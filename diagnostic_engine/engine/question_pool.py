"""
Question pool: maps a skill to a question_id (x_id) plus optional per-item
calibrated parameters.

Spec section 7.8 (the question pool contract) and section 6.2.1 (fields the
pool reads from `questions`) define this component. The pool is consulted
each time the engine picks a skill and needs to convert that into a specific
question to hand the client. It applies the spec section 7.8 filters
(active, no-repeat, skill match, purpose in scope, grade-appropriate,
tenant-scoped) and returns one question.

The return type is `QuestionPick`, a frozen dataclass:

  question_id     - the x_id to send to the client (required)
  slip_override   - per-item calibrated slip (optional, from questions.slip_i)
  guess_override  - per-item calibrated guess (optional, from questions.guess_i)

When the per-item overrides are present, the engine uses them in the Bayes
update for that question (spec section 7.7). When absent, the engine falls
back to the uniform defaults in engine_config.yaml.

This module ships two implementations:

  StubQuestionPool   - generates deterministic placeholder IDs (e.g.
                       `stub::Tables 1 to 9::0001`) and never sets the
                       overrides. Sufficient for unit tests, the CLI's
                       simulate-session command, and any path that does not
                       need real question content.

  CsvQuestionPool    - the interim production pool. Reads
                       `question_parameters.csv` (the calibration output) and
                       returns a real question id (`q_x_id`) plus that
                       question's calibrated slip and guess. Selection uses a
                       discrimination-window rule (see CsvQuestionPool for the
                       definition). This is the production default until a
                       live `questions`-collection-backed pool replaces it.

Production deployments use `CsvQuestionPool`. The real implementation raises
`NoQuestionForSkillError` if no question is available for the requested skill
(spec section 7.8 failure modes).
"""

import csv
import random
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from engine.api.errors import NoQuestionForSkillError
from engine.misconception import MISCONCEPTION_SET
from engine.observability.logging import get_logger
from engine.session import Session


@dataclass(frozen=True)
class QuestionPick:
    """Result of QuestionPool.pick_question_for_skill (spec section 7.8).

    `slip_override` and `guess_override` are optional per-item calibrated
    parameters from the `questions` collection (fields `slip_i` and
    `guess_i`; see spec section 6.2.1). When present, the engine uses them
    in the Bayes update for this question, falling back to the uniform
    defaults from engine_config.yaml when absent.

    Pool implementations are encouraged to suppress the overrides (return
    None for both) when the calibration is unreliable, e.g. when the
    underlying `n_observations_used` for the item is below a threshold.

    `misconceptions` carries the chosen item's 11 misconception tags (tag name
    -> 0/1) when the pool was built with a per-tenant lookup that includes them
    (spec section 7.3). It is None in legacy mode (no lookup). The engine does
    not act on these yet; they are made available for the future
    misconception-coverage selection layer.
    """

    question_id: str
    slip_override: Optional[float] = None
    guess_override: Optional[float] = None
    misconceptions: Optional[Dict[str, int]] = None


class QuestionPool(ABC):
    """Resolves a chosen skill to a specific question to ask the client.

    Implementations must apply the spec section 7.8 filters (active,
    no-repeat-within-session, skill match, purpose in scope,
    grade-appropriate, optional tenant scope) and return one question.
    """

    @abstractmethod
    def pick_question_for_skill(
        self,
        *,
        skill: str,
        session: Session,
        grade: int,
        tenant_id: str,
    ) -> QuestionPick:
        """Return a question for the given skill in the given session context.

        The pool MUST avoid returning a question_id that already appears in
        the session's question_history (idempotency contract, spec section
        8.3). The pool MUST raise `NoQuestionForSkillError` if no question
        is available after filtering.
        """


class StubQuestionPool(QuestionPool):
    """Deterministic placeholder. NOT FOR PRODUCTION.

    Generates IDs of the form `stub::{skill}::{n:04d}` where n is the count
    of questions already asked on this skill plus one. The stub never sets
    per-item overrides - all overrides come back as None, which keeps the
    Bayes update on the uniform config defaults.
    """

    def pick_question_for_skill(
        self,
        *,
        skill: str,
        session: Session,
        grade: int,
        tenant_id: str,
    ) -> QuestionPick:
        already_asked = sum(
            1 for entry in session.question_history if entry.skill_id == skill
        )
        question_id = f"stub::{skill}::{already_asked + 1:04d}"
        return QuestionPick(
            question_id=question_id,
            slip_override=None,
            guess_override=None,
        )


def get_default_question_pool() -> QuestionPool:
    """Factory for the default question pool. Returns StubQuestionPool for v1."""
    return StubQuestionPool()


# Columns CsvQuestionPool requires in question_parameters.csv. q_type is read
# if present (carried for diagnostics) but is not required for selection.
_REQUIRED_COLUMNS = (
    "item",
    "q_x_id",
    "l2_5_skill",
    "grade",
    "slip",
    "guess",
    "discrimination",
)

# Sentinel grade key for the grade-independent ("all") parameter row.
_ALL_GRADE = "all"


@dataclass(frozen=True)
class _ParamRow:
    """One resolved parameter row for an item at a specific grade (or 'all')."""

    q_x_id: str
    slip: float
    guess: float
    discrimination: float


class CsvQuestionPool(QuestionPool):
    """Interim production pool backed by question_parameters.csv.

    Reads the calibration output once at construction and, for any skill the
    routing layer picks, returns a real question id (`q_x_id`) plus that
    question's calibrated `slip` and `guess`. Selection uses a
    discrimination-window rule (spec section 5).

    Terms (defined on first use):
      item            - the canonical question key, a content string like
                        "Addition|1D+1D sum upto 9|Fib||3|4". All selection,
                        deduplication, and no-repeat logic keys on `item`,
                        never on `q_x_id`, so the pool stays correct if a
                        future file maps several `q_x_id`s to one `item`.
      q_x_id          - the concrete question id the client loads content by.
      discrimination  - how sharply a question separates learners who know the
                        skill from those who do not; equals 1 - slip - guess.
                        Higher is sharper.

    Selection algorithm (per pick):
      1. Enumerate the distinct `item`s for the chosen skill.
      2. Drop items already asked this session (mapping each historical
         question_id back to its item).
      3. Resolve each surviving item's parameters at the learner's grade: use
         the grade-specific row if one exists, else the item's `all` row.
      4. Keep an item only if its discrimination is both within `window_width`
         of the best discrimination among candidates AND at or above
         `discrimination_floor`.
      5. Pick one: uniformly at random (default), or, in "deterministic" mode,
         the highest discrimination with the lexicographically smallest item
         as tiebreak (the hook the future offline-tree generator will use).

    Construction parameters:
      csv_path             - path to question_parameters.csv.
      window_width         - the 0.10 window in step 4. Tunable without code.
      discrimination_floor - the 0.50 absolute floor in step 4.
      selection            - "random" (online default) or "deterministic".
      seed                 - optional int. When set, the random pick is
                             reproducible (used by tests). Unset in production
                             so picks stay varied. One generator is shared by
                             the whole pool; that is enough for test
                             reproducibility and we do not need per-session
                             determinism.
      expected_skills      - optional iterable of the engine's configured scope
                             skills. When provided, the pool logs a loud
                             WARNING at construction for each scope skill that
                             has zero questions in the CSV (mirrors the
                             priors-coverage warning).
    """

    def __init__(
        self,
        csv_path: str,
        *,
        window_width: float = 0.10,
        discrimination_floor: float = 0.50,
        selection: str = "random",
        seed: Optional[int] = None,
        expected_skills: Optional[Iterable[str]] = None,
        lookup_path: Optional[str] = None,
        retired_path: Optional[str] = None,
        misconception_target: int = 2,
    ) -> None:
        if selection not in ("random", "deterministic"):
            raise ValueError(
                f"selection must be 'random' or 'deterministic', got {selection!r}"
            )
        self._window_width = window_width
        self._discrimination_floor = discrimination_floor
        self._selection = selection
        # Opportunistic-coverage floor (spec section 5.1). A misconception is
        # "unmet" while its asked count is below this; <= 0 disables the
        # opportunistic preference (the window pick then runs unchanged).
        self._misconception_target = misconception_target
        self._rng = random.Random(seed)
        self._log = get_logger("engine.question_pool")

        # skill -> set of its items
        self._skill_items: Dict[str, Set[str]] = defaultdict(set)
        # item -> {grade_str: _ParamRow}, where grade_str includes "all"
        self._item_rows: Dict[str, Dict[str, _ParamRow]] = defaultdict(dict)
        # q_x_id -> item, for the no-repeat rule (params ids, plus lookup ids below)
        self._qxid_to_item: Dict[str, str] = {}

        # Per-tenant resolution (populated only when a lookup is supplied).
        # (tenant, item) -> resolved question_x_id
        self._tenant_item_xid: Dict[Tuple[str, str], str] = {}
        # tenant -> set of items the tenant can serve (the availability filter)
        self._tenant_items: Dict[str, Set[str]] = defaultdict(set)
        # item -> {misconception_tag: 0/1}, carried from the lookup. Flags are
        # content-derived and tenant-invariant (verified: 0 of 651 multi-tenant
        # items disagree across tenants), so this is keyed by item. A load-time
        # consistency check warns if a future lookup ever violates that. Both the
        # QuestionPick field and misconceptions_for_item() read this one table.
        self._item_flags: Dict[str, Dict[str, int]] = {}
        self._has_lookup = False
        # Optional runtime retired-list (the build step already drops retired
        # rows from the lookup; this is defence-in-depth for a stale lookup).
        self._retired_items: Set[str] = set()
        self._retired_xids: Set[str] = set()

        self._load(csv_path)
        if retired_path is not None:
            self._load_retired(retired_path)
        if lookup_path is not None:
            self._load_lookup(lookup_path)

        if expected_skills is not None:
            self._warn_missing_skills(expected_skills)

    # --- loading -----------------------------------------------------------

    def _load(self, csv_path: str) -> None:
        path = Path(csv_path)
        if not path.exists():
            raise FileNotFoundError(f"question parameters file not found: {csv_path}")

        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            missing = [c for c in _REQUIRED_COLUMNS if c not in header]
            if missing:
                raise ValueError(
                    f"{csv_path}: question parameters file is missing required "
                    f"column(s): {', '.join(missing)}"
                )

            for line_no, row in enumerate(reader, start=2):
                item = row["item"]
                q_x_id = row["q_x_id"]
                skill = row["l2_5_skill"]
                grade_str = str(row["grade"]).strip()
                try:
                    param = _ParamRow(
                        q_x_id=q_x_id,
                        slip=float(row["slip"]),
                        guess=float(row["guess"]),
                        discrimination=float(row["discrimination"]),
                    )
                except (TypeError, ValueError) as e:
                    raise ValueError(
                        f"{csv_path}:{line_no} could not parse slip/guess/"
                        f"discrimination for item {item!r}: {e}"
                    ) from e

                self._skill_items[skill].add(item)

                # Defensive: if a (item, grade) pair appears more than once with
                # different q_x_ids (should not happen in a well-formed file),
                # keep the lexicographically smallest q_x_id as a stable
                # tiebreak (spec section 5 step 6).
                existing = self._item_rows[item].get(grade_str)
                if existing is None or param.q_x_id < existing.q_x_id:
                    self._item_rows[item][grade_str] = param

                # Reverse map. Same lexicographic tiebreak if a q_x_id somehow
                # maps to two items (also should not happen).
                prior_item = self._qxid_to_item.get(q_x_id)
                if prior_item is None or item < prior_item:
                    self._qxid_to_item[q_x_id] = item

    def _load_retired(self, retired_path: str) -> None:
        """Load the retired-questions CSV (canonical: retired_questions_v2.csv) -> retired item / question_x_id sets.

        Applied at enumeration as defence-in-depth. The build step already drops
        retired rows from the lookup, so this matters only if the lookup is
        staler than the retired list.
        """
        path = Path(retired_path)
        if not path.exists():
            raise FileNotFoundError(f"retired list file not found: {retired_path}")
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                scope = (row.get("scope") or "").strip()
                key = (row.get("key") or "").strip()
                if scope == "item":
                    self._retired_items.add(key)
                elif scope == "question_x_id":
                    self._retired_xids.add(key)

    def _load_lookup(self, lookup_path: str) -> None:
        """Load tenant_question_lookup.csv: the per-tenant (tenant, item) ->
        question_x_id resolution produced by the offline build step. Enables
        the tenant-availability filter and tenant-scoped id resolution.

        Columns: tenant, item, question_x_id, + misconception flags (the flags
        are carried by the build artifact but not acted on by selection yet,
        spec 7.3).
        """
        path = Path(lookup_path)
        if not path.exists():
            raise FileNotFoundError(f"tenant question lookup file not found: {lookup_path}")
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames or []
            required = ("tenant", "item", "question_x_id")
            missing = [c for c in required if c not in header]
            if missing:
                raise ValueError(
                    f"{lookup_path}: tenant lookup is missing required column(s): "
                    f"{', '.join(missing)}"
                )
            # Any columns beyond the three keys are the misconception flags
            # (the build step writes 11). Carried, not acted on (spec 7.3).
            flag_cols = [c for c in header if c not in required]
            for row in reader:
                tenant = row["tenant"]
                item = row["item"]
                q_x_id = row["question_x_id"]
                self._tenant_item_xid[(tenant, item)] = q_x_id
                self._tenant_items[tenant].add(item)
                if flag_cols:
                    flags = {c: int(row[c]) for c in flag_cols}
                    prior_flags = self._item_flags.get(item)
                    if prior_flags is not None and prior_flags != flags:
                        # Flags are expected to be tenant-invariant for an item.
                        # A disagreement means the lookup carries tenant-varying
                        # tags (e.g. content class differs by tenant); surface it
                        # rather than silently keeping one row's values.
                        self._log.warning(
                            f"question pool: misconception flags differ across "
                            f"tenants for item {item!r}; keeping first-seen values"
                        )
                    elif prior_flags is None:
                        self._item_flags[item] = flags
                # No-repeat must recognise the served (lookup) id too: a question
                # asked in a tenant session carries the lookup's q_x_id, which can
                # differ from the params q_x_id. Map it back to its item.
                prior = self._qxid_to_item.get(q_x_id)
                if prior is None or item < prior:
                    self._qxid_to_item[q_x_id] = item
        self._has_lookup = True

    def _warn_missing_skills(self, expected_skills: Iterable[str]) -> None:
        for skill in sorted(set(expected_skills)):
            if not self._skill_items.get(skill):
                self._log.warning(
                    f"question pool: scope skill has zero questions in the CSV: "
                    f"{skill!r}. Sessions that route to this skill will fail with "
                    f"NO_QUESTION_FOR_SKILL. This is a content-pool gap."
                )

    # --- selection ---------------------------------------------------------

    def _resolve_row(self, item: str, grade: int) -> Optional[_ParamRow]:
        """Resolve an item's parameter row at the learner's grade.

        Grade-specific row if one exists, else the item's 'all' row, else None
        (which on well-formed data does not happen because every item has an
        'all' row).
        """
        rows = self._item_rows.get(item, {})
        return rows.get(str(grade)) or rows.get(_ALL_GRADE)

    def _answered_items(self, session) -> Set[str]:
        """The set of items already answered anywhere in this session, in item
        space. This is the single source of the no-repeat contract (mixed-mode
        v11 section 7): it reads the ENTIRE ``question_history`` regardless of
        ``routing_mode``, so online and ``offline_replay`` answers are treated
        identically, and it maps each ``question_x_id`` to its ``item`` (online
        and offline can serve different display variants of the same item, so
        the check must be in item space). An entry whose id is not in the pool
        maps to ``None`` and is dropped. Do NOT filter this by routing_mode or
        segment - that would let a mixed session re-ask an item answered in
        another segment.
        """
        items = {
            self._qxid_to_item.get(entry.question_id)
            for entry in session.question_history
        }
        items.discard(None)
        return items

    @staticmethod
    def _excluded_xids(session) -> "Set[str]":
        """question_x_ids the session must not be offered (Deactivation Failsafe
        mechanisms 1-2): the persistent switched-off set plus the transient
        declined set. Both are variant-level and combine with the retired and
        no-repeat exclusions in the same candidate filter. Governs future
        offering only; never affects the scoring of an answer already given."""
        off = getattr(session, "switched_off_question_x_ids", None) or set()
        declined = getattr(session, "declined_question_x_ids", None) or set()
        if not off and not declined:
            return frozenset()
        return set(off) | set(declined)

    def pick_question_for_skill(
        self,
        *,
        skill: str,
        session: Session,
        grade: int,
        tenant_id: str,
    ) -> QuestionPick:
        # Step 1: enumerate the skill's items.
        items = self._skill_items.get(skill)
        if not items:
            raise NoQuestionForSkillError(
                f"no questions in the pool for skill {skill!r}"
            )

        # Step 2 (retired-list filter) and Step 3 (tenant-availability filter),
        # tenant-aware mode only: applied together at ENUMERATION, before the
        # window, so the window never picks an item the tenant cannot serve (or a
        # retired one) and then fails at resolution. NO_QUESTION_FOR_SKILL then
        # fires only on the genuine coverage gap (no tenant-available, non-retired
        # question exists for the skill). In legacy mode (no lookup) both filters
        # are skipped and behaviour is unchanged.
        tenant_filtered = list(items)
        excluded_xids = self._excluded_xids(session)          # switched-off + declined
        if self._has_lookup:
            available = self._tenant_items.get(tenant_id, set())
            tenant_filtered = [
                i for i in tenant_filtered
                if i in available                                  # tenant can serve it
                and i not in self._retired_items                   # not item-retired
                and self._tenant_item_xid.get((tenant_id, i)) not in self._retired_xids
                and self._tenant_item_xid.get((tenant_id, i)) not in excluded_xids  # switched-off/declined
            ]
            if not tenant_filtered:
                raise NoQuestionForSkillError(
                    f"no tenant-available question for skill {skill!r} in tenant "
                    f"{tenant_id!r} (after retired and availability filters)"
                )

        # Step 4: no-repeat (item space, whole history - see _answered_items).
        asked_items = self._answered_items(session)
        candidates = [i for i in tenant_filtered if i not in asked_items]
        if not candidates:
            raise NoQuestionForSkillError(
                f"all questions for skill {skill!r} already asked this session"
            )

        # Step 5: resolve each candidate's parameters at the learner's grade.
        resolved: List[Tuple[str, _ParamRow]] = []
        for item in candidates:
            row = self._resolve_row(item, grade)
            if row is None:
                continue
            if not self._has_lookup and row.q_x_id in excluded_xids:
                continue                        # legacy-mode switched-off / declined
            resolved.append((item, row))
        if not resolved:
            # No candidate has a row for this grade or an 'all' row. On the
            # current data this cannot happen (every item has an 'all' row);
            # raising is the correct fail-loud behavior if a future file breaks
            # that guarantee.
            raise NoQuestionForSkillError(
                f"no grade-resolvable question for skill {skill!r} at grade {grade}"
            )

        # Step 6: discrimination window. best always clears both gates, so the
        # windowed list is never empty.
        best = max(row.discrimination for _, row in resolved)
        windowed = [
            (item, row)
            for item, row in resolved
            if row.discrimination >= best - self._window_width
            and row.discrimination >= self._discrimination_floor
        ]
        # Stable ordering by item so a fixed seed yields a reproducible pick.
        windowed.sort(key=lambda pair: pair[0])

        # Step 7: opportunistic misconception coverage (spec section 5.1).
        # Engages ONLY when at least one in-window candidate would advance a
        # still-unmet, applicable misconception. When it does not engage (no
        # applicable misconceptions, all already at target, or no in-window
        # candidate carries an unmet tag), `candidates` stays the full window and
        # the final pick below is byte-identical to the pre-coverage behaviour.
        # Coverage logic only NARROWS the set; the mode makes the final choice,
        # so production exposure spread is preserved and the offline tree stays
        # reproducible.
        candidates = windowed
        unmet = {
            m for m in session.misconception_applicable
            if session.misconception_asked.get(m, 0) < self._misconception_target
        }
        if unmet and self._item_flags:
            scored = [
                (
                    sum(
                        1 for m in unmet
                        if self._item_flags.get(item, {}).get(m, 0) == 1
                    ),
                    item,
                    row,
                )
                for item, row in windowed
            ]
            max_adv = max(adv for adv, _, _ in scored)
            if max_adv > 0:
                # greedy multi-tag: keep the candidates advancing the most unmet
                # misconceptions, then narrow to the sharpest among them.
                greedy = [(item, row) for adv, item, row in scored if adv == max_adv]
                candidates = self._narrow_to_sharpest(greedy)

        # Step 8: the existing mode-appropriate final pick, over `candidates`.
        chosen_item, chosen_row = self._final_pick(candidates)

        # Step 9: resolve the chosen item to a served question id plus its
        # calibrated slip / guess and tags (see _build_pick).
        return self._build_pick(chosen_item, chosen_row, tenant_id)

    # --- selection helpers (shared by the window pick and backfill) --------

    def _narrow_to_sharpest(
        self, candidates: List[Tuple[str, "_ParamRow"]]
    ) -> List[Tuple[str, "_ParamRow"]]:
        """Keep only the highest-discrimination candidates (exact max). Ties at
        the max fall through to the mode-appropriate final pick."""
        sharpest = max(row.discrimination for _, row in candidates)
        return [(item, row) for item, row in candidates if row.discrimination == sharpest]

    def _final_pick(
        self, candidates: List[Tuple[str, "_ParamRow"]]
    ) -> Tuple[str, "_ParamRow"]:
        """The mode-appropriate final choice over an already-narrowed set:
        deterministic = highest discrimination then lexicographically smallest
        item (offline tree); random = uniform among survivors (production
        exposure spread). Candidates are sorted by item first so a fixed seed
        gives a reproducible random pick."""
        ordered = sorted(candidates, key=lambda pair: pair[0])
        if self._selection == "deterministic":
            return min(ordered, key=lambda pair: (-pair[1].discrimination, pair[0]))
        return self._rng.choice(ordered)

    def _build_pick(
        self, item: str, row: "_ParamRow", tenant_id: str
    ) -> QuestionPick:
        """Resolve a chosen (item, row) to a QuestionPick: the served question
        id (tenant lookup's resolved question_x_id in tenant-aware mode, else the
        params q_x_id), the calibrated slip / guess, and the item's tags."""
        if self._has_lookup:
            q_x_id = self._tenant_item_xid.get((tenant_id, item))
            if q_x_id is None:
                raise NoQuestionForSkillError(
                    f"internal: chosen item {item!r} not resolvable in tenant "
                    f"{tenant_id!r} after the availability filter"
                )
        else:
            q_x_id = row.q_x_id
        return QuestionPick(
            question_id=q_x_id,
            slip_override=row.slip,
            guess_override=row.guess,
            misconceptions=self._item_flags.get(item),
        )

    # --- introspection (used by the app factory's coverage check) ----------

    @property
    def misconception_target(self) -> int:
        """The opportunistic/backfill floor (questions per applicable
        misconception). Read by the phase controller for the pass-A target."""
        return self._misconception_target

    def backfill_pick(
        self,
        *,
        tenant_id: str,
        grade: int,
        skills_in_scope: Iterable[str],
        session: Session,
        needed: Set[str],
    ) -> Optional[Tuple[str, QuestionPick]]:
        """Skill-agnostic coverage pick for the backfill phase (spec section 5.2).

        Among every eligible, not-yet-asked question across the in-scope skills,
        return the (skill, QuestionPick) for the one that advances the most of the
        caller-supplied `needed` misconceptions (greedy multi-tag, so one question
        can serve several), tiebroken by the same chain as the opportunistic pick:
        most advanced, then sharpest, then the mode-appropriate final pick. The
        skill is returned alongside the pick because backfill is skill-agnostic
        (the caller does not know which skill the chosen question belongs to) yet
        the response path needs it for the mastery update and the client. Returns
        None when no eligible, not-yet-asked question carries any `needed`
        misconception - the caller treats that as a shortfall for those.

        Unlike the opportunistic pick this does NOT restrict to the discrimination
        window or floor: backfill draws from a separate reserve and its job is
        coverage, so it considers any eligible carrier and lets the sharpest
        tiebreak prefer the better question. Eligibility otherwise matches
        selection exactly: tenant-available, not retired, grade-resolvable, and
        not already asked anywhere in the session. This is a pure selection
        primitive; the phase controller decides `needed`, how many to ask, and the
        reserve accounting.
        """
        if not needed or not self._item_flags:
            return None

        # No-repeat across the whole session (every phase, item space) - see
        # _answered_items.
        asked_items = self._answered_items(session)
        excluded_xids = self._excluded_xids(session)          # switched-off + declined
        available = (
            self._tenant_items.get(tenant_id, set()) if self._has_lookup else None
        )

        best_adv = 0
        winners: List[Tuple[str, str, "_ParamRow"]] = []  # (skill, item, row)
        seen: Set[str] = set()
        for skill in skills_in_scope:
            for item in self._skill_items.get(skill, ()):
                if item in seen:
                    continue
                seen.add(item)
                if item in asked_items:
                    continue
                if self._has_lookup:
                    if item not in available:
                        continue
                    if item in self._retired_items:
                        continue
                    if self._tenant_item_xid.get((tenant_id, item)) in self._retired_xids:
                        continue
                    if self._tenant_item_xid.get((tenant_id, item)) in excluded_xids:
                        continue                # switched-off / declined
                flags = self._item_flags.get(item)
                if not flags:
                    continue
                adv = sum(1 for m in needed if flags.get(m, 0) == 1)
                if adv == 0:
                    continue
                row = self._resolve_row(item, grade)
                if row is None:
                    continue
                if not self._has_lookup and row.q_x_id in excluded_xids:
                    continue                    # legacy-mode switched-off / declined
                if adv > best_adv:
                    best_adv = adv
                    winners = [(skill, item, row)]
                elif adv == best_adv:
                    winners.append((skill, item, row))

        if best_adv == 0 or not winners:
            return None
        item_to_skill = {item: skill for skill, item, _ in winners}
        candidates = self._narrow_to_sharpest([(item, row) for _, item, row in winners])
        chosen_item, chosen_row = self._final_pick(candidates)
        return item_to_skill[chosen_item], self._build_pick(chosen_item, chosen_row, tenant_id)

    def applicable_misconceptions(
        self, tenant_id: str, grade: int, skills_in_scope: Iterable[str]
    ) -> Set[str]:
        """The misconceptions the pool can actually serve a question for, to this
        learner, at session start (spec section 3.4: applicability == coverability).

        A misconception is applicable if at least one item carries its tag AND is
        reachable under the *exact same eligibility the pool uses at selection
        time*: the item is in an in-scope skill, tenant-available, not retired, and
        resolvable at the learner's grade by the grade-row-else-`all` rule. This
        deliberately mirrors the enumeration filters in `pick_question_for_skill`
        (steps 1-3 and 5) so the applicable set never disagrees with what the pool
        would serve. It is NOT a content-class predicate.

        Returns an empty set in legacy mode (no lookup / no tags). The result is
        intersected with the canonical misconception set so stray lookup columns,
        if any, cannot leak in.
        """
        applicable: Set[str] = set()
        if not self._item_flags:  # legacy mode, or a lookup without flag columns
            return applicable

        available = self._tenant_items.get(tenant_id, set()) if self._has_lookup else None
        for skill in skills_in_scope:
            for item in self._skill_items.get(skill, ()):  # step 1: in-scope skill
                if self._has_lookup:  # steps 2-3: retired + tenant-availability
                    if item not in available:
                        continue
                    if item in self._retired_items:
                        continue
                    if self._tenant_item_xid.get((tenant_id, item)) in self._retired_xids:
                        continue
                if self._resolve_row(item, grade) is None:  # step 5: grade-resolvable
                    continue
                flags = self._item_flags.get(item)
                if flags:
                    applicable.update(m for m, v in flags.items() if v == 1)
        return applicable & MISCONCEPTION_SET

    def misconceptions_for_item(self, item: str) -> Optional[Dict[str, int]]:
        """The 11 misconception tags (tag -> 0/1) for a content `item`, or None
        if unknown (legacy mode, or an item not in the lookup).

        A read-through into the same table the QuestionPick field uses. The
        QuestionPick field is the primary path (the chosen question carries its
        tags); this accessor lets a caller inspect tags for candidates it did
        NOT pick - useful for diagnostics, logging, or a future coverage-
        selection layer that runs outside the pool. Tags are tenant-invariant
        for an item, so no tenant argument is needed.
        """
        return self._item_flags.get(item)

    @property
    def available_skills(self) -> Set[str]:
        """The set of skills that have at least one question in the CSV."""
        return {skill for skill, items in self._skill_items.items() if items}
