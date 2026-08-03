"""History-based scorer (promoted into engine/ for the offline-batch ingest,
mixed-mode v11 section 9 / decision, and offline_tree_generator_spec_v2 section 7).

Relocated verbatim from the top-level ``offline_scorer.py`` script (no
scoring-logic change) so the API route can call it and it runs under the
automated test suite. It replays a stored attempt history through the engine's
OWN update and verdict functions (no reimplementation), so it is exact for
whatever was asked, regardless of whether each question came from the online
engine or an offline tree. A step is
``(question_id, skill_id, is_correct, slip, guess, tags)`` - exactly what a
``question_id`` joins to in ``question_parameters`` + the tenant lookup
(spec 12.1). Full replay is order-independent, which matters because lattice
propagation is order-sensitive.
"""
from engine.session import compute_verdicts, record_response, start_session
from engine.misconception import derive_misconception_signals


def full_params(cfg, lattice, grade):
    return cfg.get_engine_params(grade, lattice)


def score_history(steps, cfg, lattice, pool, grade, tenant, return_session=False):
    """Section 7: replay history -> (skill labels, misconception states). Exact.

    When ``return_session=True`` also returns the rebuilt scratch session, whose
    posteriors, misconception ledger, direct-observation counts, and reserve
    baseline are the replay-derived state the offline-batch ingest applies to the
    real session (mixed-mode v11 section 9, step 3).
    """
    params = full_params(cfg, lattice, grade)
    res = start_session(sub_session_id="score", learner_id="s", tenant_id=tenant,
                        class_id="c", grade=grade, engine_version="score", params=params)
    s = res.session
    s.misconception_applicable = pool.applicable_misconceptions(
        tenant, grade, params.skills_in_scope)
    for (qid, skill, correct, slip, guess, tags) in steps:
        s.pending_question_misconceptions = tags
        record_response(s, skill_id=skill, question_id=qid, is_correct=correct,
                        params=params, slip_override=slip, guess_override=guess,
                        defer_next=True)
    skills = {v.skill_id: v.confidence_label.value for v in compute_verdicts(s, params=params)}
    sigs = {x.misconception: x.state for x in derive_misconception_signals(
        s, misconception_target=cfg.misconception.target,
        clear_threshold=cfg.misconception.clear_threshold,
        present_threshold=cfg.misconception.present_threshold)}
    if return_session:
        return skills, sigs, s
    return skills, sigs
