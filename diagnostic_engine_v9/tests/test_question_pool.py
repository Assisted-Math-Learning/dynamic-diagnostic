"""
Unit tests for CsvQuestionPool (the interim production question pool).

Covers the spec section 8 acceptance criteria for the pool itself:
candidate enumeration by skill; deduplication and no-repeat keyed on `item`;
the discrimination-window rule (weak tail excluded, flat/borrowed skill admits
all, floor excludes weak questions); the grade-row-then-`all` fallback; the
NoQuestionForSkillError paths; and seed-fixed reproducibility of the random
pick. The end-to-end "override reaches the Bayes update" test lives with the
API integration tests, since it exercises record_response.

StubQuestionPool keeps its existing coverage elsewhere; these tests are
CsvQuestionPool-specific.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

from tests import DATA_DIR
from typing import List, Optional

import pytest

from engine.api.errors import NoQuestionForSkillError
from engine.question_pool import CsvQuestionPool, QuestionPick
from engine.routing import Purpose
from engine.session import QuestionHistoryEntry, RoutingMode, Session, SessionStatus


# === helpers ================================================================


# Default header for synthetic CSVs. Order matches the real file's relevant
# columns; extra real-file columns are omitted because the pool ignores them.
_HEADER = ["item", "q_x_id", "l2_5_skill", "q_type", "grade", "slip", "guess", "discrimination"]


def write_csv(path: Path, rows: List[dict], header: Optional[List[str]] = None) -> str:
    """Write a small question_parameters-style CSV and return its path."""
    header = header or _HEADER
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return str(path)


def row(item, q_x_id, skill, grade, disc, *, q_type="Fib", slip=None, guess=None):
    """Build a CSV row. If slip/guess omitted, split the non-discrimination
    mass evenly so that discrimination == 1 - slip - guess holds."""
    if slip is None and guess is None:
        rest = round((1.0 - disc) / 2.0, 4)
        slip = rest
        guess = round(1.0 - disc - slip, 4)
    return {
        "item": item, "q_x_id": q_x_id, "l2_5_skill": skill, "q_type": q_type,
        "grade": grade, "slip": slip, "guess": guess, "discrimination": disc,
    }


def make_session(grade: int = 5, history: Optional[List[QuestionHistoryEntry]] = None) -> Session:
    return Session(
        sub_session_id="s1", learner_id="L1", tenant_id="T1", class_id="C1",
        grade=grade, status=SessionStatus.ACTIVE,
        started_at=datetime(2026, 6, 1, tzinfo=timezone.utc), ended_at=None,
        engine_version="test", posteriors={}, direct_obs_count={},
        questions_per_operation={}, question_history=history or [],
        routing_mode_counts={},
    )


def history_entry(question_id: str, skill_id: str, seq: int = 1) -> QuestionHistoryEntry:
    return QuestionHistoryEntry(
        sequence=seq, question_id=question_id, skill_id=skill_id, is_correct=True,
        asked_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        posterior_before=0.5, posterior_after=0.8,
        purpose=Purpose.ANCHOR, routing_mode=RoutingMode.ONLINE,
    )


# === loading and validation =================================================


class TestLoading:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            CsvQuestionPool(str(tmp_path / "does_not_exist.csv"))

    def test_missing_required_column_names_it(self, tmp_path):
        # Drop the 'discrimination' column from the header.
        header = ["item", "q_x_id", "l2_5_skill", "q_type", "grade", "slip", "guess"]
        p = tmp_path / "params.csv"
        with p.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
        with pytest.raises(ValueError, match="discrimination"):
            CsvQuestionPool(str(p))

    def test_bad_selection_mode_raises(self, tmp_path):
        path = write_csv(tmp_path / "p.csv", [row("I|a", "q1", "SkillA", "all", 0.80)])
        with pytest.raises(ValueError, match="random.*deterministic|deterministic.*random"):
            CsvQuestionPool(path, selection="weighted")

    def test_unparseable_param_raises_with_line(self, tmp_path):
        bad = row("I|a", "q1", "SkillA", "all", 0.80)
        bad["slip"] = "not_a_number"
        path = write_csv(tmp_path / "p.csv", [bad])
        with pytest.raises(ValueError, match="slip|parse"):
            CsvQuestionPool(path)


# === candidate enumeration ==================================================


class TestEnumeration:
    def test_available_skills_reports_loaded_skills(self, tmp_path):
        rows = [
            row("A|1", "qa1", "SkillA", "all", 0.80),
            row("A|2", "qa2", "SkillA", "all", 0.82),
            row("B|1", "qb1", "SkillB", "all", 0.75),
        ]
        pool = CsvQuestionPool(write_csv(tmp_path / "p.csv", rows))
        assert pool.available_skills == {"SkillA", "SkillB"}

    def test_unknown_skill_raises(self, tmp_path):
        rows = [row("A|1", "qa1", "SkillA", "all", 0.80)]
        pool = CsvQuestionPool(write_csv(tmp_path / "p.csv", rows))
        with pytest.raises(NoQuestionForSkillError, match="no questions"):
            pool.pick_question_for_skill(
                skill="SkillZ", session=make_session(), grade=5, tenant_id="T1"
            )

    def test_distinct_items_not_distinct_rows(self, tmp_path):
        # One item with several grade rows is ONE candidate. With a single
        # item available, every pick must return that item's q_x_id.
        rows = [
            row("A|1", "qa1", "SkillA", "3", 0.80),
            row("A|1", "qa1", "SkillA", "4", 0.81),
            row("A|1", "qa1", "SkillA", "all", 0.79),
        ]
        pool = CsvQuestionPool(write_csv(tmp_path / "p.csv", rows), seed=1)
        pick = pool.pick_question_for_skill(
            skill="SkillA", session=make_session(grade=4), tenant_id="T1", grade=4
        )
        assert pick.question_id == "qa1"


# === no-repeat (keyed on item) ==============================================


class TestNoRepeat:
    def _two_item_pool(self, tmp_path):
        rows = [
            row("A|1", "qa1", "SkillA", "all", 0.80),
            row("A|2", "qa2", "SkillA", "all", 0.80),
        ]
        return CsvQuestionPool(write_csv(tmp_path / "p.csv", rows), seed=3)

    def test_asked_item_excluded(self, tmp_path):
        pool = self._two_item_pool(tmp_path)
        # History contains qa1 -> item A|1 excluded -> only A|2 (qa2) can return.
        sess = make_session(history=[history_entry("qa1", "SkillA")])
        for _ in range(5):
            pick = pool.pick_question_for_skill(
                skill="SkillA", session=sess, grade=5, tenant_id="T1"
            )
            assert pick.question_id == "qa2"

    def test_unknown_question_id_in_history_is_ignored(self, tmp_path):
        pool = self._two_item_pool(tmp_path)
        # A stub:: id (or any id not in the CSV) maps to no item and must not
        # exclude anything.
        sess = make_session(history=[history_entry("stub::SkillA::0001", "SkillA")])
        pick = pool.pick_question_for_skill(
            skill="SkillA", session=sess, grade=5, tenant_id="T1"
        )
        assert pick.question_id in {"qa1", "qa2"}

    def test_all_asked_raises(self, tmp_path):
        pool = self._two_item_pool(tmp_path)
        sess = make_session(history=[
            history_entry("qa1", "SkillA", seq=1),
            history_entry("qa2", "SkillA", seq=2),
        ])
        with pytest.raises(NoQuestionForSkillError, match="already asked"):
            pool.pick_question_for_skill(
                skill="SkillA", session=sess, grade=5, tenant_id="T1"
            )


# === window rule ============================================================


class TestWindowRule:
    def test_flat_skill_admits_all(self, tmp_path):
        # Borrowed-style skill: every question has identical discrimination.
        # The window must admit all of them, so over many picks we see each.
        rows = [row(f"A|{i}", f"qa{i}", "SkillA", "all", 0.80) for i in range(5)]
        pool = CsvQuestionPool(write_csv(tmp_path / "p.csv", rows), seed=11)
        seen = set()
        for _ in range(200):
            pick = pool.pick_question_for_skill(
                skill="SkillA", session=make_session(), grade=5, tenant_id="T1"
            )
            seen.add(pick.question_id)
        assert seen == {f"qa{i}" for i in range(5)}

    def test_weak_tail_excluded(self, tmp_path):
        # Top cluster at 0.85/0.84/0.83, weak tail at 0.60. Window = best-0.10
        # = 0.75, so the 0.60 item is dropped; it must never be picked.
        rows = [
            row("A|1", "qa1", "SkillA", "all", 0.85),
            row("A|2", "qa2", "SkillA", "all", 0.84),
            row("A|3", "qa3", "SkillA", "all", 0.83),
            row("A|tail", "qa_tail", "SkillA", "all", 0.60),
        ]
        pool = CsvQuestionPool(write_csv(tmp_path / "p.csv", rows), seed=5)
        seen = set()
        for _ in range(300):
            pick = pool.pick_question_for_skill(
                skill="SkillA", session=make_session(), grade=5, tenant_id="T1"
            )
            seen.add(pick.question_id)
        assert "qa_tail" not in seen
        assert seen == {"qa1", "qa2", "qa3"}

    def test_floor_excludes_below_threshold(self, tmp_path):
        # Two items below the 0.50 floor, one above. Even though the two weak
        # ones are within 0.10 of each other, the floor drops them.
        rows = [
            row("A|good", "qa_good", "SkillA", "all", 0.55),
            row("A|w1", "qa_w1", "SkillA", "all", 0.48),
            row("A|w2", "qa_w2", "SkillA", "all", 0.47),
        ]
        pool = CsvQuestionPool(write_csv(tmp_path / "p.csv", rows), seed=9)
        seen = set()
        for _ in range(100):
            pick = pool.pick_question_for_skill(
                skill="SkillA", session=make_session(), grade=5, tenant_id="T1"
            )
            seen.add(pick.question_id)
        assert seen == {"qa_good"}

    def test_custom_window_and_floor(self, tmp_path):
        # Widen the window to 0.30 so the 0.60 item is admitted; lower the
        # floor so nothing is floored. Demonstrates both are tunable.
        rows = [
            row("A|1", "qa1", "SkillA", "all", 0.85),
            row("A|2", "qa2", "SkillA", "all", 0.60),
        ]
        pool = CsvQuestionPool(
            write_csv(tmp_path / "p.csv", rows),
            window_width=0.30, discrimination_floor=0.40, seed=5,
        )
        seen = set()
        for _ in range(100):
            pick = pool.pick_question_for_skill(
                skill="SkillA", session=make_session(), grade=5, tenant_id="T1"
            )
            seen.add(pick.question_id)
        assert seen == {"qa1", "qa2"}

    def test_window_never_empties_single_candidate(self, tmp_path):
        # A skill with one question below the floor still returns it? No: the
        # floor is absolute. But a single question AT/above the floor returns.
        rows = [row("A|1", "qa1", "SkillA", "all", 0.55)]
        pool = CsvQuestionPool(write_csv(tmp_path / "p.csv", rows), seed=1)
        pick = pool.pick_question_for_skill(
            skill="SkillA", session=make_session(), grade=5, tenant_id="T1"
        )
        assert pick.question_id == "qa1"


# === grade fallback =========================================================


class TestGradeFallback:
    def _pool(self, tmp_path):
        # One item with a grade-5 row and an 'all' row carrying different slip
        # so we can tell which row was used.
        rows = [
            row("A|1", "qa1", "SkillA", "5", 0.80, slip=0.05, guess=0.15),
            row("A|1", "qa1", "SkillA", "all", 0.70, slip=0.20, guess=0.10),
        ]
        return CsvQuestionPool(write_csv(tmp_path / "p.csv", rows), seed=1)

    def test_grade_specific_row_used_when_present(self, tmp_path):
        pool = self._pool(tmp_path)
        pick = pool.pick_question_for_skill(
            skill="SkillA", session=make_session(grade=5), grade=5, tenant_id="T1"
        )
        # grade-5 row slip
        assert pick.slip_override == pytest.approx(0.05)
        assert pick.guess_override == pytest.approx(0.15)

    def test_all_row_used_when_no_grade_row(self, tmp_path):
        pool = self._pool(tmp_path)
        # Grade 2 has no specific row -> the 'all' row is used.
        pick = pool.pick_question_for_skill(
            skill="SkillA", session=make_session(grade=2), grade=2, tenant_id="T1"
        )
        assert pick.slip_override == pytest.approx(0.20)
        assert pick.guess_override == pytest.approx(0.10)

    def test_grade_without_row_or_all_raises(self, tmp_path):
        # An item that has only a grade-5 row (no 'all'); a grade-2 learner
        # cannot resolve it, and with no other candidate the pick raises.
        rows = [row("A|1", "qa1", "SkillA", "5", 0.80)]
        pool = CsvQuestionPool(write_csv(tmp_path / "p.csv", rows), seed=1)
        with pytest.raises(NoQuestionForSkillError, match="grade-resolvable"):
            pool.pick_question_for_skill(
                skill="SkillA", session=make_session(grade=2), grade=2, tenant_id="T1"
            )


# === selection modes ========================================================


class TestSelectionModes:
    def _spread_pool(self, tmp_path, **kw):
        rows = [
            row("A|1", "qa1", "SkillA", "all", 0.85),
            row("A|2", "qa2", "SkillA", "all", 0.84),
            row("A|3", "qa3", "SkillA", "all", 0.83),
        ]
        return CsvQuestionPool(write_csv(tmp_path / "p.csv", rows), **kw)

    def test_seed_reproducible(self, tmp_path):
        pool_a = self._spread_pool(tmp_path, seed=42)
        # Re-write the same file for a second pool (tmp_path file already there)
        pool_b = self._spread_pool(tmp_path, seed=42)
        picks_a = [
            pool_a.pick_question_for_skill(
                skill="SkillA", session=make_session(), grade=5, tenant_id="T1"
            ).question_id for _ in range(10)
        ]
        picks_b = [
            pool_b.pick_question_for_skill(
                skill="SkillA", session=make_session(), grade=5, tenant_id="T1"
            ).question_id for _ in range(10)
        ]
        assert picks_a == picks_b

    def test_different_seeds_can_differ(self, tmp_path):
        pool_a = self._spread_pool(tmp_path, seed=1)
        pool_b = self._spread_pool(tmp_path, seed=2)
        picks_a = [
            pool_a.pick_question_for_skill(
                skill="SkillA", session=make_session(), grade=5, tenant_id="T1"
            ).question_id for _ in range(20)
        ]
        picks_b = [
            pool_b.pick_question_for_skill(
                skill="SkillA", session=make_session(), grade=5, tenant_id="T1"
            ).question_id for _ in range(20)
        ]
        assert picks_a != picks_b

    def test_deterministic_picks_highest_discrimination(self, tmp_path):
        pool = self._spread_pool(tmp_path, selection="deterministic")
        for _ in range(5):
            pick = pool.pick_question_for_skill(
                skill="SkillA", session=make_session(), grade=5, tenant_id="T1"
            )
            assert pick.question_id == "qa1"  # disc 0.85 is highest

    def test_deterministic_lexicographic_tiebreak(self, tmp_path):
        # Two items tied at the top discrimination; the lexicographically
        # smaller item wins.
        rows = [
            row("A|zzz", "qa_zzz", "SkillA", "all", 0.85),
            row("A|aaa", "qa_aaa", "SkillA", "all", 0.85),
        ]
        pool = CsvQuestionPool(write_csv(tmp_path / "p.csv", rows), selection="deterministic")
        pick = pool.pick_question_for_skill(
            skill="SkillA", session=make_session(), grade=5, tenant_id="T1"
        )
        assert pick.question_id == "qa_aaa"  # item "A|aaa" < "A|zzz"


# === scope-coverage warning =================================================


class TestExpectedSkillsWarning:
    def test_warns_for_scope_skill_with_zero_questions(self, tmp_path, monkeypatch):
        warnings: List[str] = []

        class _FakeLogger:
            def warning(self, msg, *a, **k):
                warnings.append(msg)
            def info(self, *a, **k):
                pass

        monkeypatch.setattr(
            "engine.question_pool.get_logger", lambda *a, **k: _FakeLogger()
        )
        rows = [row("A|1", "qa1", "SkillA", "all", 0.80)]
        CsvQuestionPool(
            write_csv(tmp_path / "p.csv", rows),
            expected_skills={"SkillA", "SkillMissing"},
        )
        assert any("SkillMissing" in w for w in warnings)
        assert not any("SkillA" in w for w in warnings)

    def test_no_warning_when_expected_skills_absent(self, tmp_path, monkeypatch):
        warnings: List[str] = []

        class _FakeLogger:
            def warning(self, msg, *a, **k):
                warnings.append(msg)
            def info(self, *a, **k):
                pass

        monkeypatch.setattr(
            "engine.question_pool.get_logger", lambda *a, **k: _FakeLogger()
        )
        rows = [row("A|1", "qa1", "SkillA", "all", 0.80)]
        CsvQuestionPool(write_csv(tmp_path / "p.csv", rows))  # no expected_skills
        assert warnings == []


# === real data (skipped if the project file is not mounted) =================


class TestRealData:
    PATH = str(DATA_DIR / "question_parameters.csv")

    def _pool(self, **kw):
        if not Path(self.PATH).exists():
            pytest.skip("real question_parameters.csv not available")
        return CsvQuestionPool(self.PATH, **kw)

    def test_loads_40_skills(self):
        pool = self._pool(seed=1)
        assert len(pool.available_skills) == 40  # 667-bank swap added "1D - 1 to 4"

    def test_real_pick_returns_calibrated_values(self):
        pool = self._pool(seed=1)
        skill = next(iter(pool.available_skills))
        pick = pool.pick_question_for_skill(
            skill=skill, session=make_session(grade=5), grade=5, tenant_id="T1"
        )
        assert pick.question_id  # a real q_x_id
        assert pick.slip_override is not None
        assert pick.guess_override is not None
        # identity discrimination = 1 - slip - guess holds within rounding
        assert 0.0 <= pick.slip_override <= 1.0
        assert 0.0 <= pick.guess_override <= 1.0

    def test_grade_2_fallback_resolves_every_skill(self):
        pool = self._pool(seed=1)
        for skill in pool.available_skills:
            # Must not raise: every item has an 'all' row.
            pick = pool.pick_question_for_skill(
                skill=skill, session=make_session(grade=2), grade=2, tenant_id="T1"
            )
            assert pick.question_id


# === Tenant-aware resolution via the per-tenant lookup (Piece 5) ============


def write_lookup(path: Path, rows: List[dict]) -> str:
    """Write a small tenant_question_lookup-style CSV and return its path."""
    flags = [
        "x_plus_0", "x_plus_x", "x_minus_0", "zero_minus_x", "x_minus_x",
        "x_into_x", "x_into_0", "zero_end_n1", "zero_mid_n1",
        "zero_end_quotient_no_zero_n1", "zero_mid_quotient_no_zero_n1",
    ]
    header = ["tenant", "item", "question_x_id"] + flags
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            full = {k: 0 for k in flags}
            full.update(r)
            w.writerow(full)
    return str(path)


def write_retired(path: Path, rows: List[dict]) -> str:
    header = ["scope", "key", "reason", "retired_date"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow({"reason": "x", "retired_date": "2026-06-08", **r})
    return str(path)


class TestTenantAwareLookup:
    def _params(self, tmp_path):
        # Two items in SkillA, both high discrimination so both clear the window.
        rows = [
            row("A|q1", "q_params_1", "SkillA", "all", 0.80),
            row("A|q2", "q_params_2", "SkillA", "all", 0.80),
        ]
        return write_csv(tmp_path / "p.csv", rows)

    def test_resolution_uses_lookup_xid_not_params_xid(self, tmp_path):
        params = self._params(tmp_path)
        lookup = write_lookup(tmp_path / "lk.csv", [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "q_lookup_delhi_1_b"},
            {"tenant": "Delhi", "item": "A|q2", "question_x_id": "q_lookup_delhi_2_b"},
        ])
        pool = CsvQuestionPool(params, lookup_path=lookup, seed=1)
        pick = pool.pick_question_for_skill(
            skill="SkillA", session=make_session(grade=5), grade=5, tenant_id="Delhi")
        # The served id is the lookup's, never the params q_x_id.
        assert pick.question_id in {"q_lookup_delhi_1_b", "q_lookup_delhi_2_b"}
        assert pick.question_id not in {"q_params_1", "q_params_2"}
        # slip/guess still come from the calibration row.
        assert pick.slip_override is not None

    def test_availability_filter_drops_items_missing_in_tenant(self, tmp_path):
        params = self._params(tmp_path)
        # Delhi carries only q1; q2 is absent for Delhi.
        lookup = write_lookup(tmp_path / "lk.csv", [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "q_d1_b"},
            {"tenant": "Karnataka", "item": "A|q1", "question_x_id": "q_k1_b"},
            {"tenant": "Karnataka", "item": "A|q2", "question_x_id": "q_k2_b"},
        ])
        pool = CsvQuestionPool(params, lookup_path=lookup, seed=1)
        # Many draws: Delhi must never serve q2's content (it can't resolve it).
        for _ in range(25):
            pick = pool.pick_question_for_skill(
                skill="SkillA", session=make_session(grade=5), grade=5, tenant_id="Delhi")
            assert pick.question_id == "q_d1_b"

    def test_no_question_when_tenant_has_no_items_for_skill(self, tmp_path):
        params = self._params(tmp_path)
        lookup = write_lookup(tmp_path / "lk.csv", [
            {"tenant": "Karnataka", "item": "A|q1", "question_x_id": "q_k1_b"},
        ])
        pool = CsvQuestionPool(params, lookup_path=lookup, seed=1)
        # Delhi has zero items for SkillA -> genuine coverage gap.
        with pytest.raises(NoQuestionForSkillError, match="tenant-available"):
            pool.pick_question_for_skill(
                skill="SkillA", session=make_session(grade=5), grade=5, tenant_id="Delhi")

    def test_no_repeat_recognises_lookup_served_id(self, tmp_path):
        params = self._params(tmp_path)
        lookup = write_lookup(tmp_path / "lk.csv", [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "q_d1_b"},
            {"tenant": "Delhi", "item": "A|q2", "question_x_id": "q_d2_b"},
        ])
        pool = CsvQuestionPool(params, lookup_path=lookup, seed=1)
        # History carries a lookup-served id; the pool must map it back to its
        # item and not repeat it.
        sess = make_session(grade=5, history=[history_entry("q_d1_b", "SkillA")])
        for _ in range(25):
            pick = pool.pick_question_for_skill(
                skill="SkillA", session=sess, grade=5, tenant_id="Delhi")
            assert pick.question_id == "q_d2_b"

    def test_runtime_retired_item_scope_filtered(self, tmp_path):
        params = self._params(tmp_path)
        lookup = write_lookup(tmp_path / "lk.csv", [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "q_d1_b"},
            {"tenant": "Delhi", "item": "A|q2", "question_x_id": "q_d2_b"},
        ])
        retired = write_retired(tmp_path / "r.csv", [{"scope": "item", "key": "A|q1"}])
        pool = CsvQuestionPool(params, lookup_path=lookup, retired_path=retired, seed=1)
        for _ in range(25):
            pick = pool.pick_question_for_skill(
                skill="SkillA", session=make_session(grade=5), grade=5, tenant_id="Delhi")
            assert pick.question_id == "q_d2_b"  # q1 retired

    def test_runtime_retired_xid_scope_filtered(self, tmp_path):
        params = self._params(tmp_path)
        lookup = write_lookup(tmp_path / "lk.csv", [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "q_d1_b"},
            {"tenant": "Delhi", "item": "A|q2", "question_x_id": "q_d2_b"},
        ])
        retired = write_retired(tmp_path / "r.csv", [{"scope": "question_x_id", "key": "q_d1_b"}])
        pool = CsvQuestionPool(params, lookup_path=lookup, retired_path=retired, seed=1)
        for _ in range(25):
            pick = pool.pick_question_for_skill(
                skill="SkillA", session=make_session(grade=5), grade=5, tenant_id="Delhi")
            assert pick.question_id == "q_d2_b"  # q_d1_b instance retired

    def test_legacy_mode_unchanged_without_lookup(self, tmp_path):
        params = self._params(tmp_path)
        pool = CsvQuestionPool(params, seed=1)  # no lookup
        pick = pool.pick_question_for_skill(
            skill="SkillA", session=make_session(grade=5), grade=5, tenant_id="any-tenant")
        # Legacy: serves the params q_x_id, tenant ignored.
        assert pick.question_id in {"q_params_1", "q_params_2"}

    def test_pick_carries_misconception_tags_in_tenant_mode(self, tmp_path):
        params = self._params(tmp_path)
        lookup = write_lookup(tmp_path / "lk.csv", [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "q_d1_b",
             "x_plus_0": 1, "x_plus_x": 0},
            {"tenant": "Delhi", "item": "A|q2", "question_x_id": "q_d2_b",
             "x_plus_0": 0, "x_plus_x": 1},
        ])
        pool = CsvQuestionPool(params, lookup_path=lookup, seed=1)
        # exhaust both so we observe each item's tags across draws
        seen = {}
        for q1_first in (True, False):
            sess = make_session(grade=5)
            pick = pool.pick_question_for_skill(
                skill="SkillA", session=sess, grade=5, tenant_id="Delhi")
            seen[pick.question_id] = pick.misconceptions
        # tags are a dict of all 11 flags, matching the lookup for that item
        for qid, tags in seen.items():
            assert isinstance(tags, dict) and len(tags) == 11
        if "q_d1_b" in seen:
            assert seen["q_d1_b"]["x_plus_0"] == 1 and seen["q_d1_b"]["x_plus_x"] == 0
        if "q_d2_b" in seen:
            assert seen["q_d2_b"]["x_plus_0"] == 0 and seen["q_d2_b"]["x_plus_x"] == 1

    def test_legacy_mode_pick_has_no_misconceptions(self, tmp_path):
        params = self._params(tmp_path)
        pool = CsvQuestionPool(params, seed=1)  # no lookup
        pick = pool.pick_question_for_skill(
            skill="SkillA", session=make_session(grade=5), grade=5, tenant_id="T1")
        assert pick.misconceptions is None

    def test_questionpick_keeps_three_fields_and_defaults(self):
        # Interface stability (spec 7.4): existing construction with three
        # positional/keyword fields still works; misconceptions defaults to None.
        qp = QuestionPick(question_id="q", slip_override=0.1, guess_override=0.2)
        assert qp.question_id == "q" and qp.slip_override == 0.1 and qp.guess_override == 0.2
        assert qp.misconceptions is None

    def test_accessor_reads_tags_for_unpicked_items(self, tmp_path):
        params = self._params(tmp_path)
        lookup = write_lookup(tmp_path / "lk.csv", [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "q_d1_b", "x_plus_0": 1},
            {"tenant": "Delhi", "item": "A|q2", "question_x_id": "q_d2_b", "x_plus_x": 1},
        ])
        pool = CsvQuestionPool(params, lookup_path=lookup, seed=1)
        # The accessor returns tags for BOTH items regardless of which is picked,
        # so a coverage layer can inspect candidates it did not choose.
        t1 = pool.misconceptions_for_item("A|q1")
        t2 = pool.misconceptions_for_item("A|q2")
        assert t1 is not None and len(t1) == 11 and t1["x_plus_0"] == 1 and t1["x_plus_x"] == 0
        assert t2 is not None and t2["x_plus_x"] == 1 and t2["x_plus_0"] == 0
        # field and accessor agree for the chosen item
        pick = pool.pick_question_for_skill(
            skill="SkillA", session=make_session(grade=5), grade=5, tenant_id="Delhi")
        chosen_item = "A|q1" if pick.question_id == "q_d1_b" else "A|q2"
        assert pick.misconceptions == pool.misconceptions_for_item(chosen_item)

    def test_accessor_none_in_legacy_mode_and_unknown_item(self, tmp_path):
        params = self._params(tmp_path)
        pool = CsvQuestionPool(params, seed=1)  # no lookup
        assert pool.misconceptions_for_item("A|q1") is None
        lookup = write_lookup(tmp_path / "lk.csv", [
            {"tenant": "Delhi", "item": "A|q1", "question_x_id": "q_d1_b"},
        ])
        pool2 = CsvQuestionPool(params, lookup_path=lookup, seed=1)
        assert pool2.misconceptions_for_item("A|nonexistent") is None
