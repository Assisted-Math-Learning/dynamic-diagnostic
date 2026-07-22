"""
Cleanup: back-fill verdicts for completed sessions whose verdict write
crashed before completing (spec section 8.4 partial-write recovery).

The intended deployment is a Kubernetes CronJob that runs `python -m
engine.cli cleanup` every few minutes against the same MongoDB the engine
writes to. The CronJob is independent of the engine pods; it reads the
engine config and lattice from disk (mounted via the same ConfigMap as the
engine).

Out of scope:
  - Sessions in ABANDONED status (intentional termination; not currently
    back-filled by the engine; would need a separate design call).
  - Sessions stuck ACTIVE past their TTL (no expiry policy implemented in
    v1; deferred).
  - Pushing Prometheus metrics from the standalone CLI (the existing
    `cleanup_job_*` counters live on app.state.metrics, which is per
    FastAPI app and not reachable from a standalone CLI run). The CLI
    emits a structured log line with the counts instead. If we later
    decide we need metric exports from the CronJob, the cleanest path
    is a Prometheus Pushgateway.
"""

from dataclasses import dataclass
from typing import Optional

from engine.config import EngineConfig
from engine.lattice import LatticeIndex
from engine.observability.logging import get_logger
from engine.observability.metrics import EngineMetrics
from engine.session import compute_verdicts
from engine.storage.interface import StorageBackend


@dataclass(frozen=True)
class CleanupResult:
    """Summary of one cleanup run.

    sessions_examined: total sessions returned by the storage query.
    sessions_recovered: of those, how many got verdicts persisted successfully.
    sessions_failed: of those, how many raised an error during recovery.
    """

    sessions_examined: int
    sessions_recovered: int
    sessions_failed: int

    @property
    def all_successful(self) -> bool:
        return self.sessions_failed == 0


def run_cleanup(
    *,
    storage: StorageBackend,
    config: EngineConfig,
    lattice_index: LatticeIndex,
    limit: int = 100,
    metrics: Optional[EngineMetrics] = None,
) -> CleanupResult:
    """One pass: find complete sessions without verdicts, compute and persist.

    Each session is processed independently; a single failure does not stop
    the rest. Per-session failures are logged at ERROR with the
    sub_session_id; the function returns a summary CleanupResult instead
    of raising.

    Idempotent: if a recovered session is somehow returned again on the
    next run (race window), `storage.save_verdicts` is idempotent by
    contract (replace-strategy on sub_session_id), so a second write is
    safe.

    Metrics (spec section 9.1): when an EngineMetrics is supplied, this
    increments `cleanup_job_runs_total{outcome}` once per run (outcome is
    "success" if every examined session recovered, "error" if any failed)
    and `cleanup_job_recovered_sessions_total` by the recovered count. A
    one-shot CLI process cannot be scraped directly, so the CLI pushes the
    registry to a Prometheus Pushgateway when one is configured; see
    engine.cli.cmd_cleanup.
    """
    log = get_logger("engine.cleanup")
    sessions = storage.find_complete_sessions_without_verdicts(limit=limit)

    log.info(f"cleanup: examining {len(sessions)} session(s) for partial-write recovery")

    recovered = 0
    failed = 0
    for session in sessions:
        try:
            params = config.get_engine_params(
                grade=session.grade,
                lattice_index=lattice_index,
            )
            verdicts = compute_verdicts(session, params=params)
            storage.save_verdicts(session, verdicts)
            recovered += 1
            log.info(
                f"cleanup: recovered verdicts for sub_session_id={session.sub_session_id} "
                f"({len(verdicts)} verdicts written)"
            )
        except Exception as e:
            failed += 1
            log.error(
                f"cleanup: failed to recover sub_session_id={session.sub_session_id}: "
                f"{type(e).__name__}: {e}"
            )

    result = CleanupResult(
        sessions_examined=len(sessions),
        sessions_recovered=recovered,
        sessions_failed=failed,
    )

    if metrics is not None:
        outcome = "success" if result.all_successful else "error"
        metrics.cleanup_job_runs_total.labels(outcome=outcome).inc()
        if recovered:
            metrics.cleanup_job_recovered_sessions_total.inc(recovered)

    log.info(
        f"cleanup: done. examined={result.sessions_examined} "
        f"recovered={result.sessions_recovered} failed={result.sessions_failed}"
    )
    return result
