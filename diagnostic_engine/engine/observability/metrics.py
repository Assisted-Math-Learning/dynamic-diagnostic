"""
Prometheus metrics for the dynamic diagnostic engine.

Implements the 12 business metrics from spec section 9.1. Metrics are
created inside a `register_metrics(registry)` factory so tests can use a
fresh CollectorRegistry per test and avoid the duplicate-registration
errors that the default global registry causes when the module is
re-imported.

Usage:

    from prometheus_client import CollectorRegistry
    from engine.observability.metrics import register_metrics

    registry = CollectorRegistry()
    metrics = register_metrics(registry)
    metrics.sessions_started_total.labels(tenant_id="t1", grade="3").inc()
"""

from dataclasses import dataclass
from typing import Optional

from prometheus_client import CollectorRegistry, Counter, Histogram


@dataclass(frozen=True)
class EngineMetrics:
    """Container for the 12 Prometheus metrics."""

    sessions_started_total: Counter
    sessions_completed_total: Counter
    session_duration_seconds: Histogram
    questions_per_session: Histogram
    verdict_total: Counter
    routing_mode_questions_total: Counter
    offline_sync_events_total: Counter
    api_request_duration_seconds: Histogram
    api_errors_total: Counter
    response_conflicts_total: Counter
    cleanup_job_runs_total: Counter
    cleanup_job_recovered_sessions_total: Counter


def register_metrics(registry: Optional[CollectorRegistry] = None) -> EngineMetrics:
    """Create and register the 12 Prometheus metrics.

    Args:
        registry: a CollectorRegistry to register metrics into. If None, uses
            the prometheus_client global default registry. Tests should always
            pass a fresh registry.

    Returns:
        EngineMetrics dataclass holding all metric objects.
    """
    kw = {"registry": registry} if registry is not None else {}

    return EngineMetrics(
        sessions_started_total=Counter(
            "diagnostic_sessions_started_total",
            "Total diagnostic sessions started.",
            labelnames=("tenant_id", "grade"),
            **kw,
        ),
        sessions_completed_total=Counter(
            "diagnostic_sessions_completed_total",
            "Sessions ended.",
            labelnames=("tenant_id", "grade", "end_reason"),
            **kw,
        ),
        session_duration_seconds=Histogram(
            "diagnostic_session_duration_seconds",
            "Time between session start and end.",
            labelnames=("tenant_id", "grade"),
            **kw,
        ),
        questions_per_session=Histogram(
            "diagnostic_questions_per_session",
            "Number of questions asked per completed session.",
            labelnames=("tenant_id", "grade"),
            buckets=(5, 10, 20, 30, 40, 50, 60, 70, 80, 100),
            **kw,
        ),
        verdict_total=Counter(
            "diagnostic_verdict_total",
            "Verdict counts per (skill, label).",
            labelnames=("tenant_id", "grade", "skill_id", "confidence_label"),
            **kw,
        ),
        routing_mode_questions_total=Counter(
            "diagnostic_routing_mode_questions_total",
            "Hybrid mode usage.",
            labelnames=("tenant_id", "mode"),
            **kw,
        ),
        offline_sync_events_total=Counter(
            "diagnostic_offline_sync_events_total",
            "Offline-batch replay events processed.",
            labelnames=("tenant_id", "outcome"),
            **kw,
        ),
        api_request_duration_seconds=Histogram(
            "diagnostic_api_request_duration_seconds",
            "Per-endpoint latency.",
            labelnames=("endpoint", "status"),
            **kw,
        ),
        api_errors_total=Counter(
            "diagnostic_api_errors_total",
            "API errors by code.",
            labelnames=("endpoint", "error_code"),
            **kw,
        ),
        response_conflicts_total=Counter(
            "diagnostic_response_conflicts_total",
            "Idempotency conflicts.",
            labelnames=("tenant_id",),
            **kw,
        ),
        cleanup_job_runs_total=Counter(
            "diagnostic_cleanup_job_runs_total",
            "Cleanup job invocations.",
            labelnames=("outcome",),
            **kw,
        ),
        cleanup_job_recovered_sessions_total=Counter(
            "diagnostic_cleanup_job_recovered_sessions_total",
            "Sessions where the cleanup job had to write missing verdicts.",
            **kw,
        ),
    )
