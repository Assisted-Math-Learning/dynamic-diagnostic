"""Phase E (mixed-mode v11 section 16): equivalence + invariants.

The headline obligation: a mixed session (online prefix + an offline segment
folded in via the ingest) yields the SAME mastery verdicts as the pure-online
scoring of the same answers - across random split points, including a
late/out-of-order batch and the anchor-not-found stacked-delay fallback - and
never exceeds the grade budget or repeats an item. Gated on real data.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests import DATA_DIR

PROJECT = DATA_DIR
LOOKUP = Path(__file__).resolve().parents[1] / "inputs" / "tenant_question_lookup_v2.csv"

pytestmark = pytest.mark.skipif(
    not (PROJECT.exists() and (PROJECT / "question_parameters.csv").exists() and LOOKUP.exists()),
    reason="real project data / tenant lookup not present",
)

from engine.session import (                              # noqa: E402
    RoutingMode, compute_verdicts, record_response, start_session,
)
from engine.offline_ingest import OfflineAnswer, apply_offline_batch   # noqa: E402
from engine.history_scorer import score_history           # noqa: E402
from offline_follow import follow_capped                  # noqa: E402

TENANT = "Delhi"


def _setup(grade=3):
    import scripts.smoke as smoke
    from engine.cli import _build_engine_config_dict
    from engine.config import EngineConfig
    from engine.lattice import LatticeIndex
    from engine.question_pool import CsvQuestionPool
    skills, priors, anchors, edges, qpath = smoke.step_1_load_data(PROJECT)
    cfgd = _build_engine_config_dict(skills=skills, anchors=anchors, priors=priors)
    config = EngineConfig.model_validate(cfgd)
    lattice = LatticeIndex(edges)
    pool = CsvQuestionPool(str(qpath), expected_skills={s.name for s in config.skills},
                           seed=7, lookup_path=str(LOOKUP), misconception_target=2)
    return config, lattice, pool


def _capture_online(config, lattice, pool, grade, seed):
    """A realistic online answer sequence + its verdicts (the pure-online
    reference), via the shipped offline_scorer harness."""
    from offline_scorer import run_online_capture
    steps, on_skills, _ = run_online_capture(config, lattice, pool, grade, TENANT, seed)
    return steps, on_skills


def _params(config, lattice, grade):
    return config.get_engine_params(grade, lattice)


def _fresh_session(config, lattice, pool, grade, params, sid="mix"):
    res = start_session(sub_session_id=sid, learner_id="l", tenant_id=TENANT,
                        class_id="c", grade=grade, engine_version="t", params=params)
    s = res.session
    s.misconception_applicable = pool.applicable_misconceptions(
        TENANT, grade, params.skills_in_scope)
    return s


def _apply_online(session, steps, params):
    """Replay a captured (qid, skill, correct, slip, guess, tags) prefix online."""
    for (qid, skill, correct, slip, guess, tags) in steps:
        session.pending_question_misconceptions = tags
        record_response(session, skill_id=skill, question_id=qid, is_correct=correct,
                        params=params, slip_override=slip, guess_override=guess,
                        routing_mode=RoutingMode.ONLINE, defer_next=True)


def _batch(steps, start_dt=None):
    """Turn captured steps into offline batch answers (server re-derives calib)."""
    t0 = start_dt or datetime(2026, 7, 22, 10, 0, 0, tzinfo=timezone.utc)
    return [OfflineAnswer(question_x_id=qid, skill_id=skill, is_correct=correct,
                          raw_response="x", asked_at=t0 + timedelta(minutes=i))
            for i, (qid, skill, correct, slip, guess, tags) in enumerate(steps)]


@pytest.mark.parametrize("seed,frac", [(1, 0.4), (2, 0.6), (3, 0.5), (7, 0.3)])
def test_mixed_split_equals_pure_online(seed, frac):
    # Catalogue (v11 section 23): TC-MIX-19
    config, lattice, pool = _setup(3)
    params = _params(config, lattice, 3)
    steps, on_skills = _capture_online(config, lattice, pool, 3, seed)
    if len(steps) < 4:
        pytest.skip("session too short to split")
    k = max(1, int(len(steps) * frac))
    prefix, batch = steps[:k], steps[k:]

    s = _fresh_session(config, lattice, pool, 3, params, sid=f"mx-{seed}")
    _apply_online(s, prefix, params)
    anchor = prefix[-1][0]
    res = apply_offline_batch(s, resume_anchor=anchor, entries=_batch(batch),
                              tree_id="Delhi/g3", tree_version=1, cfg=config,
                              lattice=lattice, pool=pool, grade=3, tenant=TENANT)
    mixed = {v.skill_id: v.confidence_label.value
             for v in compute_verdicts(res.session, params=params)}
    # Same answers, split online/offline, must score identically to pure-online.
    assert mixed == on_skills
    # And the offline chunk is marked offline_replay.
    off = sum(1 for e in res.session.question_history
              if e.routing_mode == RoutingMode.OFFLINE_REPLAY)
    assert off == len(batch)


def test_out_of_order_batch_placed_correctly():
    # Catalogue (v11 section 23): section 16 late/out-of-order batch equivalence
    config, lattice, pool = _setup(3)
    params = _params(config, lattice, 3)
    steps, on_skills = _capture_online(config, lattice, pool, 3, 5)
    if len(steps) < 6:
        pytest.skip("session too short")
    a, b = len(steps) // 3, 2 * len(steps) // 3
    prefix, batch, later = steps[:a], steps[a:b], steps[b:]

    s = _fresh_session(config, lattice, pool, 3, params, sid="ooo")
    # The delayed batch has NOT synced yet: apply prefix, then the later online
    # segment, leaving a gap where the batch belongs.
    _apply_online(s, prefix, params)
    _apply_online(s, later, params)
    anchor = prefix[-1][0]      # the batch belongs immediately after the prefix
    res = apply_offline_batch(s, resume_anchor=anchor, entries=_batch(batch),
                              tree_id="Delhi/g3", tree_version=1, cfg=config,
                              lattice=lattice, pool=pool, grade=3, tenant=TENANT)
    # The resume anchor reconstructs the true order prefix+batch+later, so the
    # verdicts match pure-online on the same answers.
    mixed = {v.skill_id: v.confidence_label.value
             for v in compute_verdicts(res.session, params=params)}
    assert mixed == on_skills
    assert res.anchor_not_found is False
    # The batch really was inserted before the later online answers.
    hist_qids = [e.question_id for e in res.session.question_history]
    assert hist_qids.index(batch[0][0]) < hist_qids.index(later[0][0])


def test_anchor_not_found_tail_appends_and_flags():
    # Catalogue (v11 section 23): section 16 anchor-not-found fallback
    config, lattice, pool = _setup(3)
    params = _params(config, lattice, 3)
    steps, on_skills = _capture_online(config, lattice, pool, 3, 9)
    if len(steps) < 4:
        pytest.skip("session too short")
    k = len(steps) // 2
    prefix, batch = steps[:k], steps[k:]
    s = _fresh_session(config, lattice, pool, 3, params, sid="anf")
    _apply_online(s, prefix, params)
    # A resume anchor that is NOT in the history (e.g. de-duped away in a
    # stacked-delay chain, or otherwise unknown): the ingest must tail-append
    # and flag, and - since the batch's true position IS the tail here - still
    # score identically to pure-online on the same answers.
    res = apply_offline_batch(s, resume_anchor="q_anchor_not_in_history",
                              entries=_batch(batch), tree_id="Delhi/g3",
                              tree_version=1, cfg=config, lattice=lattice,
                              pool=pool, grade=3, tenant=TENANT)
    assert res.anchor_not_found is True
    mixed = {v.skill_id: v.confidence_label.value
             for v in compute_verdicts(res.session, params=params)}
    assert mixed == on_skills


def test_budget_and_no_repeat_across_walk_splits():
    # Catalogue (v11 section 23): TC-MIX-03 (unified budget + cross-source no-repeat)
    """Drive genuinely mixed sessions with the OFFLINE WALK generating the
    offline segment from an online prefix, then ingest, and assert the two
    hard invariants: never exceed the grade budget; never repeat an item."""
    import random
    import offline_tree_gen as G
    import offline_tree_perop as P
    from offline_followsim import base_first_follow, items_for
    grade = 3
    config, lattice, pool = _setup(grade)
    params = _params(config, lattice, grade)
    budget = params.routing_config.total_budget
    OPS = ["Addition", "Subtraction", "Multiplication", "Division"]
    trees = {op: P.PerOpBuilder(config, lattice, pool, grade, op, tenant=TENANT,
                                allowance={2: 3, 3: 4, 4: 4, 5: 3}[grade]).build()
             for op in OPS}
    items = items_for(trees, pool)

    for seed in range(4):
        steps, _ = _capture_online(config, lattice, pool, grade, seed)
        if len(steps) < 4:
            continue
        k = len(steps) // 2
        prefix = steps[:k]
        s = _fresh_session(config, lattice, pool, grade, params, sid=f"bnr-{seed}")
        _apply_online(s, prefix, params)
        # Offline walk resumes from the unified history (item space), spending
        # only the remaining unified budget.
        answered = {pool._qxid_to_item[e.question_id]: e.is_correct
                    for e in s.question_history}
        remaining = budget - s.questions_total
        mastery = {sk: (random.Random(seed).random() < 0.5) for sk in params.skills_in_scope}
        off_hist, qc = base_first_follow(trees, remaining, random.Random(seed * 3 + 1),
                                         mastery, pool, grade, answered=answered, items=items)
        assert qc <= remaining                              # walk respects remaining budget
        batch = [OfflineAnswer(question_x_id=h[0], skill_id=h[1], is_correct=h[2],
                               raw_response="x",
                               asked_at=datetime(2026, 7, 22, 10, 0, tzinfo=timezone.utc)
                               + timedelta(minutes=i))
                 for i, h in enumerate(off_hist)]
        anchor = prefix[-1][0]
        res = apply_offline_batch(s, resume_anchor=anchor, entries=batch,
                                  tree_id="Delhi/g3", tree_version=1, cfg=config,
                                  lattice=lattice, pool=pool, grade=grade, tenant=TENANT)
        sess = res.session
        # Invariant 1: never exceed the grade budget.
        assert sess.questions_total <= budget
        # Invariant 2: never repeat an item (no-repeat is item-space).
        its = [pool._qxid_to_item.get(e.question_id) for e in sess.question_history]
        its = [i for i in its if i is not None]
        assert len(its) == len(set(its))


def test_walk_resume_routes_past_answered():
    # Catalogue (v11 section 23): TC-MIX-01 (also TC-MIX-13, TC-MIX-18)
    """Unit: the resumed walk asks only unanswered items (entry point), routing
    past every item already in the unified history."""
    config, lattice, pool = _setup(3)
    import offline_tree_perop as P
    op = "Addition"
    b = P.PerOpBuilder(config, lattice, pool, 3, op, tenant=TENANT, allowance=4).build()
    trees = {op: b}
    items = {op: [pool._qxid_to_item[x] for x in b.questions]}
    # Fresh walk asks the root's item first.
    asked = []
    follow_capped(trees, 3, lambda qid, o: (True, asked.append(qid)),
                  op_order=[op])
    first_item = pool._qxid_to_item[asked[0]]
    # Now mark the root's item answered; the resumed walk must NOT ask it again.
    asked2 = []
    follow_capped(trees, 3, lambda qid, o: (True, asked2.append(qid)),
                  op_order=[op], answered={first_item: True}, items=items)
    asked2_items = {pool._qxid_to_item[q] for q in asked2}
    assert first_item not in asked2_items


def test_multiple_offline_segments_equal_pure_online():
    """TC-MIX-06 / TC-MIX-07: two offline segments with intervening online
    (online -> batch1 -> online -> batch2) score identically to pure-online on
    the same answers. This is the field case; the mechanism was verified by QC,
    this puts it in CI."""
    config, lattice, pool = _setup(3)
    params = _params(config, lattice, 3)
    steps, on_skills = _capture_online(config, lattice, pool, 3, 3)
    if len(steps) < 8:
        pytest.skip("session too short for two segments")
    q = len(steps) // 4
    p0, b1, p1, b2 = steps[:q], steps[q:2 * q], steps[2 * q:3 * q], steps[3 * q:]

    s = _fresh_session(config, lattice, pool, 3, params, sid="ms")
    _apply_online(s, p0, params)
    res1 = apply_offline_batch(s, resume_anchor=p0[-1][0], entries=_batch(b1),
                               tree_id="Delhi/g3", tree_version=1, cfg=config,
                               lattice=lattice, pool=pool, grade=3, tenant=TENANT)
    s = res1.session
    _apply_online(s, p1, params)                     # intervening online segment
    res2 = apply_offline_batch(s, resume_anchor=p1[-1][0],
                               entries=_batch(b2, start_dt=datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)),
                               tree_id="Delhi/g3", tree_version=1, cfg=config,
                               lattice=lattice, pool=pool, grade=3, tenant=TENANT)
    s = res2.session
    mixed = {v.skill_id: v.confidence_label.value for v in compute_verdicts(s, params=params)}
    assert mixed == on_skills
    off = sum(1 for e in s.question_history if e.routing_mode == RoutingMode.OFFLINE_REPLAY)
    assert off == len(b1) + len(b2)                  # both batches present
    assert s.questions_total == len(steps)


@pytest.mark.parametrize("seed,frac", [(1, 0.5), (4, 0.4)])
def test_mixed_split_equals_pure_online_grade5(seed, frac):
    """TC-MIX-16: equivalence also holds at grade 5, whose operation order is
    Division-first and whose budget differs - the best low-cost strengthener
    beyond the grade-3 runs."""
    config, lattice, pool = _setup(5)
    params = _params(config, lattice, 5)
    steps, on_skills = _capture_online(config, lattice, pool, 5, seed)
    if len(steps) < 4:
        pytest.skip("session too short to split")
    k = max(1, int(len(steps) * frac))
    prefix, batch = steps[:k], steps[k:]
    s = _fresh_session(config, lattice, pool, 5, params, sid=f"g5-{seed}")
    _apply_online(s, prefix, params)
    res = apply_offline_batch(s, resume_anchor=prefix[-1][0], entries=_batch(batch),
                              tree_id="Delhi/g5", tree_version=1, cfg=config,
                              lattice=lattice, pool=pool, grade=5, tenant=TENANT)
    mixed = {v.skill_id: v.confidence_label.value
             for v in compute_verdicts(res.session, params=params)}
    assert mixed == on_skills


def test_walk_asks_nothing_when_budget_exhausted():
    # Catalogue (v11 section 23): TC-MIX-17
    """If the online portion already spent the full grade budget, the offline
    walk resumed with a remaining budget of zero asks nothing and terminates
    cleanly (the hard cap stops it before any question)."""
    import offline_tree_perop as P
    config, lattice, pool = _setup(3)
    ops = ["Addition", "Subtraction", "Multiplication", "Division"]
    trees = {op: P.PerOpBuilder(config, lattice, pool, 3, op, tenant=TENANT,
                                allowance=4).build() for op in ops}
    items = {op: [pool._qxid_to_item[x] for x in trees[op].questions] for op in ops}
    # A non-empty unified history stands in for a fully-spent budget; remaining
    # budget is zero.
    answered = {pool._qxid_to_item[trees["Addition"].questions[0]]: True}
    asked = []
    out, count = follow_capped(trees, 0, lambda qid, o: (True, asked.append(qid)),
                               answered=answered, items=items)
    assert count == 0
    assert asked == []
    assert out == []


def test_mixed_sweep_ci_grades_3_and_5():
    # Catalogue: automated large-sample mixed sweep (v11 section 16)
    """CI-sized mixed sweep: 50 sessions at grade 3 and 40 at grade 5, asserting
    zero verdict mismatches versus pure-online and zero over-budget. The full
    several-hundred-session run stays opt-in via `offline_followsim.py mixed`."""
    from offline_followsim import run_mixed_sweep
    for grade, n in ((3, 50), (5, 40)):
        config, lattice, pool = _setup(grade)
        r = run_mixed_sweep(config, lattice, pool, grade, n)
        assert r["sessions"] > 0
        assert r["mismatches"] == 0, f"grade {grade}: {r}"
        assert r["over_budget"] == 0, f"grade {grade}: {r}"
