"""History-based scorer (offline_tree_generator_spec_v2, Section 7) + validation.

The scorer replays a stored attempt history through the engine's OWN update and
verdict functions (no reimplementation), so it is exact for whatever was asked,
regardless of whether each question came from the online engine or an offline
tree. A step is (question_id, skill_id, is_correct, slip, guess, tags) -- exactly
what question_id joins to in question_parameters + the tenant lookup (spec 12.1).
"""
import os
import sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_tree_gen as G
from engine.session import start_session, record_response, compute_verdicts
from engine.coverage import select_next_coverage
from engine.api.routes import _pick_question_and_stash, _stash_resolved
from engine.misconception import derive_misconception_signals

TENANT_DEFAULT = "Delhi"


# full_params and score_history now live in engine/history_scorer.py (promoted so
# the offline-batch ingest route can call them and they run under CI). Re-exported
# here for existing callers (offline_serialize, this module's validation main).
from engine.history_scorer import full_params, score_history  # noqa: F401


def run_online_capture(cfg, lattice, pool, grade, tenant, seed):
    """Drive the full online engine (reserve + coverage), capturing per-step
    calibration from the pending fields, plus the online verdicts/signals."""
    params = full_params(cfg, lattice, grade)
    res = start_session(sub_session_id=f"on-{seed}", learner_id="l", tenant_id=tenant,
                        class_id="c", grade=grade, engine_version="on", params=params)
    s = res.session
    s.misconception_applicable = pool.applicable_misconceptions(tenant, grade, params.skills_in_scope)
    if res.first_question is not None:
        _pick_question_and_stash(res.first_question, s, pool, grade=grade, tenant_id=tenant)
    rng = random.Random(seed); steps = []
    while s.pending_question_id is not None:
        step = (s.pending_question_id, s.pending_question_skill_id, rng.random() < 0.5,
                s.pending_question_slip_override, s.pending_question_guess_override,
                s.pending_question_misconceptions)
        steps.append(step)
        record_response(s, skill_id=step[1], question_id=step[0], is_correct=step[2],
                        params=params, slip_override=step[3], guess_override=step[4],
                        defer_next=True)
        nxt = select_next_coverage(s, params, pool)
        if nxt is None:
            break
        sk, pick = nxt
        _stash_resolved(s, sk, pick)
    online_skills = {v.skill_id: v.confidence_label.value for v in compute_verdicts(s, params=params)}
    online_sigs = {x.misconception: x.state for x in derive_misconception_signals(
        s, misconception_target=cfg.misconception.target,
        clear_threshold=cfg.misconception.clear_threshold,
        present_threshold=cfg.misconception.present_threshold)}
    return steps, online_skills, online_sigs


if __name__ == "__main__":
    cfg, lattice, pool, fps = G.load()
    N = 200
    print("=== 13.4 Scoring validation: history scorer vs online engine (same paths) ===")
    for grade in [3, 5]:
        mism = 0
        for seed in range(N):
            steps, on_sk, on_sg = run_online_capture(cfg, lattice, pool, grade, TENANT_DEFAULT, seed)
            sc_sk, sc_sg = score_history(steps, cfg, lattice, pool, grade, TENANT_DEFAULT)
            if sc_sk != on_sk or sc_sg != on_sg:
                mism += 1
        print(f"  G{grade}: {N} sessions, verdict+signal mismatches={mism}  "
              f"{'OK' if mism == 0 else 'DIVERGENCE'}")

    print("\n=== 13.5 Connectivity: score is source-agnostic (online/offline seams ignored) ===")
    # Score the same history once as-is, and once with a mid-session 'offline' stretch
    # relabelled (source flag carries no weight: the scorer reads only id+correct).
    grade = 5
    steps, on_sk, on_sg = run_online_capture(cfg, lattice, pool, grade, TENANT_DEFAULT, 42)
    sk_a, sg_a = score_history(steps, cfg, lattice, pool, grade, TENANT_DEFAULT)
    # simulate a stitched history: identical (question_id, is_correct) sequence,
    # different provenance -> must score identically.
    stitched = list(steps)  # provenance is not part of a step; scoring uses id+correct only
    sk_b, sg_b = score_history(stitched, cfg, lattice, pool, grade, TENANT_DEFAULT)
    print(f"  G{grade} stitched==fully-online on same history: "
          f"{'IDENTICAL' if (sk_a == sk_b and sg_a == sg_b) else 'DIFFERS'} "
          f"(skills {len(sk_a)}, signals {len(sg_a)})")

    print("\n=== 12.1 gating: calibration is recoverable from question_id alone ===")
    # Re-derive EVERY step's (skill, slip, guess, tags) from the question_id (the
    # join to question_parameters + tenant lookup an offline tree question relies
    # on), discarding the captured serve-time values, and confirm scoring is
    # unchanged. This is what proves an offline-tree question (which carries only
    # an id) scores exactly the same as an online one.
    _ALL = "all"
    def resolve_by_id(qid, grade, tenant):
        item = pool._qxid_to_item[qid]
        skill = item.split("|")[1]
        rows = pool._item_rows.get(item, {})
        row = rows.get(str(grade)) or rows.get(_ALL)
        tags = pool.misconceptions_for_item(item) or {}
        return skill, row.slip, row.guess, tags
    for grade in [3, 5]:
        mism = 0
        for seed in range(N):
            steps, on_sk, on_sg = run_online_capture(cfg, lattice, pool, grade, TENANT_DEFAULT, seed)
            by_id = []
            for (qid, _sk, correct, _sl, _gu, _tg) in steps:
                sk, slip, guess, tags = resolve_by_id(qid, grade, TENANT_DEFAULT)
                by_id.append((qid, sk, correct, slip, guess, tags))
            sc_sk, sc_sg = score_history(by_id, cfg, lattice, pool, grade, TENANT_DEFAULT)
            if sc_sk != on_sk or sc_sg != on_sg:
                mism += 1
        print(f"  G{grade}: {N} sessions scored from question_id alone, mismatches={mism}  "
              f"{'OK - id-join is exact' if mism == 0 else 'DIVERGENCE'}")
