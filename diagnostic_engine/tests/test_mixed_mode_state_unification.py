"""Phase B (mixed-mode v11 section 1 / Phase 1): state is unified over the whole
question_history in item space, segment-agnostically.

The online engine already reads the whole history for no-repeat, budget, and
three-pass (no routing_mode filter anywhere), so there is no per-segment view to
refactor. These are the regression guards that LOCK that invariant: an
offline_replay answer must be counted identically to an online one, so the
offline answers Phase C ingests are seen by no-repeat, the budget, and the
per-operation (three-pass) counters. Gated on real data like the other
integration tests.
"""
from dataclasses import replace
from pathlib import Path

import pytest

from tests import DATA_DIR

PROJECT = DATA_DIR
LOOKUP = Path(__file__).resolve().parents[1] / "inputs" / "tenant_question_lookup_v2.csv"

pytestmark = pytest.mark.skipif(
    not (PROJECT.exists() and (PROJECT / "question_parameters.csv").exists() and LOOKUP.exists()),
    reason="real project data / tenant lookup not present",
)

from engine.api.errors import NoQuestionForSkillError    # noqa: E402
from engine.session import (                              # noqa: E402
    RoutingMode, record_response, start_session,
)


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
    pool = CsvQuestionPool(
        str(qpath), expected_skills={s.name for s in config.skills},
        seed=7, lookup_path=str(LOOKUP), misconception_target=2,
    )
    params = config.get_engine_params(grade, lattice)
    return config, lattice, pool, params


def _pick_qid(pool, session, grade, skill, tenant="Delhi"):
    try:
        return pool.pick_question_for_skill(
            skill=skill, session=session, grade=grade, tenant_id=tenant).question_id
    except NoQuestionForSkillError:
        return None


def _first_unasked(pool, session, params, grade, tenant="Delhi"):
    """(skill, question_id) for some in-scope skill with an unasked item."""
    for skill in params.skills_in_scope:
        qid = _pick_qid(pool, session, grade, skill, tenant)
        if qid is not None:
            return skill, qid
    return None, None


def _start(params, sid, grade=3):
    return start_session(sub_session_id=sid, learner_id="l", tenant_id="Delhi",
                         class_id="c", grade=grade, engine_version="test",
                         params=params).session, None


def test_offline_replay_answer_is_counted_like_online():
    # Catalogue (v11 section 23): TC-MIX-03, TC-MIX-04
    config, lattice, pool, params = _setup(grade=3)
    sr = start_session(sub_session_id="mix-1", learner_id="l", tenant_id="Delhi",
                       class_id="c", grade=3, engine_version="test", params=params)
    session = sr.session

    # One ONLINE answer for the chosen first-question skill.
    on_skill = sr.first_question.skill
    on_qid = _pick_qid(pool, session, 3, on_skill)
    assert on_qid is not None
    record_response(session, skill_id=on_skill, question_id=on_qid, is_correct=True,
                    params=params, routing_mode=RoutingMode.ONLINE, defer_next=True)
    online_item = pool._qxid_to_item[on_qid]

    # One OFFLINE_REPLAY answer for a different, unasked item.
    off_skill, off_qid = _first_unasked(pool, session, params, 3)
    assert off_qid is not None, "expected at least one more unasked item"
    offline_item = pool._qxid_to_item[off_qid]
    record_response(session, skill_id=off_skill, question_id=off_qid, is_correct=False,
                    params=params, routing_mode=RoutingMode.OFFLINE_REPLAY, defer_next=True)

    # Budget: questions_total counts BOTH modes.
    assert session.questions_total == 2
    # routing_mode_counts tracks both.
    assert session.routing_mode_counts[RoutingMode.ONLINE] == 1
    assert session.routing_mode_counts[RoutingMode.OFFLINE_REPLAY] == 1
    # Three-pass: per-operation counts include the offline_replay answer, and
    # they sum to questions_total (so a mixed session's budget is exact).
    assert sum(session.questions_per_operation.values()) == session.questions_total
    off_op = params.skill_to_operation.get(off_skill)
    assert session.questions_per_operation.get(off_op, 0) >= 1

    # No-repeat (item space) sees BOTH items - segment-agnostic.
    answered = pool._answered_items(session)
    assert online_item in answered
    assert offline_item in answered


def test_no_repeat_excludes_an_offline_replay_item():
    # Catalogue (v11 section 23): TC-MIX-02
    config, lattice, pool, params = _setup(grade=3)
    sr = start_session(sub_session_id="mix-2", learner_id="l", tenant_id="Delhi",
                       class_id="c", grade=3, engine_version="test", params=params)
    session = sr.session
    skill = sr.first_question.skill
    qid = _pick_qid(pool, session, 3, skill)
    assert qid is not None
    record_response(session, skill_id=skill, question_id=qid, is_correct=True,
                    params=params, routing_mode=RoutingMode.OFFLINE_REPLAY, defer_next=True)
    offline_item = pool._qxid_to_item[qid]

    assert offline_item in pool._answered_items(session)
    # A subsequent pick for the SAME skill never returns that (offline) item.
    try:
        p2 = pool.pick_question_for_skill(
            skill=skill, session=session, grade=3, tenant_id="Delhi")
        assert pool._qxid_to_item[p2.question_id] != offline_item
    except NoQuestionForSkillError:
        pass  # the skill's only item was the offline one; correctly exhausted


def test_answered_items_drops_unknown_id():
    # Catalogue (v11 section 23): TC-MIX-05
    config, lattice, pool, params = _setup(grade=3)
    sr = start_session(sub_session_id="mix-3", learner_id="l", tenant_id="Delhi",
                       class_id="c", grade=3, engine_version="test", params=params)
    session = sr.session
    skill = sr.first_question.skill
    qid = _pick_qid(pool, session, 3, skill)
    assert qid is not None
    record_response(session, skill_id=skill, question_id=qid, is_correct=True,
                    params=params, routing_mode=RoutingMode.ONLINE, defer_next=True)
    known_item = pool._qxid_to_item[qid]
    # Append an entry whose question_x_id is not in the pool (corrupt/hard-deleted).
    bogus = replace(session.question_history[0], question_id="q_not_in_pool_xyz")
    session.question_history.append(bogus)
    answered = pool._answered_items(session)
    assert known_item in answered
    assert None not in answered
