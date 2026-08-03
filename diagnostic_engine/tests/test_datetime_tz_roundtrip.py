"""Regression: session datetimes survive a storage round-trip as tz-aware.

Field bug: with the MongoDB backend, a session persisted at session/start and
reloaded at session/response came back with a timezone-NAIVE started_at (PyMongo
returns BSON dates naive unless the client is tz_aware), while ended_at was set
fresh and tz-aware. Completing the session then did
`(ended_at - started_at).total_seconds()` -> "can't subtract offset-naive and
offset-aware datetimes". The in-memory storage used elsewhere in the suite
deepcopies the Session, preserving tzinfo, so it never reproduced this.

These tests exercise the serialization boundary directly (simulating the naive
read), so they guard the fix regardless of whether the driver/mongomock mimics
real MongoDB's behaviour.
"""
from datetime import datetime, timezone

from engine.session import SessionStatus
from engine.storage.documents import doc_to_session, session_to_doc
from tests.test_storage import make_session


def _as_naive(doc):
    """Simulate a real MongoDB read with a non-tz_aware client: BSON dates come
    back timezone-naive (UTC wall-clock, tzinfo dropped)."""
    for k in ("started_at", "ended_at"):
        if doc.get(k) is not None and doc[k].tzinfo is not None:
            doc[k] = doc[k].replace(tzinfo=None)
    for e in doc.get("question_history", []):
        if e.get("asked_at") is not None and e["asked_at"].tzinfo is not None:
            e["asked_at"] = e["asked_at"].replace(tzinfo=None)
    return doc


def test_doc_to_session_reattaches_utc_to_naive_datetimes():
    s = make_session(status=SessionStatus.COMPLETE)
    s.ended_at = datetime(2026, 5, 26, 12, 3, 0, tzinfo=timezone.utc)   # 3 min after start
    loaded = doc_to_session(_as_naive(session_to_doc(s)))
    # All reloaded datetimes are tz-aware again.
    assert loaded.started_at.tzinfo is not None
    assert loaded.ended_at.tzinfo is not None
    assert loaded.question_history[0].asked_at.tzinfo is not None
    # The failing subtraction now works and is correct (aware - aware).
    assert (loaded.ended_at - loaded.started_at).total_seconds() == 180.0


def test_completion_duration_after_naive_started_at():
    """The exact field path: started_at reloaded (was naive) minus a freshly-set
    aware ended_at must not raise."""
    s = make_session(status=SessionStatus.ACTIVE)
    loaded = doc_to_session(_as_naive(session_to_doc(s)))   # started_at back from storage
    fresh_ended = datetime.now(timezone.utc)                # set in-process at completion
    assert (fresh_ended - loaded.started_at).total_seconds() >= 0
