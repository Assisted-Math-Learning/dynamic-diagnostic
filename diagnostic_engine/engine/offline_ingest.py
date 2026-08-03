"""Offline-batch ingest (mixed-mode v11 section 9).

Folds a completed offline segment back into a session's ONE unified history and
recomputes all replay-derived state by a full chronological replay through the
promoted history scorer (engine.history_scorer.score_history) - not an
incremental per-item apply. This is the "thin wrapper" the spec describes: it
appends the batch, rebuilds state by replaying the whole history, and leaves the
next-question selection to the caller.

No new scoring or selection logic lives here.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional

from engine.api.errors import OfflineBatchTooLargeError, ResponseConflictError
from engine.history_scorer import full_params, score_history
from engine.routing import Purpose
from engine.session import QuestionHistoryEntry, RoutingMode, SessionStatus


@dataclass
class OfflineAnswer:
    """One learner answer from an offline segment (spec section 9 request body)."""
    question_x_id: str
    skill_id: str
    is_correct: bool
    raw_response: Optional[str]
    asked_at: object            # datetime; reuses the existing history-entry field


@dataclass
class IngestResult:
    session: object
    dedup_count: int = 0
    anchor_not_found: bool = False
    skipped_qids: List[str] = field(default_factory=list)
    over_budget: bool = False
    accepted_count: int = 0
    idempotent_noops: int = 0


def _resolve(pool, qid: str, grade: int):
    """Re-derive (skill, slip, guess, tags) for a question_x_id from the pool
    (the history does not store them). Returns None when the id has no
    calibration in the pool (retired-and-hard-deleted or corrupt): such an entry
    is skipped from the scoring replay (spec section 9, step 3)."""
    item = pool._qxid_to_item.get(qid)
    if item is None:
        return None
    row = pool._resolve_row(item, grade)
    if row is None:
        return None
    skill = item.split("|")[1]
    tags = pool.misconceptions_for_item(item) or {}
    return skill, row.slip, row.guess, dict(tags), item


def _rec_from_entry(entry) -> Dict:
    return {
        "question_id": entry.question_id,
        "skill_id": entry.skill_id,
        "is_correct": entry.is_correct,
        "raw_response": entry.raw_response,
        "asked_at": entry.asked_at,
        "routing_mode": entry.routing_mode,
    }


def apply_offline_batch(
    session,
    *,
    resume_anchor: Optional[str],
    entries: List[OfflineAnswer],
    tree_id: Optional[str],
    tree_version: Optional[int],
    cfg,
    lattice,
    pool,
    grade: int,
    tenant: str,
) -> IngestResult:
    """Append an offline batch to the session and recompute by full replay.

    Returns an IngestResult carrying the rebuilt session (posteriors, ledger,
    direct-obs, reserve baseline from the replay; unified history, per-operation
    counts, and routing-mode counts including any skipped entry) plus the flags
    the route surfaces to monitoring. Does NOT select the next question.
    """
    params = full_params(cfg, lattice, grade)
    grade_budget = params.routing_config.total_budget
    result = IngestResult(session=session)

    # Corruption/abuse guard only (decision 2): reject an implausibly large batch.
    if len(entries) > 2 * grade_budget:
        raise OfflineBatchTooLargeError(
            f"offline batch of {len(entries)} answers exceeds twice the grade "
            f"budget ({grade_budget}); rejecting as implausible"
        )

    existing = [_rec_from_entry(e) for e in session.question_history]
    existing_by_qid = {r["question_id"]: r for r in existing}

    # --- Idempotency on question_x_id, full history (spec section 9, step 2). ---
    # NOTE (within-batch duplicates): idempotency and conflict are checked only
    # against the EXISTING history, not within the incoming batch. If a single
    # batch contained the same question_x_id twice with conflicting is_correct,
    # the pair is not raised as RESPONSE_CONFLICT here - both survive this step
    # and the later keep-earliest item de-dup silently keeps the first. A
    # well-behaved device never emits the same question_x_id twice in one batch,
    # so this is left as keep-earliest rather than a hard error.
    surviving_batch: List[Dict] = []
    for a in entries:
        prior = existing_by_qid.get(a.question_x_id)
        if prior is not None:
            if bool(prior["is_correct"]) == bool(a.is_correct):
                result.idempotent_noops += 1        # duplicate answer -> no-op
                continue
            raise ResponseConflictError(
                f"offline answer for question_x_id '{a.question_x_id}' conflicts "
                f"with the recorded answer (is_correct differs)"
            )
        surviving_batch.append({
            "question_id": a.question_x_id,
            "skill_id": a.skill_id,
            "is_correct": bool(a.is_correct),
            "raw_response": a.raw_response,
            "asked_at": a.asked_at,
            "routing_mode": RoutingMode.OFFLINE_REPLAY,
        })

    # --- Place by resume_anchor (or tail-append + flag). Order block by asked_at.
    surviving_batch.sort(key=lambda r: r["asked_at"])
    anchor_idx = None
    if resume_anchor is not None:
        for i, r in enumerate(existing):
            if r["question_id"] == resume_anchor:
                anchor_idx = i
                break
    if anchor_idx is None:
        result.anchor_not_found = resume_anchor is not None and len(surviving_batch) > 0
        merged = existing + surviving_batch                 # tail
    else:
        merged = existing[:anchor_idx + 1] + surviving_batch + existing[anchor_idx + 1:]

    # --- De-dup by item, keeping the earliest occurrence (spec section 9, step 2).
    seen_items = set()
    deduped: List[Dict] = []
    for r in merged:
        item = pool._qxid_to_item.get(r["question_id"])
        if item is not None and item in seen_items:
            result.dedup_count += 1                         # drop the later copy
            continue
        if item is not None:
            seen_items.add(item)
        deduped.append(r)

    # --- Build the scoring steps (scoreable records only), in authoritative order.
    resolved: List[Optional[tuple]] = []
    steps = []
    for r in deduped:
        info = _resolve(pool, r["question_id"], grade)
        resolved.append(info)
        if info is None:
            result.skipped_qids.append(r["question_id"])
            continue
        skill, slip, guess, tags, _item = info
        steps.append((r["question_id"], skill, r["is_correct"], slip, guess, tags))

    # --- Recompute all replay-derived state by full replay (scratch session). ---
    _skills, _sigs, scratch = score_history(
        steps, cfg, lattice, pool, grade, tenant, return_session=True)

    # --- Rebuild the authoritative unified history. The scratch history is in the
    #     same order as `steps` (scoreable records); overlay routing_mode /
    #     raw_response / asked_at / skill onto each, and construct entries for any
    #     skipped record (audit-only fields; flagged). Renumber sequence.
    scored_iter = iter(scratch.question_history)
    unified: List[QuestionHistoryEntry] = []
    for seq, (r, info) in enumerate(zip(deduped, resolved), start=1):
        if info is None:
            unified.append(QuestionHistoryEntry(
                sequence=seq, question_id=r["question_id"], skill_id=r["skill_id"],
                is_correct=r["is_correct"], asked_at=r["asked_at"],
                posterior_before=0.5, posterior_after=0.5,
                purpose=Purpose.INFO_GAIN, routing_mode=r["routing_mode"],
                raw_response=r["raw_response"],
            ))
            continue
        skill = info[0]
        base = next(scored_iter)                            # replay-scored entry
        unified.append(replace(
            base, sequence=seq, skill_id=skill, asked_at=r["asked_at"],
            routing_mode=r["routing_mode"], raw_response=r["raw_response"],
        ))

    # --- Turn the scratch session into the real session (its replay-derived
    #     state is correct: posteriors, ledger, direct-obs, reserve baseline). ---
    scratch.sub_session_id = session.sub_session_id
    scratch.learner_id = session.learner_id
    scratch.tenant_id = session.tenant_id
    scratch.class_id = session.class_id
    scratch.grade = session.grade
    scratch.engine_version = session.engine_version
    scratch.started_at = session.started_at
    scratch.status = SessionStatus.ACTIVE
    # scratch.misconception_applicable was set correctly by score_history from the
    # pool (same tenant/grade/skills as the real session); keep it.
    # Carry the deactivation-failsafe sets across the full-replay rebuild so a
    # switched-off list (and any transient decline) sent on the ingest call
    # survives (Deactivation Failsafe mechanisms 1-2).
    scratch.switched_off_question_x_ids = set(
        getattr(session, "switched_off_question_x_ids", None) or set())
    scratch.declined_question_x_ids = set(
        getattr(session, "declined_question_x_ids", None) or set())
    scratch.tree_id_used = tree_id
    scratch.tree_version_used = tree_version
    scratch.question_history = unified

    # Per-operation and routing-mode counts come from the FULL history (all
    # entries, incl. skipped), so budget and no-repeat agree (spec section 9).
    per_op: Dict[str, int] = {}
    rm_counts: Dict[RoutingMode, int] = {RoutingMode.ONLINE: 0, RoutingMode.OFFLINE_REPLAY: 0}
    for e in unified:
        op = params.skill_to_operation.get(e.skill_id)
        if op is not None:
            per_op[op] = per_op.get(op, 0) + 1
        rm_counts[e.routing_mode] = rm_counts.get(e.routing_mode, 0) + 1
    scratch.questions_per_operation = per_op
    scratch.routing_mode_counts = rm_counts

    result.session = scratch
    result.accepted_count = len(surviving_batch)
    result.over_budget = len(unified) > grade_budget
    return result
