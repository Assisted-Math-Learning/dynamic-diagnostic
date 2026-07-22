#!/usr/bin/env python3
"""
AML eligibility tagger (Script 1).

Tags each Fib question with the misconception codes that could fire on it, by
probing the deterministic classifier, and folds in real misses recorded by the
runtime. Writes a version-stamped eligibility table and updates a pointer that
the runtime follows.

Run modes:
  all  (a)  re-probe every question; fold ALL log rows (needed after a rules change)
  new  (b)  probe only questions not already in the table; fold pending log rows
            into existing and new questions
  log  (c)  fold pending log rows only; no probing

Fallbacks:
  no table present            -> force mode 'all'
  table present, no log, 'new'-> probe new questions only (log half is a no-op)
  table present, no log, 'log'-> nothing to do; report and exit
The script announces at start which mode it is actually running.

Question identity key (carried as labels; eligibility itself depends only on the
last four): Q L1 Skill | Q L2.5 Skill | Q Type | Q Text | Q N1 | Q N2 |
Response Includes Remainder.

Usage:
  python aml_tag.py --questions delhi_question_list.parquet --mode all --mult-window fast
  python aml_tag.py --mode log
  python aml_tag.py --status
"""
import os, sys, json, glob, argparse, datetime, shutil
from collections import defaultdict
import pandas as pd
import aml_engine as E

# ---- intrinsic key (what eligibility actually depends on) ----
def intrinsic_key(op, n1, n2, rir):
    o = E.norm_op(op)
    rir = bool(rir) if o == "division" else None
    return (o, int(n1), int(n2), rir)

def key_str(k):
    return f"{k[0]}|{k[1]}|{k[2]}|{k[3]}"

# ---- table / pointer / log paths ----
def pointer_path(d): return os.path.join(d, "eligibility_table_current.txt")
def master_log_path(d): return os.path.join(d, "miss_log_master.csv")
def raw_log_path(d): return os.path.join(d, "miss_log.csv")

MASTER_COLS = ["operation", "n1", "n2", "response_includes_remainder",
               "response", "code", "hit_count", "last_seen", "folded_in_version"]
RAW_COLS = ["ts", "operation", "n1", "n2", "response_includes_remainder", "response", "code"]

def load_pointer(d):
    p = pointer_path(d)
    if not os.path.exists(p):
        return None
    name = open(p).read().strip()
    fp = os.path.join(d, name)
    return fp if os.path.exists(fp) else None

def load_table(d):
    fp = load_pointer(d)
    if fp is None:
        return None
    return json.load(open(fp))

def next_version(d):
    today = datetime.date.today().strftime("%Y%m%d")
    n = 1
    for f in glob.glob(os.path.join(d, f"eligibility_table_{today}_v*.json")):
        try:
            n = max(n, int(f.rsplit("_v", 1)[1].split(".")[0]) + 1)
        except (ValueError, IndexError):
            pass
    return f"{today}_v{n}"

# ---- log handling ----
def load_master(d):
    p = master_log_path(d)
    if os.path.exists(p):
        df = pd.read_csv(p, dtype={"response": str, "code": str})
        return df
    return pd.DataFrame(columns=MASTER_COLS)

def rotate_and_merge_raw(d, master):
    """Move the runtime's append-only raw log aside and merge into master (dedup)."""
    raw = raw_log_path(d)
    if not os.path.exists(raw):
        return master, 0
    tmp = raw + f".processing_{datetime.datetime.now():%Y%m%d%H%M%S}"
    shutil.move(raw, tmp)                      # runtime creates a fresh raw on next append
    rdf = pd.read_csv(tmp, dtype={"response": str, "code": str})
    if rdf.empty:
        return master, 0
    rdf["response_includes_remainder"] = rdf["response_includes_remainder"].map(_norm_rir)
    agg = (rdf.groupby(["operation", "n1", "n2", "response_includes_remainder", "response", "code"], dropna=False)
              .agg(hit_count=("ts", "size"), last_seen=("ts", "max")).reset_index())
    mkey = ["operation", "n1", "n2", "response_includes_remainder", "response", "code"]
    midx = {tuple(r): i for i, r in enumerate(master[mkey].astype(object).values.tolist())} if len(master) else {}
    added = 0
    new_rows = []
    for r in agg.itertuples(index=False):
        k = (r.operation, r.n1, r.n2, r.response_includes_remainder, r.response, r.code)
        if k in midx:
            i = midx[k]
            master.at[i, "hit_count"] = int(master.at[i, "hit_count"]) + int(r.hit_count)
            master.at[i, "last_seen"] = max(str(master.at[i, "last_seen"]), str(r.last_seen))
        else:
            new_rows.append({**dict(zip(mkey, k)), "hit_count": int(r.hit_count),
                             "last_seen": r.last_seen, "folded_in_version": None})
            added += 1
    if new_rows:
        master = pd.concat([master, pd.DataFrame(new_rows)], ignore_index=True)
    return master, added

def _norm_rir(v):
    s = str(v).strip().lower()
    if s in ("true", "1"): return True
    if s in ("false", "0"): return False
    return None

# ---- question list ----
def load_questions(path):
    df = pd.read_parquet(path) if path.endswith(".parquet") else pd.read_csv(path)
    df = df[df["q_type"] == "Fib"].copy()
    # derive response_includes_remainder if absent
    if "response_includes_remainder" not in df.columns:
        df["response_includes_remainder"] = df.apply(
            lambda r: (str(r.get("q_correct_answer", "")).strip().startswith("{"))
            if r["q_l1_skill"] == "Division" else None, axis=1)
    return df

# ---- main ----
def run(args):
    d = args.table_dir
    os.makedirs(d, exist_ok=True)
    mult_window = 200 if args.mult_window == "regular" else 25

    current = load_table(d)

    # ----- status -----
    if args.status:
        master = load_master(d)
        # account for not-yet-merged raw rows as pending too
        raw_pending = 0
        if os.path.exists(raw_log_path(d)):
            raw_pending = max(0, sum(1 for _ in open(raw_log_path(d))) - 1)
        master_pending = int(master["folded_in_version"].isna().sum()) if len(master) else 0
        ver = current["version"] if current else "(none)"
        print(f"current table version: {ver}")
        print(f"questions in table:    {len(current['questions']) if current else 0}")
        print(f"pending master rows:   {master_pending}")
        print(f"un-merged raw rows:    {raw_pending}")
        print(f"fold needed:           {'yes' if (master_pending + raw_pending) > 0 else 'no'}")
        return

    # ----- resolve effective mode + fallbacks -----
    mode = args.mode
    note = None
    if current is None:
        if mode != "all":
            note = f"no existing table -> forcing mode 'all' (requested '{mode}')"
        mode = "all"
    have_log = os.path.exists(master_log_path(d)) or os.path.exists(raw_log_path(d))
    if mode in ("new", "log") and not have_log:
        if mode == "log":
            print("mode 'log' but no log present: nothing to fold. Exiting.")
            return
        note = "mode 'new' but no log present: probing new questions only (log fold is a no-op)"

    print(f"running mode: {mode}" + (f"   [{note}]" if note else "") +
          f"   (mult_window={mult_window})")

    if mode in ("all", "new") and not args.questions:
        sys.exit("error: --questions is required for modes 'all' and 'new'")

    # ----- fold log -----
    master = load_master(d)
    master, merged = rotate_and_merge_raw(d, master)
    new_version = next_version(d)
    if mode == "all":
        fold_mask = pd.Series([True] * len(master))
    else:
        fold_mask = master["folded_in_version"].isna() if len(master) else pd.Series([], dtype=bool)
    log_codes = defaultdict(set)
    if len(master):
        for r in master[fold_mask].itertuples(index=False):
            k = intrinsic_key(r.operation, r.n1, r.n2, _norm_rir(r.response_includes_remainder))
            log_codes[k].add(r.code)

    # mode 'log' with nothing pending: do not churn a new version
    if mode == "log" and (not len(master) or int(fold_mask.sum()) == 0):
        if merged:
            master.to_csv(master_log_path(d), index=False)
        print("mode 'log': no pending rows to fold; current version unchanged.")
        return

    # ----- build questions for the new table -----
    existing_by_id = {q["question_id"]: q for q in current["questions"]} if current else {}
    out_questions = {}
    syn_cache = {}

    def synth(k):
        if k not in syn_cache:
            o, n1, n2, rir = k
            syn_cache[k] = set(E.eligible_codes(o, n1, n2, system_expects_remainder=rir,
                                                mult_window=mult_window))
        return syn_cache[k]

    if mode in ("all", "new"):
        ql = load_questions(args.questions)
        for r in ql.itertuples(index=False):
            k = intrinsic_key(r.q_l1_skill, r.q_n1, r.q_n2, r.response_includes_remainder)
            qid = r.question_id
            is_new = qid not in existing_by_id
            if mode == "all" or is_new:
                elig = set(synth(k))
            else:  # mode 'new', existing question: keep its current tags
                elig = set(existing_by_id[qid]["eligible_codes"])
            elig |= log_codes.get(k, set())
            out_questions[qid] = {
                "q_l1_skill": r.q_l1_skill, "q_l2_5_skill": r.q_l2_5_skill,
                "q_type": r.q_type, "q_text": r.q_text,
                "q_n1": int(r.q_n1), "q_n2": int(r.q_n2),
                "response_includes_remainder": (bool(r.response_includes_remainder)
                    if E.norm_op(r.q_l1_skill) == "division" else None),
                "question_id": qid, "eligible_codes": sorted(elig),
            }
        # mode 'new': also keep existing table questions not in the list, plus fold log into them
        if mode == "new":
            for qid, q in existing_by_id.items():
                if qid not in out_questions:
                    k = intrinsic_key(q["q_l1_skill"], q["q_n1"], q["q_n2"],
                                      q["response_includes_remainder"])
                    q = dict(q); q["eligible_codes"] = sorted(set(q["eligible_codes"]) | log_codes.get(k, set()))
                    out_questions[qid] = q
    else:  # mode 'log': start from existing table, fold pending log only
        for qid, q in existing_by_id.items():
            k = intrinsic_key(q["q_l1_skill"], q["q_n1"], q["q_n2"], q["response_includes_remainder"])
            q = dict(q); q["eligible_codes"] = sorted(set(q["eligible_codes"]) | log_codes.get(k, set()))
            out_questions[qid] = q

    # ----- mark folded log rows -----
    if len(master):
        master.loc[fold_mask, "folded_in_version"] = new_version
        master.to_csv(master_log_path(d), index=False)

    # ----- write table + pointer -----
    table = {
        "version": new_version,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode": mode, "mult_window": mult_window,
        "source_question_list": os.path.basename(args.questions) if args.questions else None,
        "questions": list(out_questions.values()),
    }
    fname = f"eligibility_table_{new_version}.json"
    json.dump(table, open(os.path.join(d, fname), "w"))
    open(pointer_path(d), "w").write(fname)

    folded = int(fold_mask.sum()) if len(master) else 0
    print(f"wrote {fname}: {len(out_questions)} questions | "
          f"merged {merged} new log rows, folded {folded} log rows | pointer -> {fname}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--questions")
    ap.add_argument("--mode", choices=["all", "new", "log"], default="all")
    ap.add_argument("--mult-window", choices=["fast", "regular"], default="fast")
    ap.add_argument("--table-dir", default=".")
    ap.add_argument("--status", action="store_true")
    run(ap.parse_args())
