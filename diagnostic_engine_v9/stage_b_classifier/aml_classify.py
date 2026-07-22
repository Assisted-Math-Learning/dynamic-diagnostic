#!/usr/bin/env python3
"""
AML misconception classifier - learner runtime (Script 2).

Reads a learner's responses as JSON, classifies each with the deterministic
misconception classifier, and aggregates to a per-operation ranked list of
misconception_evidence_index values.

  index(code) = sum of the code's within-question scores over the learner's
                questions where it fired
                ----------------------------------------------------------
                number of the learner's questions (same operation) where the
                code was ELIGIBLE = precomputed table for the question's operands
                UNION any code that fired on the actual response (firing-union,
                so numerator <= denominator always).

Table is resolved once per run via the pointer file (or an explicit override),
and the version used is stamped on the output. Any fired code NOT in the
precomputed table is appended to an append-only miss log for the tagger to fold
in later (runtime never edits the table or rewrites the log; it only appends).

Usage:
  python aml_classify.py input.json -o output.json
  python aml_classify.py input.json --table-dir ./tables
  python aml_classify.py input.json --table-version 20260626_v2   # reproduce a past run
  cat input.json | python aml_classify.py
"""
import sys, os, json, argparse, csv, datetime
from collections import defaultdict
import aml_engine as E

def _pointer(d): return os.path.join(d, "eligibility_table_current.txt")
def _rawlog(d): return os.path.join(d, "miss_log.csv")
def _sidecache(d): return os.path.join(d, "eligibility_sidecache.jsonl")
def _unknownlog(d): return os.path.join(d, "unknown_questions.csv")
RAW_COLS = ["ts", "operation", "n1", "n2", "response_includes_remainder", "response", "code"]

def _key_str(key):
    return f"{key[0]}|{key[1]}|{key[2]}|{key[3]}"

def _key_parse(s):
    op, n1, n2, rir = s.split("|")
    rir = True if rir == "True" else False if rir == "False" else None
    return (op, int(n1), int(n2), rir)

def load_sidecache(table_dir):
    """Append-only JSONL, last-write-wins per key (deterministic, so safe)."""
    p = _sidecache(table_dir)
    cache = {}
    if os.path.exists(p):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    cache[_key_parse(rec["k"])] = set(rec["codes"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return cache

def resolve_table(table_dir, version=None, table_file=None):
    """Resolve the table once. Returns (table_dict, lookup, version_str)."""
    if table_file:
        fp = table_file
    elif version:
        fp = os.path.join(table_dir, f"eligibility_table_{version}.json")
    else:
        ptr = _pointer(table_dir)
        if not os.path.exists(ptr):
            return None, {}, None
        fp = os.path.join(table_dir, open(ptr).read().strip())
    if not os.path.exists(fp):
        return None, {}, None
    table = json.load(open(fp))
    lookup = defaultdict(set)
    for q in table["questions"]:
        o = E.norm_op(q["q_l1_skill"])
        rir = bool(q["response_includes_remainder"]) if o == "division" else None
        lookup[(o, int(q["q_n1"]), int(q["q_n2"]), rir)] |= set(q["eligible_codes"])
    return table, lookup, table.get("version")

def _resolve_sysrem(op, n1, n2, item):
    if op != "division":
        return None
    v = item.get("system_expects_remainder")
    if v is not None:
        # bool("False") is True; coerce text flags explicitly before falling back.
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.strip().lower() in ("true", "false"):
            return v.strip().lower() == "true"
        return bool(v)
    return (n2 != 0 and n1 % n2 != 0)

def classify_learner(payload, lookup, table_version, miss_sink,
                     sidecache=None, new_sidecache=None, off_table=None):
    sidecache = sidecache if sidecache is not None else {}
    new_sidecache = new_sidecache if new_sidecache is not None else {}
    off_table = off_table if off_table is not None else set()
    learner_id = payload.get("learner_id")
    learner_grade = payload.get("learner_grade")
    items = payload.get("items", [])
    fired_scores = defaultdict(lambda: defaultdict(list))
    elig_counts = defaultdict(lambda: defaultdict(int))
    n_questions = defaultdict(int); n_correct = defaultdict(int); n_invalid = defaultdict(int)
    errors = []

    for idx, item in enumerate(items):
        op = E.norm_op(item.get("operation"))
        if op is None:
            errors.append({"index": idx, "reason": f"unknown operation {item.get('operation')!r}", "item": item}); continue
        try:
            n1 = int(item["n1"]); n2 = int(item["n2"]); resp = item["response"]
        except (KeyError, ValueError, TypeError) as e:
            errors.append({"index": idx, "reason": f"bad item ({e})", "item": item}); continue
        sysrem = _resolve_sysrem(op, n1, n2, item)
        try:
            cr = E.classify_one(op, n1, n2, resp, learner_grade=learner_grade,
                                system_expects_remainder=sysrem)
        except Exception as e:
            errors.append({"index": idx, "reason": f"classify failed ({e})", "item": item}); continue

        n_questions[op] += 1
        fired = {c: s for c, _n, s in cr.ranked if c != "CORRECT"}
        if cr.cascade_code == "CORRECT":
            n_correct[op] += 1
        if cr.cascade_code in E.INVALID_CODES:
            n_invalid[op] += 1

        key = (op, n1, n2, sysrem)
        precomp = lookup.get(key)                  # 1) labelled table
        if precomp is None:
            off_table.add(key)                     # flag drift regardless of cache hit
            precomp = new_sidecache.get(key) or sidecache.get(key)  # 2) side-cache
            if precomp is None:                    # 3) compute inline once, cache it
                precomp = E.eligible_codes(op, n1, n2, system_expects_remainder=sysrem)
                new_sidecache[key] = precomp
        # log any fired code not in the eligible set (the miss log)
        for code in set(fired) - precomp:
            miss_sink((op, n1, n2, sysrem, resp, code))
        elig = precomp | set(fired)               # firing-union
        for code in elig:
            elig_counts[op][code] += 1
        for code, score in fired.items():
            fired_scores[op][code].append(score)

    results = {}
    for op in ["addition", "subtraction", "multiplication", "division"]:
        if n_questions[op] == 0:
            continue
        ranked = []
        for code, scores in fired_scores[op].items():
            if code in E.INVALID_CODES:
                continue
            nf = len(scores); ssum = sum(scores); ne = elig_counts[op].get(code, nf)
            ranked.append({"code": code, "name": E.code_name(op, code),
                           "n_fired": nf, "n_eligible": ne,
                           "mean_score_when_fired": round(ssum / nf, 4),
                           "misconception_evidence_index": round(ssum / ne, 4)})
        ranked.sort(key=lambda x: (-x["misconception_evidence_index"], -x["n_fired"], x["code"]))
        nq = n_questions[op]
        results[op] = {
            "accuracy": {"n_questions": nq, "n_correct": n_correct[op],
                         "accuracy": round(n_correct[op] / nq, 4)},
            "invalid_responses": {"n_invalid": n_invalid[op], "rate": round(n_invalid[op] / nq, 4)},
            "ranked": ranked,
        }
    return {"learner_id": learner_id, "learner_grade": learner_grade,
            "eligibility_table_version": table_version,
            "results_by_operation": results, "errors": errors}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?")
    ap.add_argument("-o", "--output")
    ap.add_argument("--table-dir", default=".")
    ap.add_argument("--table-version", help="override pointer to reproduce a past run")
    ap.add_argument("--table-file", help="explicit table json path")
    ap.add_argument("--no-log", action="store_true", help="do not append misses to the miss log")
    ap.add_argument("--no-sidecache", action="store_true",
                    help="do not read or write the off-table eligibility side-cache")
    args = ap.parse_args()

    table, lookup, version = resolve_table(args.table_dir, args.table_version, args.table_file)
    if table is None:
        sys.stderr.write("warning: no eligibility table found; using on-the-fly fallback for every question\n")

    # append-only miss log
    miss_rows = []
    def miss_sink(row):
        miss_rows.append(row)
    if args.no_log:
        miss_sink = lambda row: None

    # off-table eligibility side-cache (performance layer, not the labelled table)
    sidecache = {} if args.no_sidecache else load_sidecache(args.table_dir)
    new_sidecache = {}
    off_table = set()

    raw = open(args.input).read() if args.input else sys.stdin.read()
    payload = json.loads(raw)
    out = classify_learner(payload, lookup, version, miss_sink,
                           sidecache=sidecache, new_sidecache=new_sidecache, off_table=off_table)

    if miss_rows and not args.no_log:
        p = _rawlog(args.table_dir)
        new = not os.path.exists(p)
        with open(p, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(RAW_COLS)
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
            for op, n1, n2, sysrem, resp, code in miss_rows:
                rir = sysrem if op == "division" else ""
                w.writerow([ts, op, n1, n2, rir, resp, code])

    # persist newly computed side-cache entries (append-only JSONL)
    if new_sidecache and not args.no_sidecache:
        with open(_sidecache(args.table_dir), "a") as f:
            for key, codes in new_sidecache.items():
                f.write(json.dumps({"k": _key_str(key), "codes": sorted(codes)}) + "\n")

    # flag off-table questions (set drift between tagged and administered sets)
    if off_table:
        sys.stderr.write(f"warning: {len(off_table)} off-table question key(s) encountered "
                         f"(not in eligibility table '{version}'); served via side-cache/inline. "
                         f"Re-tag from the question list to onboard them.\n")
        up = _unknownlog(args.table_dir)
        new = not os.path.exists(up)
        with open(up, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["ts", "table_version", "operation", "n1", "n2", "response_includes_remainder"])
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
            for op, n1, n2, rir in off_table:
                w.writerow([ts, version, op, n1, n2, rir if op == "division" else ""])

    text = json.dumps(out, indent=2, default=str)
    if args.output:
        open(args.output, "w").write(text)
    else:
        print(text)

if __name__ == "__main__":
    main()
