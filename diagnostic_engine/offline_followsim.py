"""Committed, re-runnable residual-gap harness (offline_tree_generator_spec_v3,
Sections 8.1 + 13). Drives N simulated learners through the OFFLINE follow exactly
as the device would: base-first three-pass walk (Pass 1 base caps, Pass 2
misconception backfill, Pass 3 skill harvest), each pass across operations in
fixed order Addition, Subtraction, Multiplication, Division, with a no-compute
global question counter that hard-stops the session at the grade budget. Scores
each session from history (Section 7) and reports, per grade/allowance: residual
uncertain-skill gap vs online (overall + by operation), misconception below-target
(overall + by operation), the offline question-count distribution incl. the
over-budget fraction (must be 0 -- the cap's correctness check), and determinism.

Usage: python offline_followsim.py <grade> <lvl,lvl,...>
"""
import os
import sys, json, gzip, random, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_tree_gen as G, offline_tree_perop as P
from offline_scorer import score_history, full_params
from measure_allowance import determinism
from engine.session import start_session, record_response, compute_verdicts
from engine.coverage import select_next_coverage
from engine.api.routes import _pick_question_and_stash, _stash_resolved
from engine.misconception import derive_misconception_signals, SIGNAL_UNSURE
from offline_follow import follow_capped, LEAF, DEFAULT_OPS

TENANT = "Delhi"; N = 300
OPS = DEFAULT_OPS
BUDGET = {2: 25, 3: 42, 4: 59, 5: 76}
PHASES = (0, 1, 2)  # base, backfill, harvest
_ALL = "all"


def resolve(pool, qid, grade):
    item = pool._qxid_to_item[qid]; skill = item.split("|")[1]
    rows = pool._item_rows.get(item, {}); row = rows.get(str(grade)) or rows.get(_ALL)
    return skill, row.slip, row.guess, (pool.misconceptions_for_item(item) or {})


def base_first_follow(trees, budget, rng, mastery, pool, grade,
                      answered=None, items=None):
    """Three-pass base-first walk with the global cap (Section 8.1). Returns
    (history, qcount) with history in show order; qcount never exceeds budget.
    Thin wrapper over the pure follow_capped with a pool-based answer model.

    Mixed-mode (v11 sections 6-7): pass `answered` (item -> is_correct of the
    UNIFIED history so far) and `items` (op -> list parallel to trees[op].questions)
    to RESUME the walk from an online prefix - it routes past already-answered
    items and asks only from the first unanswered node, spending the remaining
    unified budget. Use items_for(trees, pool) to build the `items` map."""
    def answer_fn(qid, op):
        sk, slip, guess, tags = resolve(pool, qid, grade)
        correct = rng.random() < ((1 - slip) if mastery.get(sk, False) else guess)
        return correct, (qid, sk, correct, slip, guess, tags)
    return follow_capped(trees, budget, answer_fn, answered=answered, items=items)


def items_for(trees, pool):
    """op -> list of items parallel to trees[op].questions (what the shipped
    artifact carries as its `items` array; the device matches in item space)."""
    return {op: [pool._qxid_to_item[x] for x in trees[op].questions] for op in trees}


def by_op_uncertain(skills, skill_to_op):
    out = {op: 0 for op in OPS}
    for s, lab in skills.items():
        if lab == "uncertain":
            out[skill_to_op.get(s, "?")] = out.get(skill_to_op.get(s, "?"), 0) + 1
    return out


def run_online(rng, mastery, pool, cfg, lattice, grade, params, applicable, target):
    res = start_session(sub_session_id="o", learner_id="l", tenant_id=TENANT, class_id="c",
                        grade=grade, engine_version="o", params=params)
    s = res.session; s.misconception_applicable = applicable
    if res.first_question is not None:
        _pick_question_and_stash(res.first_question, s, pool, grade=grade, tenant_id=TENANT)
    while s.pending_question_id is not None:
        sk, slip, guess = (s.pending_question_skill_id, s.pending_question_slip_override,
                           s.pending_question_guess_override)
        ok = rng.random() < ((1 - slip) if mastery.get(sk, False) else guess)
        record_response(s, skill_id=sk, question_id=s.pending_question_id, is_correct=ok,
                        params=params, slip_override=slip, guess_override=guess, defer_next=True)
        nxt = select_next_coverage(s, params, pool)
        if nxt is None:
            break
        skp, pick = nxt; _stash_resolved(s, skp, pick)
    skills = {v.skill_id: v.confidence_label.value for v in compute_verdicts(s, params=params)}
    return skills


def main(grade, levels):
    cfg, lattice, pool, fps = G.load()
    params = full_params(cfg, lattice, grade)
    target = cfg.misconception.target
    budget = BUDGET[grade]
    s2op = params.skill_to_operation
    applic_all = pool.applicable_misconceptions(TENANT, grade, params.skills_in_scope)
    misc2op = {}
    for op in OPS:
        opsk = [s for s in params.skills_in_scope if s2op.get(s) == op]
        for m in pool.applicable_misconceptions(TENANT, grade, opsk):
            misc2op[m] = op
    seeds = list(range(N))
    masteries = [{s: (random.Random(sd).random() < float(params.priors.get(s, 0.5)))
                  for s in params.skills_in_scope} for sd in seeds]
    # online reference
    on_unc_op = {op: [] for op in OPS}; on_unc = []
    for i, sd in enumerate(seeds):
        sk = run_online(random.Random(2 * sd + 2), masteries[i], pool, cfg, lattice, grade,
                        params, applic_all, target)
        bo = by_op_uncertain(sk, s2op)
        on_unc.append(sum(1 for v in sk.values() if v == "uncertain"))
        for op in OPS:
            on_unc_op[op].append(bo[op])
    on_mean = st.mean(on_unc); on_op_mean = {op: st.mean(on_unc_op[op]) for op in OPS}
    print(f"\n=== G{grade} (budget {budget}; online uncertain={on_mean:.2f} "
          f"[{' '.join(op[:3]+'='+format(on_op_mean[op],'.2f') for op in OPS)}]) ===")
    print("lvl| gz_MB | gap | gap_by_op(A/S/M/D)        | below_tgt | q_mean q_max over_bud | det")
    for lvl in levels:
        trees = {op: P.PerOpBuilder(cfg, lattice, pool, grade, op, tenant=TENANT, allowance=lvl).build()
                 for op in OPS}
        gz = sum(len(gzip.compress(json.dumps(b.serialize()).encode(), 9)) for b in trees.values()) / 1024 / 1024
        det = sum(determinism(b, op, pool, n=150) for op, b in trees.items())
        off_unc, qs = [], []
        off_unc_op = {op: [] for op in OPS}; bt_all = []; bt_op = {op: [] for op in OPS}
        over = 0
        for i, sd in enumerate(seeds):
            hist, qc = base_first_follow(trees, budget, random.Random(2 * sd + 1),
                                         masteries[i], pool, grade)
            skills, sigs, sess = score_history(hist, cfg, lattice, pool, grade, TENANT, return_session=True)
            bo = by_op_uncertain(skills, s2op)
            off_unc.append(sum(1 for v in skills.values() if v == "uncertain"))
            for op in OPS:
                off_unc_op[op].append(bo[op])
            bt = [m for m in applic_all if sess.misconception_asked.get(m, 0) < target]
            bt_all.append(len(bt))
            for op in OPS:
                bt_op[op].append(sum(1 for m in bt if misc2op.get(m) == op))
            qs.append(qc); over += (qc > budget)
        gap = st.mean(off_unc) - on_mean
        gbo = {op: st.mean(off_unc_op[op]) - on_op_mean[op] for op in OPS}
        bt_mean = st.mean(bt_all); bt_op_mean = {op: st.mean(bt_op[op]) for op in OPS}
        print(f"+{lvl} | {gz:5.2f} |{gap:5.2f}| "
              f"{'/'.join(format(gbo[op],'.1f') for op in OPS):<24} | "
              f"{bt_mean:4.2f} [{'/'.join(format(bt_op_mean[op],'.1f') for op in OPS)}] | "
              f"{st.mean(qs):5.1f}  {max(qs):3d}   {over/N:5.2f} | {det}")


def run_mixed_sweep(cfg, lattice, pool, grade, n):
    """Large-sample mixed-mode equivalence sweep (v11 section 16). For n learners:
    capture a pure-online session, split it at a varied point into an online
    prefix + an offline batch, apply the prefix online and fold the batch in via
    the real ingest, and compare the mixed verdicts to the pure-online verdicts on
    the same answers. Reports verdict mismatches (must be 0) - the several-hundred-
    session analogue of the offline path's residual-gap run, on top of the CI
    equivalence tests. Run: python offline_followsim.py mixed <grade> <n>."""
    from datetime import datetime, timedelta, timezone
    from offline_scorer import run_online_capture
    from engine.offline_ingest import OfflineAnswer, apply_offline_batch
    params = full_params(cfg, lattice, grade)
    applic = pool.applicable_misconceptions(TENANT, grade, params.skills_in_scope)
    budget = params.routing_config.total_budget
    mism = done = over = 0
    offfrac = []
    for sd in range(n):
        steps, on_skills, _ = run_online_capture(cfg, lattice, pool, grade, TENANT, sd)
        if len(steps) < 3:
            continue
        k = 1 + (sd % (len(steps) - 1))                    # varied split point
        prefix, batch = steps[:k], steps[k:]
        res = start_session(sub_session_id="mx", learner_id="l", tenant_id=TENANT,
                            class_id="c", grade=grade, engine_version="mx", params=params)
        s = res.session
        s.misconception_applicable = applic
        for (qid, sk, correct, slip, guess, tags) in prefix:
            s.pending_question_misconceptions = tags
            record_response(s, skill_id=sk, question_id=qid, is_correct=correct,
                            params=params, slip_override=slip, guess_override=guess,
                            defer_next=True)
        t0 = datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
        entries = [OfflineAnswer(question_x_id=q[0], skill_id=q[1], is_correct=q[2],
                                 raw_response="x", asked_at=t0 + timedelta(minutes=i))
                   for i, q in enumerate(batch)]
        ing = apply_offline_batch(s, resume_anchor=prefix[-1][0], entries=entries,
                                  tree_id=f"Delhi/g{grade}", tree_version=1, cfg=cfg,
                                  lattice=lattice, pool=pool, grade=grade, tenant=TENANT)
        mixed = {v.skill_id: v.confidence_label.value
                 for v in compute_verdicts(ing.session, params=params)}
        mism += (mixed != on_skills)
        over += (ing.session.questions_total > budget)
        offfrac.append(len(batch) / max(1, len(steps)))
        done += 1
    print(f"G{grade} mixed sweep: {done} sessions | verdict mismatches vs pure-online: "
          f"{mism} (expect 0) | over-budget: {over} (expect 0) | mean offline fraction "
          f"{st.mean(offfrac):.2f}")
    return {"sessions": done, "mismatches": mism, "over_budget": over}


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "mixed":
        cfg, lattice, pool, fps = G.load()
        run_mixed_sweep(cfg, lattice, pool, int(sys.argv[2]), int(sys.argv[3]))
    else:
        grade = int(sys.argv[1]); levels = [int(x) for x in sys.argv[2].split(",")]
        main(grade, levels)
