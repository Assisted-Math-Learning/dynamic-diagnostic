#!/usr/bin/env python3
"""
calibrate_questions.py
======================
One script that turns a QUESTIONS file + STUDENT RESPONSES file into a single
output giving every question its slip and guess parameters.

It does, in order:
  1. KEY + CHECK   - identifies each question by a composite content key
                     (Q L1 Skill | Q L2.5 Skill | Q Type | Q Text | Q N1 | Q N2)
                     and runs
                     a consistency check on that key.
  2. CALIBRATE     - for every skill with >= 3 answered questions, fits a
                     two-class DINA model by EM to estimate slip/guess (mastery
                     is inferred from response patterns, so no MainD label is
                     needed), and runs a multi-group likelihood-ratio test to
                     decide whether each question needs one pooled value or
                     grade-specific values.
  3. BORROW        - any question that cannot be estimated (a single-question
                     skill, or a brand-new question with no/too few responses)
                     gets slip/guess copied from the nearest calibrated
                     question, type-matched, with a multiple-choice guess floor.
                     If its donor varies by grade, it inherits a per-grade
                     profile. Borrowed values are flagged provisional.
  4. OUTPUT        - writes ONE file containing every question in the questions
                     file with parameters added. A question that has
                     grade-specific values appears as several rows (one per
                     grade) plus a 'grade = all' pooled/fallback row.

To add new questions: just include them in the questions file. Those that can be
estimated will be; the rest are borrowed automatically.

Run
---
    python calibrate_questions.py \
        --questions  bank.xlsx \
        --responses  g1_5.xlsx g6.xlsx g7.xlsx g8.xlsx \
        --out        question_parameters.csv
    python calibrate_questions.py --help
"""
from __future__ import annotations
import argparse, json, math, re, sys
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np
import pandas as pd

CONTENT_ORD = {"class-one": 1, "class-two": 2, "class-three": 3, "class-four": 4, "class-five": 5}


@dataclass
class Config:
    questions_file: str = "20260429_AML_Delhi_List_of_Diagnostic_Qs.xlsx"
    response_files: list = field(default_factory=lambda: [
        "20260527_AML_Delhi_CM_SHRI_Learner_Wise_Diagnostic_Question_Attempt_Data_Grade_1_to_5__Anonymized_.xlsx",
        "20260527_AML_Delhi_CM_SHRI_Learner_Wise_Diagnostic_Question_Attempt_Data_Grade_6__Anonymized_.xlsx",
        "20260527_AML_Delhi_CM_SHRI_Learner_Wise_Diagnostic_Question_Attempt_Data_Grade_7_Part_1__Anonymized_.xlsx",
        "20260527_AML_Delhi_CM_SHRI_Learner_Wise_Diagnostic_Question_Attempt_Data_Grade_7_Part_2__Anonymized_.xlsx",
        "20260527_AML_Delhi_CM_SHRI_Learner_Wise_Diagnostic_Question_Attempt_Data_Grade_8_Part_1__Anonymized_.xlsx",
        "20260527_AML_Delhi_CM_SHRI_Learner_Wise_Diagnostic_Question_Attempt_Data_Grade_8_Part_2__Anonymized_.xlsx",
    ])
    out_file: str = "question_parameters.csv"
    cache_file: str = ""
    response_bank_file: str = ""   # optional: a questions file containing the UUIDs the
                                   # responses were collected on, used only to map those
                                   # UUIDs to the content key (when the --questions file is a
                                   # different/deduplicated set). Defaults to --questions.

    # Question-bank columns
    qid_col: str = "Q ID"
    xid_col: str = "Q X ID"
    qset_col: str = "QSet X ID"
    l1_col: str = "Q L1 Skill"
    l25_col: str = "Q L2.5 Skill"
    type_col: str = "Q Type"
    class_col: str = "Q Content Class"
    mcq_col: str = "Q MCQ Options"
    # Response columns
    resp_qid_col: str = "Question ID"
    resp_learner_col: str = "Learner ID"
    resp_grade_col: str = "Learner Grade"
    resp_score_col: str = "Learner Score"

    # The KEY identifying a unique question (composite content key)
    key_fields: tuple = ("Q L1 Skill", "Q L2.5 Skill", "Q Type", "Q Text", "Q N1", "Q N2")
    key_sep: str = "|"
    # v9 AC11: response_includes_remainder is the seventh key field. It is appended
    # ONLY for division rows (empty for non-division), so non-division keys are
    # byte-identical to the six-field key and their calibration join is unchanged.
    # The value is derived from the correct-answer column: a JSON object carrying a
    # "remainder" key means the system expects a quotient+remainder answer (True),
    # even when the operands divide evenly. Operand inference (n1 % n2) is NOT used
    # here, because it mislabels remainder-expecting items that happen to divide evenly.
    append_remainder_field: bool = True
    correct_answer_col: str = "Q Correct Answer"
    division_l1_label: str = "Division"
    # Key fields exempt from the null check (legitimately sparse). Q Text is null
    # for all non-MCQ questions, so a null there is expected, not a collision risk;
    # the collision check still catches any real merge it could cause.
    key_null_check_exempt: tuple = ("Q Text",)
    xid_grade_prefix: str = r"^q_dlg\d+_"      # for the readable label + consistency check
    unique_xid_col: str = "Unique Q X ID"      # per-question content id, if present (collision check)
    # Content-bearing fields that are NOT part of the key. If two rows share a content
    # key but differ in any of these, the key has failed to distinguish genuinely
    # different questions (a real collision). The canonical case is two MCQs with the
    # same stem/operands but different options. Fields absent from a workbook are
    # skipped. Identical-content pooling (grade/version/tenant duplicates) is benign
    # and reported as information, not a warning.
    collision_tiebreak_fields: tuple = ("Q MCQ Options", "Q Correct MCQ Option")
    # Some workbooks repeat each question once per QSet placement (question-in-QSet
    # grain). Calibration parameters are QSet-independent, so the output is collapsed
    # to one row per (question, content item) x grade. Set False to emit one row per
    # input row (per-QSet-placement) instead.
    dedup_output: bool = True
    # Column-name aliases: some workbooks export "Final Q L1 Skill" / "Final Q Content
    # Class" instead of the canonical names. The canonical name is used everywhere;
    # if it is absent on load, the first matching alias is renamed to it.
    column_aliases: tuple = (
        ("Q L1 Skill", ("Final Q L1 Skill",)),
        ("Q Content Class", ("Final Q Content Class",)),
    )

    # Estimation
    min_items_per_skill: int = 3
    min_item_responses: int = 30               # a question needs this many responses to be estimated
    min_learners_fit: int = 100
    n_restarts: int = 5
    max_iter: int = 500
    tol: float = 1e-8
    random_seed: int = 0

    # Invariance test
    invariance_min_learners: int = 200
    mg_max_iter: int = 300
    alpha: float = 0.05
    practical_threshold: float = 0.05

    # Borrowing + flags
    mcq_default_options: int = 4
    mcq_type_label: str = "Mcq"
    engine_default_slip: float = 0.10
    engine_default_guess: float = 0.15
    low_discrimination_flag: float = 0.20


# =========================================================================== #
# Stats helpers                                                               #
# =========================================================================== #
def _gammq(a, x):
    if x < 0 or a <= 0: return float("nan")
    if x == 0: return 1.0
    gln = math.lgamma(a)
    if x < a + 1.0:
        ap, s, d = a, 1.0 / a, 1.0 / a
        for _ in range(2000):
            ap += 1.0; d *= x / ap; s += d
            if abs(d) < abs(s) * 1e-14: break
        return 1.0 - s * math.exp(-x + a * math.log(x) - gln)
    tiny = 1e-300; b, c, d = x + 1.0 - a, 1.0 / tiny, 1.0 / (x + 1.0 - a); h = d
    for i in range(1, 2000):
        an = -i * (i - a); b += 2.0
        d = an * d + b; d = tiny if abs(d) < tiny else d
        c = b + an / c; c = tiny if abs(c) < tiny else c
        d = 1.0 / d; delta = d * c; h *= delta
        if abs(delta - 1.0) < 1e-14: break
    return math.exp(-x + a * math.log(x) - gln) * h


def chi2_sf(x, df):
    if x <= 0: return 1.0
    try:
        from scipy.stats import chi2
        return float(chi2.sf(x, df))
    except Exception:
        return _gammq(df / 2.0, x / 2.0)


def holm(pvals):
    p = np.asarray(pvals, float); n = len(p)
    order = np.argsort(p); adj = np.empty(n); run = 0.0
    for rank, idx in enumerate(order):
        run = max(run, (n - rank) * p[idx]); adj[idx] = min(run, 1.0)
    return adj


# =========================================================================== #
# Keys, loading, consistency check                                            #
# =========================================================================== #
def strip_grade_token(xid, prefix_re): return re.sub(prefix_re, "", str(xid))


def _derive_response_includes_remainder(row, cfg):
    """Seventh key field (v9 AC11). Delegates to the shared item_key module so the
    rule cannot drift from the lookup builder."""
    import item_key
    return item_key.derive_response_includes_remainder(
        row, l1_field=cfg.key_fields[0],
        correct_answer_col=cfg.correct_answer_col,
        division_label=cfg.division_l1_label)


def composite_key(df, cfg):
    """The composite content key. Delegates to the shared item_key module, so the
    calibration script and the lookup builder produce byte-identical keys."""
    import item_key
    return item_key.build_item_key(
        df, fields=cfg.key_fields, sep=cfg.key_sep,
        append_remainder=getattr(cfg, "append_remainder_field", False),
        correct_answer_col=cfg.correct_answer_col,
        division_label=cfg.division_l1_label)


def content_ord(val):
    if pd.isna(val): return np.nan
    if isinstance(val, (int, float)): return float(val)
    return float(CONTENT_ORD.get(str(val).strip().lower(), np.nan))


def n_options_from(raw, default):
    try:
        opts = json.loads(raw)
        return len(opts) if isinstance(opts, list) and len(opts) else default
    except Exception:
        return default


def _apply_aliases(q, cfg):
    for canonical, alts in getattr(cfg, "column_aliases", ()):
        if canonical not in q.columns:
            for a in alts:
                if a in q.columns:
                    q = q.rename(columns={a: canonical}); break
    return q


def load_questions(cfg):
    q = pd.read_excel(cfg.questions_file)
    q = _apply_aliases(q, cfg)
    need = set(cfg.key_fields) | {cfg.qid_col, cfg.l1_col, cfg.l25_col}
    if getattr(cfg, "append_remainder_field", False):
        need |= {cfg.correct_answer_col}
    if need - set(q.columns):
        sys.exit(f"Questions file missing columns: {need - set(q.columns)}")
    q["item"] = composite_key(q, cfg)
    if cfg.xid_col in q.columns:
        q["logical_item"] = q[cfg.xid_col].apply(lambda x: strip_grade_token(x, cfg.xid_grade_prefix))
    q["content_ord"] = q[cfg.class_col].apply(content_ord) if cfg.class_col in q.columns else np.nan
    q["n_options"] = q.apply(
        lambda r: n_options_from(r.get(cfg.mcq_col), cfg.mcq_default_options)
        if str(r.get(cfg.type_col)) == cfg.mcq_type_label else np.nan, axis=1)
    return q


def load_responses(cfg, qid_to_item):
    if cfg.cache_file and Path(cfg.cache_file).exists():
        print(f"Loading cached responses from {cfg.cache_file}")
        r = pd.read_pickle(cfg.cache_file)
        r["item"] = r[cfg.resp_qid_col].map(qid_to_item)
        return r.dropna(subset=["item"])
    use = [cfg.resp_learner_col, cfg.resp_grade_col, cfg.resp_qid_col, cfg.resp_score_col]
    frames = []
    for f in cfg.response_files:
        if not Path(f).exists(): sys.exit(f"Response file not found: {f}")
        print(f"Reading {Path(f).name} ...")
        frames.append(pd.read_excel(f, usecols=use))
    resp = pd.concat(frames, ignore_index=True)
    if cfg.cache_file:
        resp.to_pickle(cfg.cache_file); print(f"Cached parsed responses to {cfg.cache_file}")
    resp["item"] = resp[cfg.resp_qid_col].map(qid_to_item)
    bad = resp["item"].isna().sum()
    if bad: print(f"WARNING: {bad} responses did not map to a question (dropped).", file=sys.stderr)
    return resp.dropna(subset=["item"])


def check_key_consistency(q, cfg, out_dir):
    print("\n" + "-" * 64 + "\nKEY CONSISTENCY CHECK\n" + "-" * 64)
    ok = True
    null_check = [c for c in cfg.key_fields if c not in cfg.key_null_check_exempt]
    bad_nulls = {c: int(q[c].isna().sum()) for c in null_check if c in q.columns and q[c].isna().sum()}
    if bad_nulls:
        ok = False; print("WARN: nulls in key fields (would merge distinct questions):")
        for c, n in bad_nulls.items(): print(f"      {c}: {n}")
    else:
        print(f"Null check: OK - no nulls in key fields {null_check}")
        if cfg.key_null_check_exempt:
            print(f"            (exempt from null check: {list(cfg.key_null_check_exempt)})")
    print(f"Composite-key groups: {q['item'].nunique()}")

    # Pick a per-question identity to compare the content key against:
    #   1) a dedicated unique-question-id column (tenant-agnostic), else
    #   2) the grade-stripped X-ID suffix (only if that naming convention is present).
    ident, ident_name = None, None
    if cfg.unique_xid_col in q.columns:
        ident, ident_name = q[cfg.unique_xid_col].astype(str), cfg.unique_xid_col
    elif cfg.xid_col in q.columns:
        suf = q[cfg.xid_col].apply(lambda x: strip_grade_token(x, cfg.xid_grade_prefix))
        if int((suf != q[cfg.xid_col]).sum()) >= 0.5 * len(q):
            ident, ident_name = suf, "X-ID suffix"

    report = None
    if ident is None:
        print("Collision check skipped (no per-question id column available).")
    else:
        tmp = q.assign(_id=ident)
        tb = [c for c in cfg.collision_tiebreak_fields if c in q.columns]
        n_key = len(cfg.key_fields)  # length of the base key (the 7th field is appended after these)
        base_key = lambda it: cfg.key_sep.join(str(it).split(cfg.key_sep)[:n_key])
        print(f"Distinct questions by {ident_name}: {ident.nunique()}")
        print(f"Tiebreak fields checked (content outside the key): {tb or 'none present'}")

        rows = []
        genuine_merge = benign_merge = genuine_split = benign_split = 0

        # MERGE: one content key shared by several rows. Genuine only if those rows
        # differ in a tiebreak field; otherwise it is identical-content pooling.
        for k, grp in tmp.groupby("item"):
            combos = grp[tb].fillna("").astype(str).drop_duplicates() if tb else None
            differs = combos is not None and len(combos) > 1
            if differs:
                genuine_merge += 1
                detail = " || ".join(" | ".join(f"{c}={v}" for c, v in zip(tb, r)) for r in combos.values)
                rows.append(dict(kind="genuine_merge", key=k, count=int(grp["_id"].nunique()),
                                 detail=detail[:500],
                                 members=", ".join(map(str, sorted(grp["_id"].unique())))))
            elif grp["_id"].nunique() > 1:
                benign_merge += 1

        # SPLIT: one question id across several content keys. Genuine only if the keys
        # differ beyond the remainder field; a remainder-only split is the intended
        # division behaviour (one question, two answer formats).
        for idv, grp in tmp.groupby("_id"):
            items = grp["item"].unique()
            if len(items) <= 1:
                continue
            if len({base_key(it) for it in items}) > 1:
                genuine_split += 1
                rows.append(dict(kind="genuine_split", key=str(idv), count=len(items),
                                 detail=" vs ".join(sorted(map(str, items)))[:500], members=""))
            else:
                benign_split += 1

        print(f"Benign pooling (expected): {benign_merge} content key(s) pool grade/version/tenant "
              f"duplicates of one question; {benign_split} question(s) split only by the remainder field.")
        if genuine_merge or genuine_split:
            ok = False
            print(f"WARN: GENUINE ambiguity - {genuine_merge} key(s) merge questions that differ in "
                  f"{tb or 'content'}; {genuine_split} question(s) split across materially different keys.")
        else:
            print("Genuine-ambiguity check: OK - every shared key is identical-content pooling.")
        summary = dict(kind="summary", key="(counts)",
                       count=int(q["item"].nunique()),
                       detail=f"genuine_merge={genuine_merge}; genuine_split={genuine_split}; "
                              f"benign_merge={benign_merge}; benign_split={benign_split}", members="")
        report = pd.DataFrame([summary] + rows)
    print("RESULT:", "PASS" if ok else "WARN - review above"); print("-" * 64)
    if out_dir is not None:
        (report if report is not None else pd.DataFrame([dict(kind="ok", key="all", count=0, detail="", members="")])
         ).to_csv(Path(out_dir) / "key_consistency_report.csv", index=False)
    return ok


# =========================================================================== #
# DINA model: single-group (point estimates) and multi-group (invariance LRT) #
# =========================================================================== #
def _em_once(M, rng, jitter, max_iter, tol):
    n, m = M.shape; im = M.mean(0)
    if jitter:
        g = np.clip(im - rng.uniform(0.05, 0.25, m), 0.02, 0.48); pm = np.clip(im + rng.uniform(0.02, 0.15, m), 0.55, 0.995)
    else:
        g = np.clip(im - 0.15, 0.02, 0.48); pm = np.clip(im + 0.07, 0.55, 0.995)
    pi = float(np.clip(M.mean(), 0.1, 0.9)); prev = -np.inf
    for _ in range(max_iter):
        ll1 = (M * np.log(pm) + (1 - M) * np.log(1 - pm)).sum(1) + np.log(pi)
        ll0 = (M * np.log(g) + (1 - M) * np.log(1 - g)).sum(1) + np.log(1 - pi)
        mx = np.maximum(ll1, ll0); e1, e0 = np.exp(ll1 - mx), np.exp(ll0 - mx)
        r = e1 / (e1 + e0); w1, w0 = r.sum(), (1 - r).sum()
        pm = np.clip((r[:, None] * M).sum(0) / w1, 0.50, 0.999)
        g = np.clip(((1 - r)[:, None] * M).sum(0) / w0, 0.001, 0.50)
        pi = float(np.clip(w1 / n, 0.01, 0.99)); ll = float((mx + np.log(e1 + e0)).sum())
        if abs(ll - prev) < tol: break
        prev = ll
    if pm.mean() < g.mean(): pm, g, pi = 1 - g, 1 - pm, 1 - pi
    return 1 - pm, g, pi, ll


def fit_two_class(M, cfg):
    rng = np.random.default_rng(cfg.random_seed); best = None
    for r in range(cfg.n_restarts):
        out = _em_once(M, rng, r > 0, cfg.max_iter, cfg.tol)
        if best is None or out[3] > best[3]: best = out
    return best[0], best[1], best[2]


def _mg_loglik(M, grp, pm, gs, pi):
    PM, GG = pm[grp], gs[grp]
    ll1 = (M * np.log(PM) + (1 - M) * np.log(1 - PM)).sum(1) + np.log(pi[grp])
    ll0 = (M * np.log(GG) + (1 - M) * np.log(1 - GG)).sum(1) + np.log(1 - pi[grp])
    mx = np.maximum(ll1, ll0)
    return float((mx + np.log(np.exp(ll1 - mx) + np.exp(ll0 - mx))).sum()), ll1, ll0


def fit_multigroup(M, grp, free_mask, cfg, init):
    n, m = M.shape; G = int(grp.max()) + 1; cnt = np.bincount(grp, minlength=G).astype(float)
    pm0, g0 = init; pm = np.tile(pm0, (G, 1)).astype(float); gs = np.tile(g0, (G, 1)).astype(float)
    pi = np.clip(np.bincount(grp, weights=M.mean(1), minlength=G) / np.maximum(cnt, 1), .05, .95); prev = -np.inf
    for _ in range(cfg.mg_max_iter):
        ll, ll1, ll0 = _mg_loglik(M, grp, pm, gs, pi)
        if abs(ll - prev) < cfg.tol: break
        prev = ll
        mx = np.maximum(ll1, ll0); e1, e0 = np.exp(ll1 - mx), np.exp(ll0 - mx); r = e1 / (e1 + e0)
        pi = np.clip(np.bincount(grp, weights=r, minlength=G) / np.maximum(cnt, 1), .01, .99)
        W1 = np.bincount(grp, weights=r, minlength=G); W0 = np.bincount(grp, weights=1 - r, minlength=G)
        num1 = np.stack([np.bincount(grp, weights=r * M[:, i], minlength=G) for i in range(m)], 1)
        num0 = np.stack([np.bincount(grp, weights=(1 - r) * M[:, i], minlength=G) for i in range(m)], 1)
        pm_free = np.clip(num1 / np.maximum(W1[:, None], 1e-9), .50, .999)
        gs_free = np.clip(num0 / np.maximum(W0[:, None], 1e-9), .001, .50)
        pm_sh = np.clip((r @ M) / r.sum(), .50, .999); gs_sh = np.clip(((1 - r) @ M) / (1 - r).sum(), .001, .50)
        pm = np.where(free_mask[None, :], pm_free, pm_sh[None, :]); gs = np.where(free_mask[None, :], gs_free, gs_sh[None, :])
    ll, _, _ = _mg_loglik(M, grp, pm, gs, pi)
    if pm.mean() < gs.mean():
        pm, gs, pi = 1 - gs, 1 - pm, 1 - pi; ll, _, _ = _mg_loglik(M, grp, pm, gs, pi)
    return dict(pm=pm, gs=gs, pi=pi, loglik=ll)


def run_invariance_lrt(wide, items, cfg):
    counts = wide["__grade"].value_counts()
    grades = sorted(g for g, c in counts.items() if c >= cfg.invariance_min_learners)
    if len(grades) < 2: return None
    sub = wide[wide["__grade"].isin(grades)]; M = sub[items].values.astype(float)
    gmap = {g: k for k, g in enumerate(grades)}; grp = sub["__grade"].map(gmap).values.astype(int)
    m, G = len(items), len(grades)
    slip0, guess0, _ = fit_two_class(M, cfg); init = (1 - slip0, guess0)
    con = fit_multigroup(M, grp, np.zeros(m, bool), cfg, init)
    unc = fit_multigroup(M, grp, np.ones(m, bool), cfg, init)
    items_by, grade_vals = {}, {}
    for i, it in enumerate(items):
        mask = np.ones(m, bool); mask[i] = False
        coni = fit_multigroup(M, grp, mask, cfg, init)
        LRi = max(2 * (unc["loglik"] - coni["loglik"]), 0.0)
        sg, gg = 1 - unc["pm"][:, i], unc["gs"][:, i]
        items_by[it] = dict(lr=round(LRi, 3), df=2 * (G - 1), p_raw=chi2_sf(LRi, 2 * (G - 1)),
                            slip_spread=round(float(sg.max() - sg.min()), 4),
                            guess_spread=round(float(gg.max() - gg.min()), 4))
        grade_vals[it] = {int(grades[k]): (float(1 - unc["pm"][k, i]), float(unc["gs"][k, i])) for k in range(G)}
    return dict(items_by=items_by, grade_vals=grade_vals)


def build_skill_wide(resp, cfg, items, learner_grade):
    sub = resp[resp["item"].isin(items)]
    wide = sub.pivot_table(index=cfg.resp_learner_col, columns="item", values=cfg.resp_score_col, aggfunc="first")
    if not set(items).issubset(wide.columns): return None
    wide = wide[items].dropna(); wide["__grade"] = wide.index.map(learner_grade)
    return wide


# =========================================================================== #
# Borrowing                                                                   #
# =========================================================================== #
def donor_skill_stats(params, grade_varying):
    est = params[params["source"] == "estimated"]
    g = est.groupby("l2_5_skill")
    df = pd.DataFrame({
        "l1_skill": g["l1_skill"].first(), "slip_med": g["slip"].median(), "guess_med": g["guess"].median(),
        "q_type": g["q_type"].agg(lambda s: s.mode().iat[0] if len(s.mode()) else None),
        "content_ord": g["content_ord"].median(), "raw_p": g["raw_p_correct"].mean()})
    df["grade_varying"] = df.index.isin(grade_varying)
    return df


def skill_grade_profiles(item_grade_vals, params):
    skill_of = params.set_index("item")["l2_5_skill"].to_dict()
    by_skill = {}
    for it, gv in item_grade_vals.items():
        sk = skill_of.get(it)
        if sk is None: continue
        for gr, (s, gu) in gv.items():
            by_skill.setdefault(sk, {}).setdefault(gr, []).append((s, gu))
    return {sk: {gr: (float(np.median([v[0] for v in lst])), float(np.median([v[1] for v in lst])))
                 for gr, lst in grd.items()} for sk, grd in by_skill.items()}


def _nearest(cands, t_ord, t_rawp):
    d_class = (cands["content_ord"] - t_ord).abs() if not pd.isna(t_ord) else 0.0
    d_diff = (cands["raw_p"] - t_rawp).abs() if (t_rawp is not None and not pd.isna(t_rawp)) else 0.0
    score = (d_class.fillna(99) if hasattr(d_class, "fillna") else d_class) * 10 + (d_diff if np.ndim(d_diff) else 0)
    return cands.assign(_s=score).sort_values("_s")


def _mcq_floor(guess, is_mcq, nopt):
    if is_mcq:
        fl = 1.0 / max(int(nopt), 2)
        if guess < fl: return fl, True
    return guess, False


def borrow_one(target, donors, sgp, cfg):
    skill, op, qtype = target["l2_5_skill"], target["l1_skill"], target["q_type"]
    tord, trawp = target.get("content_ord", np.nan), target.get("raw_p", None)
    nopt = target.get("n_options", cfg.mcq_default_options); is_mcq = str(qtype) == cfg.mcq_type_label
    out = dict(slip=np.nan, guess=np.nan, method="", slip_donor="", guess_donor="",
               mcq_floor_applied=False, grade_specific=False, per_grade=None)
    if len(donors) == 0:
        out.update(slip=cfg.engine_default_slip, guess=cfg.engine_default_guess,
                   method="default_no_donor", slip_donor="default", guess_donor="default")
    elif skill in donors.index:
        slip_donor = guess_donor = skill; out["method"] = "borrow_same_skill"
    else:
        same_op = donors[donors["l1_skill"] == op]; pool = same_op if len(same_op) else donors
        out["method"] = "borrow_nearest_skill" if len(same_op) else "borrow_global_nearest_skill"
        slip_donor = _nearest(pool, tord, trawp).index[0]
        st = pool[pool["q_type"] == qtype]
        if not len(st): st = donors[donors["q_type"] == qtype]
        guess_donor = _nearest(st, tord, trawp).index[0] if len(st) else None
    if out["method"] == "default_no_donor":
        out["discrimination"] = round(1 - out["slip"] - out["guess"], 4); return out

    out["slip_donor"] = slip_donor
    out["guess_donor"] = guess_donor if guess_donor else (f"mcq_floor_1/{int(nopt)}" if is_mcq else "global_median")
    pooled_slip = float(donors.loc[slip_donor, "slip_med"])
    if guess_donor: pooled_guess = float(donors.loc[guess_donor, "guess_med"])
    elif is_mcq: pooled_guess = 1.0 / max(int(nopt), 2)
    else: pooled_guess = float(donors["guess_med"].median())
    pooled_guess, floored = _mcq_floor(pooled_guess, is_mcq, nopt)
    floored = floored or (is_mcq and not guess_donor)
    out["slip"] = round(pooled_slip, 4); out["guess"] = round(pooled_guess, 4)
    out["discrimination"] = round(1 - out["slip"] - out["guess"], 4); out["mcq_floor_applied"] = floored

    slip_gv = sgp and donors.loc[slip_donor, "grade_varying"] and slip_donor in sgp
    guess_gv = sgp and guess_donor and donors.loc[guess_donor, "grade_varying"] and guess_donor in sgp
    if slip_gv or guess_gv:
        grades = sorted((sgp.get(slip_donor) or sgp.get(guess_donor)).keys())
        per = []
        for gg in grades:
            s = sgp[slip_donor][gg][0] if slip_gv and gg in sgp[slip_donor] else pooled_slip
            gu = sgp[guess_donor][gg][1] if guess_gv and gg in sgp[guess_donor] else pooled_guess
            gu, fl = _mcq_floor(gu, is_mcq, nopt); out["mcq_floor_applied"] = out["mcq_floor_applied"] or fl
            per.append((int(gg), round(float(s), 4), round(float(gu), 4)))
        out["grade_specific"] = True; out["per_grade"] = per
    return out


# =========================================================================== #
# Orchestration                                                               #
# =========================================================================== #
def run(cfg, questions=None, resp=None):
    out_dir = Path(cfg.out_file).parent if str(Path(cfg.out_file).parent) else Path(".")
    out_dir.mkdir(parents=True, exist_ok=True)
    if questions is None:
        questions = load_questions(cfg)
    check_key_consistency(questions, cfg, out_dir)
    if cfg.response_bank_file:
        rbank = pd.read_excel(cfg.response_bank_file)
        rbank = _apply_aliases(rbank, cfg)
        rbank["item"] = composite_key(rbank, cfg)
        qid_to_item = dict(zip(rbank[cfg.qid_col], rbank["item"]))
        print(f"Response UUIDs decoded via response bank: {Path(cfg.response_bank_file).name} "
              f"({len(qid_to_item)} questions)")
    else:
        qid_to_item = dict(zip(questions[cfg.qid_col], questions["item"]))
    if resp is None:
        resp = load_responses(cfg, qid_to_item)

    learner_grade = resp.drop_duplicates(cfg.resp_learner_col).set_index(cfg.resp_learner_col)[cfg.resp_grade_col].to_dict()
    qmeta = questions.drop_duplicates("item").set_index("item")
    items_by_skill = questions.drop_duplicates("item").groupby(cfg.l25_col)["item"].apply(list)
    rc = resp.groupby("item").size()
    raw_p = resp.groupby("item")[cfg.resp_score_col].mean()

    rows, item_grade_vals = [], {}

    def base_row(it, method, source):
        return dict(item=it, l1_skill=qmeta.loc[it, cfg.l1_col], l2_5_skill=qmeta.loc[it, cfg.l25_col],
                    q_type=qmeta.loc[it, cfg.type_col], content_ord=qmeta.loc[it, "content_ord"],
                    n_options=qmeta.loc[it, "n_options"], raw_p_correct=round(float(raw_p.get(it, np.nan)), 4)
                    if it in raw_p.index else np.nan, method=method, source=source)

    for skill, items in items_by_skill.items():
        responded = [it for it in items if rc.get(it, 0) >= cfg.min_item_responses]
        estimable = len(responded) >= cfg.min_items_per_skill
        wide = build_skill_wide(resp, cfg, responded, learner_grade) if estimable else None
        if estimable and (wide is None or len(wide) < cfg.min_learners_fit):
            estimable = False
        if estimable:
            slip, guess, prev = fit_two_class(wide[responded].values.astype(float), cfg)
            lrt = run_invariance_lrt(wide, responded, cfg)
            for j, it in enumerate(responded):
                s, g = float(slip[j]), float(guess[j]); lr = (lrt["items_by"].get(it, {}) if lrt else {})
                r = base_row(it, "estimated", "estimated")
                r.update(slip=round(s, 4), guess=round(g, 4), discrimination=round(1 - s - g, 4),
                         mastery_prevalence=round(float(prev), 4), n_learners=int(len(wide)),
                         lr_stat=lr.get("lr", np.nan), lr_df=lr.get("df", np.nan), p_raw=lr.get("p_raw", np.nan),
                         slip_spread=lr.get("slip_spread", np.nan), guess_spread=lr.get("guess_spread", np.nan),
                         low_discrimination_flag=("low" if (1 - s - g) < cfg.low_discrimination_flag else ""))
                rows.append(r)
                if lrt and it in lrt["grade_vals"]: item_grade_vals[it] = lrt["grade_vals"][it]
            for it in items:                      # questions in the skill with no/low data -> borrow (same skill)
                if it not in responded:
                    rows.append(base_row(it, "fallback_no_response_data", "borrowed"))
        else:
            for it in items:                      # whole skill not estimable -> borrow (nearest skill)
                tag = "fallback_single_item_skill" if len(items) < cfg.min_items_per_skill else "fallback_skill_no_data"
                rows.append(base_row(it, tag, "borrowed"))

    params = pd.DataFrame(rows)
    for c in ["slip", "guess", "discrimination", "mastery_prevalence", "n_learners", "lr_stat", "lr_df",
              "p_raw", "slip_spread", "guess_spread"]:
        if c not in params.columns: params[c] = np.nan
    for c in ["low_discrimination_flag", "slip_donor", "guess_donor", "invariance_decision"]:
        if c not in params.columns: params[c] = ""
    if "mcq_floor_applied" not in params.columns: params["mcq_floor_applied"] = False
    if "grade_specific" not in params.columns: params["grade_specific"] = False

    # --- grade decision for estimated items (significant AND practically large) ---
    est = params["source"] == "estimated"; has_p = est & params["p_raw"].notna()
    params["p_holm"] = np.nan
    if has_p.any():
        params.loc[has_p, "p_holm"] = holm(params.loc[has_p, "p_raw"].values)
    spread = params[["slip_spread", "guess_spread"]].max(axis=1)
    decide_gc = has_p & (params["p_holm"] < cfg.alpha) & (spread > cfg.practical_threshold)
    params.loc[est, "invariance_decision"] = np.where(decide_gc[est], "grade_condition", "pool")
    params.loc[est & params["invariance_decision"].eq("grade_condition"), "grade_specific"] = True

    # --- borrow for every non-estimated question ---
    grade_varying = set(params.loc[params["invariance_decision"] == "grade_condition", "l2_5_skill"])
    donors = donor_skill_stats(params, grade_varying)
    sgp = skill_grade_profiles(item_grade_vals, params)
    for idx in params.index[params["source"] == "borrowed"]:
        r = params.loc[idx]
        tgt = dict(l1_skill=r["l1_skill"], l2_5_skill=r["l2_5_skill"], q_type=r["q_type"],
                   content_ord=r["content_ord"], raw_p=r["raw_p_correct"], n_options=r["n_options"])
        b = borrow_one(tgt, donors, sgp, cfg)
        params.at[idx, "slip"] = b["slip"]; params.at[idx, "guess"] = b["guess"]
        params.at[idx, "discrimination"] = b["discrimination"]; params.at[idx, "method"] = r["method"] + ":" + b["method"]
        params.at[idx, "slip_donor"] = b["slip_donor"]; params.at[idx, "guess_donor"] = b["guess_donor"]
        params.at[idx, "mcq_floor_applied"] = b["mcq_floor_applied"]; params.at[idx, "grade_specific"] = b["grade_specific"]
        if b["per_grade"]:
            item_grade_vals[r["item"]] = {g: (s, gu) for g, s, gu in b["per_grade"]}

    out = assemble_output(questions, params, item_grade_vals, cfg)
    out.to_csv(cfg.out_file, index=False)
    print_summary(params, out, cfg)
    return out, params


def assemble_output(questions, params, item_grade_vals, cfg):
    pinfo = params.set_index("item")
    # Collapse QSet placements: a question may appear once per QSet, but calibration
    # parameters do not depend on QSet. Emit one row per (question, content item).
    # Keying on (xid, item) preserves the division two-format splits, where a single
    # Q X ID legitimately carries two content items (remainder vs no-remainder).
    if getattr(cfg, "dedup_output", True):
        dcols = [c for c in (cfg.xid_col, "item") if c in questions.columns] or ["item"]
        questions = questions.drop_duplicates(subset=dcols)
    rows = []
    for _, q in questions.iterrows():
        it = q["item"]
        if it not in pinfo.index: continue
        r = pinfo.loc[it]
        recs = [("all", r["slip"], r["guess"], r["discrimination"])]
        if bool(r["grade_specific"]) and it in item_grade_vals:
            for g, (s, gu) in sorted(item_grade_vals[it].items()):
                recs.append((int(g), round(float(s), 4), round(float(gu), 4), round(1 - s - gu, 4)))
        for g, s, gu, disc in recs:
            rows.append(dict(
                q_x_id=q.get(cfg.xid_col, ""), qset_x_id=q.get(cfg.qset_col, ""), q_id=q[cfg.qid_col],
                item=it, logical_item=q.get("logical_item", ""), l1_skill=r["l1_skill"], l2_5_skill=r["l2_5_skill"],
                q_type=r["q_type"], grade=g, slip=s, guess=gu, discrimination=disc,
                source=r["source"], method=r["method"], grade_specific=bool(r["grade_specific"]),
                provisional=(r["source"] == "borrowed"), invariance_decision=r.get("invariance_decision", ""),
                slip_donor=r.get("slip_donor", ""), guess_donor=r.get("guess_donor", ""),
                mcq_floor_applied=bool(r.get("mcq_floor_applied", False)),
                n_learners=r.get("n_learners", np.nan), mastery_prevalence=r.get("mastery_prevalence", np.nan),
                lr_stat=r.get("lr_stat", np.nan), p_holm=r.get("p_holm", np.nan)))
    return pd.DataFrame(rows).sort_values(["qset_x_id", "q_x_id", "grade"])


def print_summary(params, out, cfg):
    est = params[params["source"] == "estimated"]; bor = params[params["source"] == "borrowed"]
    print("\n" + "=" * 66 + "\nSUMMARY\n" + "=" * 66)
    print(f"Questions (unique items)         : {len(params)}")
    print(f"  estimated                      : {len(est)}")
    print(f"  borrowed                       : {len(bor)}")
    if len(est):
        gc = int((est["invariance_decision"] == "grade_condition").sum())
        print(f"  estimated -> grade-specific    : {gc}  (pooled: {len(est)-gc})")
        print(f"Slip  median {est.slip.median():.3f} | Guess median {est.guess.median():.3f}")
    fl = int(params["mcq_floor_applied"].sum())
    if fl: print(f"MCQ guess floor applied to       : {fl} question(s)")
    print(f"Output rows (question x grade)   : {len(out)}")
    print("=" * 66)
    print(f"Wrote: {cfg.out_file}")
    print(f"       {Path(cfg.out_file).parent / 'key_consistency_report.csv'}")


def parse_args(cfg):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--questions", default=cfg.questions_file)
    p.add_argument("--responses", nargs="+", default=cfg.response_files)
    p.add_argument("--response-bank", default=cfg.response_bank_file,
                   help="Questions file containing the UUIDs the responses were collected on "
                        "(used to map responses to the content key when --questions is a different set)")
    p.add_argument("--out", default=cfg.out_file)
    p.add_argument("--cache", default=cfg.cache_file)
    p.add_argument("--min-items", type=int, default=cfg.min_items_per_skill)
    p.add_argument("--min-item-responses", type=int, default=cfg.min_item_responses)
    p.add_argument("--restarts", type=int, default=cfg.n_restarts)
    p.add_argument("--alpha", type=float, default=cfg.alpha)
    p.add_argument("--practical", type=float, default=cfg.practical_threshold)
    p.add_argument("--mcq-default-options", type=int, default=cfg.mcq_default_options)
    p.add_argument("--seed", type=int, default=cfg.random_seed)
    a = p.parse_args()
    cfg.questions_file, cfg.response_files, cfg.out_file = a.questions, a.responses, a.out
    cfg.response_bank_file = a.response_bank
    cfg.cache_file, cfg.min_items_per_skill, cfg.min_item_responses = a.cache, a.min_items, a.min_item_responses
    cfg.n_restarts, cfg.alpha, cfg.practical_threshold = a.restarts, a.alpha, a.practical
    cfg.mcq_default_options, cfg.random_seed = a.mcq_default_options, a.seed
    return cfg


if __name__ == "__main__":
    run(parse_args(Config()))
