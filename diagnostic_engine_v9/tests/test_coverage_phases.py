"""Checkpoint 3b-i: budget/reserve plumbing and the additive Phase-3 leftover
skill selector. (The full phase controller and its end-to-end behaviour come in
3b-ii / 3b-iii.)"""

from engine.routing import RoutingState, select_leftover_skill, pick_next_question
from engine.session import EngineParams

from tests.test_session import make_params, make_routing_config, SKILLS, SKILL_TO_OP


def _state(posteriors, *, qtotal=0, per_op=None):
    return RoutingState(
        skills_in_scope=SKILLS,
        skill_to_operation=SKILL_TO_OP,
        operation_anchors={},
        posteriors=posteriors,
        direct_obs_count={s: 1 for s in SKILLS},  # suppress verification path
        questions_total=qtotal,
        questions_per_operation=per_op or {},
    )


# --- budget plumbing -------------------------------------------------------


def test_adaptive_budget_equals_total_when_no_reserve():
    p = make_params()
    assert p.reserve_size == 0
    assert p.adaptive_budget == p.routing_config.total_budget


def test_adaptive_budget_subtracts_reserve():
    import dataclasses
    p = make_params()
    p2 = dataclasses.replace(p, reserve_size=7)
    assert p2.adaptive_budget == p.routing_config.total_budget - 7


# --- select_leftover_skill (Phase 3 helper) --------------------------------


def test_leftover_picks_an_unsure_skill():
    cfg = make_routing_config()
    p = make_params()
    # One skill mid-uncertainty (0.5), the rest resolved.
    post = {s: 0.97 for s in SKILLS}
    post[SKILLS[1]] = 0.5
    choice = select_leftover_skill(_state(post), cfg, p.lattice_index, SKILLS)
    assert choice is not None and choice.skill == SKILLS[1]


def test_leftover_none_when_all_resolved():
    cfg = make_routing_config()
    p = make_params()
    post = {s: 0.97 for s in SKILLS}
    assert select_leftover_skill(_state(post), cfg, p.lattice_index, SKILLS) is None


def test_leftover_ignores_per_operation_caps():
    # An operation at/over its per-op cap still yields its unsure skill via the
    # leftover selector (caps lifted), unlike pick_next_question.
    cfg = make_routing_config(per_operation_budget=1, total_budget=99)
    p = make_params()
    post = {s: 0.97 for s in SKILLS}
    unsure = SKILLS[0]
    post[unsure] = 0.5
    op = SKILL_TO_OP[unsure]
    # That operation has already spent its per-op budget.
    state = _state(post, qtotal=1, per_op={op: 1})
    # pick_next_question would skip the capped operation...
    nq = pick_next_question(state, cfg, p.lattice_index)
    assert nq is None or nq.skill != unsure
    # ...but the leftover selector still returns it.
    choice = select_leftover_skill(state, cfg, p.lattice_index, SKILLS)
    assert choice is not None and choice.skill == unsure


def test_leftover_restricts_to_candidate_set():
    cfg = make_routing_config()
    p = make_params()
    post = {s: 0.5 for s in SKILLS}  # all unsure
    # Only offer two as candidates -> never returns the others.
    candidates = SKILLS[:2]
    choice = select_leftover_skill(_state(post), cfg, p.lattice_index, candidates)
    assert choice is not None and choice.skill in candidates


# --- the phase controller (select_next_coverage) ---------------------------

import dataclasses  # noqa: E402

from engine.coverage import select_next_coverage  # noqa: E402
from engine.question_pool import CsvQuestionPool  # noqa: E402
from engine.session import start_session  # noqa: E402
from tests.test_question_pool import (  # noqa: E402
    row, write_csv, write_lookup, history_entry,
)

CTRL_SKILLS = ["SkillA", "SkillB"]
CTRL_OPS = {"SkillA": "Addition", "SkillB": "Subtraction"}


def _ctrl_setup(tmp_path, *, reserve, target=2, extra=1, total=20):
    params = write_csv(tmp_path / "p.csv", [
        row("A|q1", "qp1", "SkillA", "all", 0.80),
        row("A|q2", "qp2", "SkillA", "all", 0.80),
        row("B|q1", "qp3", "SkillB", "all", 0.80),
    ])
    lookup = write_lookup(tmp_path / "lk.csv", [
        {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
        {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2", "x_plus_x": 1},
        {"tenant": "Delhi", "item": "B|q1", "question_x_id": "d3", "zero_minus_x": 1},
    ])
    pool = CsvQuestionPool(params, lookup_path=lookup, selection="deterministic",
                           seed=1, misconception_target=target)
    p = make_params(
        skills=CTRL_SKILLS, skill_to_op=CTRL_OPS, anchors={},
        priors={"SkillA": 0.5, "SkillB": 0.5},
        routing_config=make_routing_config(
            operation_order=("Addition", "Subtraction"),
            per_operation_budget=total, total_budget=total),
        grade=5,
    )
    p = dataclasses.replace(p, reserve_size=reserve, misconception_conditional_extra=extra)
    sess = start_session(sub_session_id="s", learner_id="l", tenant_id="Delhi",
                         class_id="c", grade=5, engine_version="t", params=p).session
    sess.misconception_applicable = {"x_plus_0", "x_plus_x", "zero_minus_x"}
    return pool, p, sess


def test_phase1_returns_routing_pick_while_unresolved(tmp_path):
    pool, p, sess = _ctrl_setup(tmp_path, reserve=5)
    # Fresh session: marker unset, skills unresolved -> Phase 1 pick.
    res = select_next_coverage(sess, p, pool)
    assert res is not None
    skill, pick = res
    assert skill in CTRL_SKILLS
    assert sess.reserve_phase_started_at is None  # still Phase 1


def test_phase1_end_sets_forfeit_marker(tmp_path):
    pool, p, sess = _ctrl_setup(tmp_path, reserve=5)
    for s in CTRL_SKILLS:
        sess.posteriors[s] = 0.99  # all resolved -> routing returns None
    sess.misconception_applicable = set()  # nothing to backfill
    sess.question_history = [history_entry("x", "SkillA", i + 1) for i in range(4)]
    res = select_next_coverage(sess, p, pool)
    assert res is None  # no backfill, no unsure -> complete
    assert sess.reserve_phase_started_at == 4  # marker fixed at the end count


def test_reserve_zero_is_inert(tmp_path):
    pool, p, sess = _ctrl_setup(tmp_path, reserve=0)
    for s in CTRL_SKILLS:
        sess.posteriors[s] = 0.99
    res = select_next_coverage(sess, p, pool)
    assert res is None  # reserve 0 -> no Phase 2/3 even with applicable unmet


def test_phase2_pass_a_backfills_to_floor(tmp_path):
    pool, p, sess = _ctrl_setup(tmp_path, reserve=5)
    sess.reserve_phase_started_at = 0          # past Phase 1
    sess.misconception_applicable = {"x_plus_0"}
    # asked is 0 (< target 2) -> pass A needs x_plus_0 -> backfill picks its carrier
    res = select_next_coverage(sess, p, pool)
    assert res is not None
    skill, pick = res
    assert pick.question_id == "d1"  # the x_plus_0 carrier


def test_phase2_reachability_gate(tmp_path):
    # extra=2 -> cap=4. Resolve all skills so Phase 3 cannot mask pass B.
    pool, p, sess = _ctrl_setup(tmp_path, reserve=5, extra=2)
    for s in CTRL_SKILLS:
        sess.posteriors[s] = 0.99
    sess.reserve_phase_started_at = 0
    sess.misconception_applicable = {"x_plus_0"}

    def fires(asked, correct):
        sess.misconception_asked = {"x_plus_0": asked}
        sess.misconception_correct = {"x_plus_0": correct}
        return select_next_coverage(sess, p, pool) is not None

    assert fires(2, 1) is True    # bubble: 50%, reachable (1+2)/4=0.75 -> ask
    assert fires(2, 2) is False   # cleared: 100% -> no extra (2c)
    assert fires(2, 0) is False   # unreachable: max 2/4=50% (2b)
    assert fires(3, 2) is True    # 2/3, reachable (2+1)/4=0.75 -> ask
    assert fires(3, 1) is False   # 1/3, unreachable (1+1)/4=0.5 (2b)
    assert fires(4, 2) is False   # cap reached (2a)


def test_reserve_exhaustion_returns_none(tmp_path):
    pool, p, sess = _ctrl_setup(tmp_path, reserve=3)
    sess.reserve_phase_started_at = 0
    sess.misconception_applicable = {"x_plus_0"}        # still unmet
    sess.question_history = [history_entry("h", "SkillA", i + 1) for i in range(3)]
    # reserve_consumed = 3 - 0 = 3 >= reserve_size 3 -> done (shortfall)
    assert select_next_coverage(sess, p, pool) is None


def test_phase3_leftover_when_no_backfill_needed(tmp_path):
    pool, p, sess = _ctrl_setup(tmp_path, reserve=5)
    sess.reserve_phase_started_at = 0
    sess.misconception_applicable = set()       # no backfill needs
    sess.posteriors["SkillA"] = 0.99            # resolved
    sess.posteriors["SkillB"] = 0.5             # unsure -> Phase 3 target
    res = select_next_coverage(sess, p, pool)
    assert res is not None
    skill, pick = res
    assert skill == "SkillB"  # leftover-to-mastery on the unsure skill


def test_phase3_none_when_all_resolved(tmp_path):
    pool, p, sess = _ctrl_setup(tmp_path, reserve=5)
    sess.reserve_phase_started_at = 0
    sess.misconception_applicable = set()
    for s in CTRL_SKILLS:
        sess.posteriors[s] = 0.99
    assert select_next_coverage(sess, p, pool) is None
