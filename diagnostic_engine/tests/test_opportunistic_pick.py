"""Checkpoint 2 of the misconception-coverage layer: the opportunistic pick
inside `pick_question_for_skill` (spec section 5.1).

The pick prefers, among the discrimination-window survivors, the candidate that
advances the most still-unmet applicable misconceptions; it then narrows to the
sharpest and lets the existing mode make the final choice. Crucially it engages
ONLY when a candidate can advance an unmet applicable misconception, so when no
misconceptions are in play selection is byte-identical to before.
"""

from pathlib import Path
from typing import Set

from engine.question_pool import CsvQuestionPool

from tests.test_question_pool import row, write_csv, write_lookup, make_session


def _session(grade: int, applicable: Set[str], asked=None):
    s = make_session(grade=grade)
    s.misconception_applicable = set(applicable)
    s.misconception_asked = dict(asked or {})
    return s


def _pool(tmp_path, params_rows, lookup_rows, *, selection="random", seed=1, target=2):
    params = write_csv(tmp_path / "p.csv", params_rows)
    lookup = write_lookup(tmp_path / "lk.csv", lookup_rows)
    return CsvQuestionPool(params, lookup_path=lookup, selection=selection, seed=seed,
                           misconception_target=target)


# --- prefers the tagged in-window candidate (test case 1) ------------------


class TestOpportunisticPreference:
    def _setup(self, tmp_path, **kw):
        # Two equally-sharp items in SkillA; q1 tagged x_plus_0, q2 untagged.
        params = [
            row("A|q1", "qp1", "SkillA", "all", 0.80),
            row("A|q2", "qp2", "SkillA", "all", 0.80),
        ]
        lookup = [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
            {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2"},
        ]
        return _pool(tmp_path, params, lookup, **kw)

    def test_tagged_chosen_random_mode(self, tmp_path):
        pool = self._setup(tmp_path, selection="random")
        sess = _session(5, {"x_plus_0"})
        pick = pool.pick_question_for_skill(skill="SkillA", session=sess, grade=5,
                                            tenant_id="Delhi")
        assert pick.question_id == "d1"  # the tagged one, deterministically

    def test_tagged_chosen_deterministic_mode(self, tmp_path):
        pool = self._setup(tmp_path, selection="deterministic")
        sess = _session(5, {"x_plus_0"})
        pick = pool.pick_question_for_skill(skill="SkillA", session=sess, grade=5,
                                            tenant_id="Delhi")
        assert pick.question_id == "d1"

    def test_no_preference_when_misconception_already_met(self, tmp_path):
        # x_plus_0 already at target -> unmet empty -> inert -> over many seeds
        # both candidates appear (no collapse onto the tagged one).
        seen = set()
        for seed in range(40):
            pool = self._setup(tmp_path, selection="random", seed=seed)
            sess = _session(5, {"x_plus_0"}, asked={"x_plus_0": 2})  # met
            seen.add(pool.pick_question_for_skill(
                skill="SkillA", session=sess, grade=5, tenant_id="Delhi").question_id)
        assert seen == {"d1", "d2"}

    def test_no_preference_when_no_applicable(self, tmp_path):
        # Empty applicable set -> inert -> uniform over the whole window.
        seen = set()
        for seed in range(40):
            pool = self._setup(tmp_path, selection="random", seed=seed)
            sess = _session(5, set())
            seen.add(pool.pick_question_for_skill(
                skill="SkillA", session=sess, grade=5, tenant_id="Delhi").question_id)
        assert seen == {"d1", "d2"}  # both appear; not collapsed


# --- window boundary: a tagged out-of-window candidate is never chosen ------


def test_tagged_outside_window_never_chosen(tmp_path):
    # q1 sharp & untagged (in window), q3 tagged but low discrimination (outside
    # the 0.10 window below the 0.80 best). Coverage must not pull it in.
    params = [
        row("A|q1", "qp1", "SkillA", "all", 0.80),
        row("A|q3", "qp3", "SkillA", "all", 0.55),  # outside window (< 0.70)
    ]
    lookup = [
        {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1"},
        {"tenant": "Delhi", "item": "A|q3", "question_x_id": "d3", "x_plus_0": 1},
    ]
    pool = CsvQuestionPool(write_csv(tmp_path / "p.csv", params),
                           lookup_path=write_lookup(tmp_path / "lk.csv", lookup),
                           selection="random", seed=1)
    sess = _session(5, {"x_plus_0"})
    for seed in range(20):
        pool._rng.seed(seed)
        pick = pool.pick_question_for_skill(skill="SkillA", session=sess, grade=5,
                                            tenant_id="Delhi")
        assert pick.question_id == "d1"  # the in-window untagged one, never d3


# --- greedy multi-tag: advance the most unmet misconceptions ----------------


def test_greedy_prefers_candidate_advancing_more(tmp_path):
    # All three equally sharp & in window. q2 carries two unmet tags, q1 one,
    # q3 none -> q2 wins.
    params = [
        row("A|q1", "qp1", "SkillA", "all", 0.80),
        row("A|q2", "qp2", "SkillA", "all", 0.80),
        row("A|q3", "qp3", "SkillA", "all", 0.80),
    ]
    lookup = [
        {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
        {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2",
         "x_plus_0": 1, "x_plus_x": 1},
        {"tenant": "Delhi", "item": "A|q3", "question_x_id": "d3"},
    ]
    pool = CsvQuestionPool(write_csv(tmp_path / "p.csv", params),
                           lookup_path=write_lookup(tmp_path / "lk.csv", lookup),
                           selection="random", seed=1)
    sess = _session(5, {"x_plus_0", "x_plus_x"})
    for seed in range(20):
        pool._rng.seed(seed)
        assert pool.pick_question_for_skill(
            skill="SkillA", session=sess, grade=5, tenant_id="Delhi").question_id == "d2"


# --- production exposure spread (test case 12) ------------------------------


def test_exposure_spread_among_equal_tagged_candidates(tmp_path):
    # Two equally-sharp candidates BOTH carrying the one unmet misconception:
    # greedy + sharpest leave both -> random mode spreads across both; the
    # deterministic mode collapses to the lexicographically smallest.
    params = [
        row("A|q1", "qp1", "SkillA", "all", 0.80),
        row("A|q2", "qp2", "SkillA", "all", 0.80),
    ]
    lookup = [
        {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
        {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2", "x_plus_0": 1},
    ]
    p = write_csv(tmp_path / "p.csv", params)
    lk = write_lookup(tmp_path / "lk.csv", lookup)
    sess = _session(5, {"x_plus_0"})

    seen = set()
    for seed in range(40):
        pool = CsvQuestionPool(p, lookup_path=lk, selection="random", seed=seed)
        seen.add(pool.pick_question_for_skill(
            skill="SkillA", session=sess, grade=5, tenant_id="Delhi").question_id)
    assert seen == {"d1", "d2"}  # spread preserved, not collapsed

    det = CsvQuestionPool(p, lookup_path=lk, selection="deterministic", seed=1)
    assert det.pick_question_for_skill(
        skill="SkillA", session=sess, grade=5, tenant_id="Delhi").question_id == "d1"


# --- deterministic reproducibility -----------------------------------------


def test_deterministic_reproducible(tmp_path):
    params = [
        row("A|q1", "qp1", "SkillA", "all", 0.80),
        row("A|q2", "qp2", "SkillA", "all", 0.80),
    ]
    lookup = [
        {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
        {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2", "x_plus_x": 1},
    ]
    p = write_csv(tmp_path / "p.csv", params)
    lk = write_lookup(tmp_path / "lk.csv", lookup)
    sess = _session(5, {"x_plus_0", "x_plus_x"})
    picks = {
        CsvQuestionPool(p, lookup_path=lk, selection="deterministic", seed=7)
        .pick_question_for_skill(skill="SkillA", session=sess, grade=5,
                                 tenant_id="Delhi").question_id
        for _ in range(5)
    }
    assert len(picks) == 1  # identical every time
