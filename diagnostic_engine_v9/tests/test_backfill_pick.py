"""Checkpoint 3a of the misconception-coverage layer: the skill-agnostic
`backfill_pick` selection primitive (spec section 5.2).

This is a pure primitive: given a `needed` misconception set it returns the
not-yet-asked, eligible question (across all in-scope skills) advancing the most
of `needed`, tiebroken by sharpest then the mode pick, or None when nothing
eligible carries a needed tag. The pass-A / pass-B orchestration and reserve
accounting live in the phase controller (checkpoint 3b).
"""

from engine.question_pool import CsvQuestionPool

from tests.test_question_pool import (
    row, write_csv, write_lookup, make_session, history_entry,
)

SCOPE = ["SkillA", "SkillB"]


def _pool(tmp_path, params_rows, lookup_rows, *, selection="random", seed=1):
    return CsvQuestionPool(
        write_csv(tmp_path / "p.csv", params_rows),
        lookup_path=write_lookup(tmp_path / "lk.csv", lookup_rows),
        selection=selection, seed=seed,
    )


def test_greedy_multi_tag_picks_most_covering(tmp_path):
    # q2 covers two needed tags, q1 one, q3 none -> q2.
    params = [row(f"A|q{i}", f"qp{i}", "SkillA", "all", 0.80) for i in (1, 2, 3)]
    lookup = [
        {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
        {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2",
         "x_plus_0": 1, "x_plus_x": 1},
        {"tenant": "Delhi", "item": "A|q3", "question_x_id": "d3"},
    ]
    pool = _pool(tmp_path, params, lookup)
    for seed in range(15):
        pool._rng.seed(seed)
        res = pool.backfill_pick(tenant_id="Delhi", grade=5, skills_in_scope=SCOPE,
                                  session=make_session(5), needed={"x_plus_0", "x_plus_x"})
        assert res is not None and res[1].question_id == "d2"


def test_skill_agnostic_picks_from_any_in_scope_skill(tmp_path):
    # The only carrier of the needed tag is in SkillB.
    params = [
        row("A|q1", "qp1", "SkillA", "all", 0.80),
        row("B|q1", "qp2", "SkillB", "all", 0.80),
    ]
    lookup = [
        {"tenant": "Delhi", "item": "A|q1", "question_x_id": "da", "x_plus_0": 1},
        {"tenant": "Delhi", "item": "B|q1", "question_x_id": "db", "zero_minus_x": 1},
    ]
    pool = _pool(tmp_path, params, lookup)
    res = pool.backfill_pick(tenant_id="Delhi", grade=5, skills_in_scope=SCOPE,
                              session=make_session(5), needed={"zero_minus_x"})
    assert res is not None and res[1].question_id == "db"


def test_no_repeat_excludes_already_asked(tmp_path):
    # Two carriers of the needed tag; q1 already asked -> must pick q2.
    params = [row(f"A|q{i}", f"qp{i}", "SkillA", "all", 0.80) for i in (1, 2)]
    lookup = [
        {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
        {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2", "x_plus_0": 1},
    ]
    pool = _pool(tmp_path, params, lookup)
    sess = make_session(5, history=[history_entry("d1", "SkillA")])  # d1 asked
    for seed in range(15):
        pool._rng.seed(seed)
        res = pool.backfill_pick(tenant_id="Delhi", grade=5, skills_in_scope=SCOPE,
                                  session=sess, needed={"x_plus_0"})
        assert res is not None and res[1].question_id == "d2"


def test_returns_none_when_no_carrier_remains(tmp_path):
    # Only carrier already asked -> shortfall (None).
    params = [row("A|q1", "qp1", "SkillA", "all", 0.80)]
    lookup = [{"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1}]
    pool = _pool(tmp_path, params, lookup)
    sess = make_session(5, history=[history_entry("d1", "SkillA")])
    assert pool.backfill_pick(tenant_id="Delhi", grade=5, skills_in_scope=SCOPE,
                              session=sess, needed={"x_plus_0"}) is None
    # also None for an empty needed set
    assert pool.backfill_pick(tenant_id="Delhi", grade=5, skills_in_scope=SCOPE,
                              session=make_session(5), needed=set()) is None


def test_ignores_discrimination_floor_for_coverage(tmp_path):
    # The only carrier of the needed tag is below the discrimination floor (0.50);
    # backfill must still pick it (coverage, not window).
    params = [
        row("A|q1", "qp1", "SkillA", "all", 0.80),          # high disc, no needed tag
        row("A|q2", "qp2", "SkillA", "all", 0.30),          # below floor, carries it
    ]
    lookup = [
        {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1"},
        {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2", "zero_minus_x": 1},
    ]
    pool = _pool(tmp_path, params, lookup)
    res = pool.backfill_pick(tenant_id="Delhi", grade=5, skills_in_scope=SCOPE,
                              session=make_session(5), needed={"zero_minus_x"})
    assert res is not None and res[1].question_id == "d2"


def test_sharpest_tiebreak_among_equal_coverage(tmp_path):
    # Both carry the one needed tag; the sharper one is preferred.
    params = [
        row("A|q1", "qp1", "SkillA", "all", 0.60),
        row("A|q2", "qp2", "SkillA", "all", 0.85),
    ]
    lookup = [
        {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
        {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2", "x_plus_0": 1},
    ]
    pool = _pool(tmp_path, params, lookup)
    for seed in range(15):
        pool._rng.seed(seed)
        res = pool.backfill_pick(tenant_id="Delhi", grade=5, skills_in_scope=SCOPE,
                                  session=make_session(5), needed={"x_plus_0"})
        assert res is not None and res[1].question_id == "d2"  # sharper always wins


def test_exposure_spread_then_deterministic_collapse(tmp_path):
    # Equal coverage AND equal discrimination -> random spreads, deterministic
    # collapses to the lexicographically smallest item.
    params = [row(f"A|q{i}", f"qp{i}", "SkillA", "all", 0.80) for i in (1, 2)]
    lookup = [
        {"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1},
        {"tenant": "Delhi", "item": "A|q2", "question_x_id": "d2", "x_plus_0": 1},
    ]
    seen = set()
    for seed in range(40):
        pool = _pool(tmp_path, params, lookup, selection="random", seed=seed)
        seen.add(pool.backfill_pick(tenant_id="Delhi", grade=5, skills_in_scope=SCOPE,
                                    session=make_session(5),
                                    needed={"x_plus_0"})[1].question_id)
    assert seen == {"d1", "d2"}
    det = _pool(tmp_path, params, lookup, selection="deterministic", seed=1)
    assert det.backfill_pick(tenant_id="Delhi", grade=5, skills_in_scope=SCOPE,
                             session=make_session(5),
                             needed={"x_plus_0"})[1].question_id == "d1"


def test_pick_carries_tags_and_overrides(tmp_path):
    params = [row("A|q1", "qp1", "SkillA", "all", 0.80, slip=0.1, guess=0.1)]
    lookup = [{"tenant": "Delhi", "item": "A|q1", "question_x_id": "d1", "x_plus_0": 1}]
    pool = _pool(tmp_path, params, lookup)
    res = pool.backfill_pick(tenant_id="Delhi", grade=5, skills_in_scope=SCOPE,
                              session=make_session(5), needed={"x_plus_0"})
    assert res is not None
    skill, pick = res
    assert skill == "SkillA"  # backfill returns the chosen question's skill
    assert pick.question_id == "d1"
    assert pick.slip_override == 0.1 and pick.guess_override == 0.1
    assert pick.misconceptions is not None and pick.misconceptions["x_plus_0"] == 1
