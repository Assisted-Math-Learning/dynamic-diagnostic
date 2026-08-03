"""In-process Stage B integration (v9).

After a session is finalized and verdicts computed, classify the learner's
responses and merge the misconception layer into the learner state, in process.
This is the `aml_stageb.build_learning_state` call, not the live-service triggers.

The raw learner response is NOT stored on the session (only `is_correct`), so it
is an injected dependency here: `raw_response_of(question_id) -> str`. In
production that source is the response-fetch endpoint (spec 8.4, engineering-team
scope); in tests the harness supplies it. Question metadata (operation, n1, n2,
the division remainder flag, q_type) is recovered from the question's `item`
content key via the pool's `_qxid_to_item`.
"""
import os
import sys

# The classifier package uses flat imports (import aml_engine, aml_classify, ...),
# so its directory must be on sys.path.
_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "stage_b_classifier")
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

import aml_engine as E          # noqa: E402
import aml_stageb as SB         # noqa: E402

DEFAULT_TABLE_DIR = os.path.join(_PKG, "tables")


def parse_item(item):
    """Guarded positional parse of the `item` content key.

    item = L1 | L2.5 | q_type | q_text | n1 | n2 [| response_includes_remainder]

    Safe today only because q_text is empty for every Fib item, so the key has
    no embedded '|'. Make that dependency loud: require exactly 6 fields
    (non-division) or 7 (division), integer operands, and a True/False seventh
    field. Raise on anything else so a future q_text-bearing or malformed item
    fails fast instead of mis-parsing.
    """
    parts = item.split("|")
    op = parts[0]
    is_div = op == "Division"
    expected = 7 if is_div else 6
    if len(parts) != expected:
        raise ValueError(f"item has {len(parts)} fields, expected {expected}: {item!r}")
    try:
        n1 = int(parts[4]); n2 = int(parts[5])
    except ValueError as e:
        raise ValueError(f"non-integer operand in item {item!r}: {e}")
    rir = None
    if is_div:
        if parts[6] not in ("True", "False"):
            raise ValueError(f"seventh field must be 'True'/'False', got {parts[6]!r} in {item!r}")
        # Pass a real bool, never the text. bool('False') is True in Python.
        rir = (parts[6] == "True")
    return {"operation": op, "skill_id": parts[1], "q_type": parts[2],
            "n1": n1, "n2": n2, "response_includes_remainder": rir}


def build_responses_payload(session, pool, raw_response_of=None):
    """Build the Stage B responses payload from a finalized session.

    `raw_response_of(question_id) -> str | None` supplies the learner's raw
    typed answer. When not injected (the default), it reads the raw responses
    persisted on the session's question_history (populated from the response
    request's optional raw_response field, spec section 8.4). q_type is taken
    from the item, so Mcq / Number-Sense questions pass through and Stage B
    drops them (it classifies only Fib)."""
    if raw_response_of is None:
        # Real source: the raw answers persisted per question on the session.
        _persisted = {e.question_id: e.raw_response for e in session.question_history}
        raw_response_of = _persisted.get
    items = []
    qxid_to_item = pool._qxid_to_item
    for entry in session.question_history:
        qid = entry.question_id
        item = qxid_to_item.get(qid)
        if item is None:
            # No content key for this served id; record nothing here, the merge
            # treats the skill as untested unless other questions cover it.
            continue
        meta = parse_item(item)
        rec = {"question_id": qid, "skill_id": entry.skill_id,
               "operation": meta["operation"], "n1": meta["n1"], "n2": meta["n2"],
               "response": raw_response_of(qid), "q_type": meta["q_type"]}
        if meta["operation"] == "Division":
            rec["response_includes_remainder"] = meta["response_includes_remainder"]  # real bool
        items.append(rec)
    return {"learner_id": session.learner_id, "learner_grade": session.grade, "items": items}


def run_stage_b(session, verdicts, pool, raw_response_of=None, *, table_dir=None,
                tenant=None, engine_version=None, calibration_version=None,
                low_support_k=2):
    """End-to-end in-process Stage B: verdicts -> mastery, session -> responses,
    classify + merge. Returns the merged learning-state dict to store on the
    learner state."""
    mastery = SB.mastery_from_verdicts(verdicts, session.learner_id, session.grade)
    responses = build_responses_payload(session, pool, raw_response_of)
    meta = {
        "tenant": tenant or getattr(session, "tenant_id", None),
        "engine_version": engine_version or getattr(session, "engine_version", None),
        "calibration_version": calibration_version,
        "diagnostic_session": {
            "session_id": getattr(session, "sub_session_id", None),
            "mode": "online",
            "completed_utc": None,
        },
    }
    return SB.build_learning_state(responses, mastery, meta,
                                   table_dir=table_dir or DEFAULT_TABLE_DIR,
                                   low_support_k=low_support_k)
