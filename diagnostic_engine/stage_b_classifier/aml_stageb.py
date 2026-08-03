#!/usr/bin/env python3
"""v9 Stage B orchestration: classify -> skill-level aggregate -> merge -> provenance.

Sits on top of the v1_2 classifier package. Reuses aml_classify's three-tier
eligibility lookup (labelled table -> side-cache -> inline), miss/drift handling,
and firing-union, but changes the aggregation key from operation to the L2.5
skill (spec 8.2) and produces the merged learning-state file (spec 9).

Acceptance coverage: AC4 (skill-level aggregation, rollup = sum of skills),
AC5 (low_support), AC7 (merge fidelity, status/reason), AC10 (provenance from
aml_engine.MODULE_VERSIONS). AC6 is enforced here: division items must carry
response_includes_remainder; a missing flag is an error, never operand-inferred.
"""
import os, json, datetime
from collections import defaultdict
import aml_engine as E
import aml_classify as C

OPS = ["addition", "subtraction", "multiplication", "division"]


def _resolve_sysrem_strict(op, item, errors, idx):
    """AC6: division requires an explicit flag; never operand-infer. Returns
    (sysrem, ok). On a missing flag for division, records an error and ok=False."""
    if op != "division":
        return None, True
    v = item.get("response_includes_remainder", item.get("system_expects_remainder"))
    if v is None:
        errors.append({"index": idx, "reason": "missing response_includes_remainder on division item",
                       "operation": op, "question_id": item.get("question_id")})
        return None, False
    # Coerce robustly. The in-process glue recovers this field positionally from
    # the item string, so it arrives as the text "True"/"False"; bool("False")
    # is True in Python, which would silently flip a no-remainder item to
    # remainder-expected and reintroduce the AC6 failure the seventh field exists
    # to prevent. Accept real bools and the case-insensitive strings; reject
    # anything else loudly rather than mis-coercing.
    if isinstance(v, bool):
        return v, True
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true", True
    errors.append({"index": idx, "reason": f"unrecognized response_includes_remainder value: {v!r}",
                   "operation": op, "question_id": item.get("question_id")})
    return None, False


def classify_by_skill(payload, lookup, table_version, miss_sink,
                      sidecache=None, new_sidecache=None, off_table=None, low_support_k=2):
    """Per-skill aggregation (spec 8.2/8.3). Filters to Fib items."""
    sidecache = sidecache if sidecache is not None else {}
    new_sidecache = new_sidecache if new_sidecache is not None else {}
    off_table = off_table if off_table is not None else set()
    grade = payload.get("learner_grade")

    fired = defaultdict(lambda: defaultdict(list))   # skill -> code -> [scores]
    elig = defaultdict(lambda: defaultdict(int))     # skill -> code -> n_eligible
    n_cls = defaultdict(int); n_cor = defaultdict(int); n_inv = defaultdict(int)
    skill_op = {}
    errors = []

    for idx, item in enumerate(payload.get("items", [])):
        if item.get("q_type") and item["q_type"] != "Fib":
            continue                                   # spec 8.4: classify Fib only
        op = E.norm_op(item.get("operation"))
        skill = item.get("skill_id")
        if op is None or not skill:
            errors.append({"index": idx, "reason": "missing operation or skill_id",
                           "question_id": item.get("question_id")}); continue
        try:
            n1 = int(item["n1"]); n2 = int(item["n2"]); resp = item["response"]
        except (KeyError, ValueError, TypeError) as e:
            errors.append({"index": idx, "reason": f"malformed_item ({e})",
                           "operation": op, "question_id": item.get("question_id")}); continue
        sysrem, ok = _resolve_sysrem_strict(op, item, errors, idx)
        if not ok:
            continue
        try:
            cr = E.classify_one(op, n1, n2, resp, learner_grade=grade, system_expects_remainder=sysrem)
        except Exception as e:
            errors.append({"index": idx, "reason": f"classify_failed ({e})",
                           "operation": op, "question_id": item.get("question_id")}); continue

        skill_op[skill] = op
        n_cls[skill] += 1
        fired_codes = {c: s for c, _n, s in cr.ranked if c != "CORRECT"}
        if cr.cascade_code == "CORRECT":
            n_cor[skill] += 1
        if cr.cascade_code in E.INVALID_CODES:
            n_inv[skill] += 1

        key = (op, n1, n2, sysrem)
        precomp = lookup.get(key)                              # 1) labelled table
        if precomp is None:
            off_table.add(key)
            precomp = new_sidecache.get(key) or sidecache.get(key)   # 2) side-cache
            if precomp is None:                               # 3) inline, cache it
                precomp = E.eligible_codes(op, n1, n2, system_expects_remainder=sysrem)
                new_sidecache[key] = precomp
        for code in set(fired_codes) - precomp:
            miss_sink((op, n1, n2, sysrem, resp, code))
        for code in (precomp | set(fired_codes)):             # firing-union
            elig[skill][code] += 1
        for code, score in fired_codes.items():
            fired[skill][code].append(score)

    per_skill = {}
    for skill, nq in n_cls.items():
        op = skill_op[skill]
        ranked = []
        for code, scores in fired[skill].items():
            if code in E.INVALID_CODES:
                continue
            nf = len(scores); ssum = sum(scores); ne = elig[skill].get(code, nf)
            ranked.append({"code": code, "name": E.code_name(op, code),
                           "misconception_evidence_index": round(ssum / ne, 4),
                           "n_fired": nf, "n_eligible": ne,
                           "mean_score_when_fired": round(ssum / nf, 4),
                           "low_support": ne < low_support_k})
        ranked.sort(key=lambda x: (-x["misconception_evidence_index"], -x["n_fired"], x["code"]))
        per_skill[skill] = {"operation": op, "status": "classified",
                            "n_questions_classified": nq,
                            "accuracy": round(n_cor[skill] / nq, 4),
                            "n_invalid": n_inv[skill], "ranked": ranked}
    return {"per_skill": per_skill, "skill_op": skill_op, "errors": errors,
            "eligibility_table_version": table_version,
            "_counts": {"n_cls": dict(n_cls), "n_cor": dict(n_cor), "n_inv": dict(n_inv)}}


def _operation_rollup(per_skill, counts):
    """AC4: per-operation rollup computed by summing the skill groups."""
    agg = defaultdict(lambda: {"n_classified": 0, "n_correct": 0, "n_invalid": 0})
    for skill, blk in per_skill.items():
        op = blk["operation"]; a = agg[op]
        a["n_classified"] += counts["n_cls"].get(skill, 0)
        a["n_correct"] += counts["n_cor"].get(skill, 0)
        a["n_invalid"] += counts["n_inv"].get(skill, 0)
    out = {}
    for op, a in agg.items():
        n = a["n_classified"] or 1
        out[op] = {"n_classified": a["n_classified"],
                   "accuracy": round(a["n_correct"] / n, 4),
                   "invalid_rate": round(a["n_invalid"] / n, 4)}
    return out


def _reason_for(mastery):
    """Reason a skill has no classifiable Fib responses (spec 9.1)."""
    if mastery and mastery.get("n_questions_asked", 0) == 0:
        return "skill_not_directly_tested"
    return "tested_only_via_mcq_or_number_sense"


def merge(skill_block, mastery, meta):
    """AC7 + AC10: join mastery (every in-scope skill) with misconceptions on the
    L2.5 name; provenance from aml_engine.MODULE_VERSIONS."""
    per_skill = skill_block["per_skill"]; counts = skill_block["_counts"]
    mastery_skills = mastery["skills"]            # {skill_id: {verdict, posterior, ...}}
    skills_out = []
    for skill_id, m in mastery_skills.items():
        mis = per_skill.get(skill_id)
        if mis is None:
            misc = {"status": "no_classifiable_responses",
                    "reason": _reason_for(m), "n_questions_classified": 0, "ranked": []}
            raw_op = m.get("operation")
            op = E.norm_op(raw_op) if raw_op else raw_op   # normalize to match classified skills
        else:
            misc = {"status": "classified",
                    "n_questions_classified": mis["n_questions_classified"],
                    "accuracy": mis["accuracy"], "n_invalid": mis["n_invalid"],
                    "ranked": mis["ranked"]}
            op = mis["operation"]
        skills_out.append({"skill_id": skill_id, "operation": op,
                           "mastery": m, "misconceptions": misc})

    return {
        "schema_version": "1.0",
        "learner_id": mastery.get("learner_id"),
        "learner_grade": mastery.get("learner_grade"),
        "tenant": meta.get("tenant"),
        "generated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "diagnostic_session": meta.get("diagnostic_session", {}),
        "provenance": {
            "engine_version": meta.get("engine_version"),
            "calibration_version": meta.get("calibration_version"),
            "eligibility_table_version": skill_block["eligibility_table_version"],
            "classifier_modules": dict(E.MODULE_VERSIONS),     # AC10: structured source
            "low_support_k": meta.get("low_support_k", 2),
        },
        "skills": skills_out,
        "operation_rollup": _operation_rollup(per_skill, counts),
        "errors": skill_block["errors"],
    }


def _persist(table_dir, version, miss_rows, new_sidecache, off_table, use_sidecache=True):
    """Write the runtime side files server-side, identical in format to aml_classify:
    miss_log.csv (probe-gap repair), eligibility_sidecache.jsonl (off-table perf cache),
    unknown_questions.csv (drift log). Without this, the Stage B path silently drops
    all three (spec Section 10 / AC8)."""
    import csv, datetime
    if miss_rows:
        p = C._rawlog(table_dir); new = not os.path.exists(p)
        with open(p, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(C.RAW_COLS)
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
            for op, n1, n2, sysrem, resp, code in miss_rows:
                w.writerow([ts, op, n1, n2, (sysrem if op == "division" else ""), resp, code])
    if new_sidecache and use_sidecache:
        with open(C._sidecache(table_dir), "a") as f:
            for key, codes in new_sidecache.items():
                f.write(json.dumps({"k": C._key_str(key), "codes": sorted(codes)}) + "\n")
    if off_table:
        up = C._unknownlog(table_dir); new = not os.path.exists(up)
        with open(up, "a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["ts", "table_version", "operation", "n1", "n2", "response_includes_remainder"])
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
            for op, n1, n2, rir in off_table:
                w.writerow([ts, version, op, n1, n2, (rir if op == "division" else "")])


def build_learning_state(responses_payload, mastery_payload, meta, table_dir,
                         table_version=None, table_file=None, low_support_k=2,
                         log=True, use_sidecache=True):
    """End-to-end: resolve table, classify by skill, merge. Returns the spec-9 file.
    Reuses aml_classify's table resolution and side-cache, and (spec Section 10 / AC8)
    persists the miss log, side-cache and drift log server-side."""
    table, lookup, version = C.resolve_table(table_dir, table_version, table_file)
    sidecache = C.load_sidecache(table_dir) if use_sidecache else {}
    new_sidecache, off_table, miss_rows = {}, set(), []
    miss_sink = (lambda r: miss_rows.append(r)) if log else (lambda r: None)
    sk = classify_by_skill(responses_payload, lookup, version, miss_sink,
                           sidecache=sidecache, new_sidecache=new_sidecache,
                           off_table=off_table, low_support_k=low_support_k)
    if log:
        _persist(table_dir, version, miss_rows, new_sidecache, off_table, use_sidecache=use_sidecache)
    meta = {**meta, "low_support_k": low_support_k}
    return merge(sk, mastery_payload, meta)


# --- reference adapters for the engine-side glue (spec 8.4) -----------------
def _enum_val(x):
    return x.value if hasattr(x, "value") else str(x)


def _resolved_by(v):
    if getattr(v, "direct_observations", 0) > 0:
        return "direct_evidence"
    if getattr(v, "propagation_updates", 0) > 0:
        return "lattice_propagation"
    return "prior"


def mastery_from_verdicts(verdicts, learner_id, learner_grade):
    """Map the engine's compute_verdicts() output to the mastery payload merge()
    consumes. Reference adapter; production may read these straight from the
    engine's verdict records."""
    skills = {}
    for v in verdicts:
        skills[v.skill_id] = {
            "verdict": _enum_val(v.confidence_label),
            "posterior": round(float(v.posterior), 4),
            "recommendation": _enum_val(v.recommendation),
            "resolved_by": _resolved_by(v),
            "n_questions_asked": int(getattr(v, "direct_observations", 0)),
            "operation": getattr(v, "operation", ""),
        }
    return {"learner_id": learner_id, "learner_grade": learner_grade, "skills": skills}


def build_responses_payload(learner_id, learner_grade, question_ids, resolve, response_of):
    """Reference for the 8.4 response-fetch API. `resolve(qid)` returns the
    question content {skill_id, operation, n1, n2, response_includes_remainder,
    q_type}; `response_of(qid)` returns the persisted raw response. The
    question_id -> operand resolution is the AML-side integration seam."""
    items = []
    for qid in question_ids:
        items.append({"question_id": qid, "response": response_of(qid), **resolve(qid)})
    return {"learner_id": learner_id, "learner_grade": learner_grade, "items": items}
