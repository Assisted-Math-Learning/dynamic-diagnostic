"""
FastAPI application for the dynamic diagnostic engine.

Two entry points:
  - create_app(...) is the testable factory. All dependencies are injected.
    Tests call it directly with in-memory storage, a test EngineConfig, and a
    custom tenant_tokens map.
  - create_app_from_env() is the production factory. It reads dependencies
    from environment variables (spec section 10.3).

Module-level `app` is constructed via create_app_from_env() at import time,
so `uvicorn engine.api.main:app` works without the --factory flag. If the
env is not configured (e.g. during a test run or CLI usage) the construction
fails and `app` stays None; that's fine because tests don't reference the
module-level `app`.

Two exception handlers translate raised errors into envelope-wrapped JSON:
  - EngineApiError: routes raise these directly; the handler reads .code,
    .message, .http_status and produces an error envelope.
  - RequestValidationError: raised by FastAPI when Pydantic request-body
    validation fails. Extra fields (extra='forbid') become PII_FIELD_PRESENT;
    grade-field errors become INVALID_GRADE; everything else is a generic 400.
"""

import json
import os
from typing import Dict, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from prometheus_client import CollectorRegistry

import engine
from engine.api.envelope import error_envelope
from engine.api.errors import EngineApiError, ErrorCode
from engine.api.middleware import RequestIdMiddleware
from engine.api.routes import flat_router, router
from engine.config import EngineConfig, check_priors_coverage, load_engine_config
from engine.lattice import LatticeIndex
from engine.observability.logging import configure_logging, get_logger
from engine.observability.metrics import register_metrics
from engine.offline_registry import OfflineTreeRegistry, default_artifact_dir
from engine.question_pool import CsvQuestionPool, QuestionPool, StubQuestionPool
from engine.storage import StorageBackend, get_storage_backend


# === Factory functions ======================================================


def create_app(
    *,
    config: EngineConfig,
    storage: StorageBackend,
    lattice_index: LatticeIndex,
    tenant_tokens: Dict[str, str],
    engine_version: str,
    question_pool: Optional[QuestionPool] = None,
    metrics_registry: Optional[CollectorRegistry] = None,
    offline_artifact_dir: Optional[str] = None,
    title: str = "AML Diagnostic Engine",
) -> FastAPI:
    """Create a FastAPI app with explicitly injected dependencies.

    This is the testable entry point. Tests build a config + in-memory storage
    + lattice + tenant_tokens map and call this directly.
    """
    app = FastAPI(title=title, docs_url="/docs", redoc_url=None)

    # Attach dependencies to app.state so routes can reach them via Request.
    app.state.config = config
    app.state.storage = storage
    app.state.lattice_index = lattice_index
    app.state.tenant_tokens = dict(tenant_tokens)
    app.state.engine_version = engine_version
    app.state.question_pool = question_pool or StubQuestionPool()

    # Offline decision-tree registry (B1). Loaded once from the artifact dir;
    # served by reference on session/start and by the offline-tree fetch
    # endpoint. Missing dir / no artifacts is graceful (empty registry ->
    # offline_tree is simply null). Repo-relative default, no /mnt dependency.
    app.state.offline_tree_registry = OfflineTreeRegistry(
        offline_artifact_dir or default_artifact_dir()
    )

    # Check whether any configured grade lacks cohort priors. Such grades
    # silently fall back to a default 0.5 prior for every skill - safe for
    # testing but a hidden behavior change in production. We log a WARN
    # here so the gap is visible in startup logs; we also stash the list on
    # app.state so /health can expose it. Fail-fast on missing priors is
    # the operator's choice via the STRICT_PRIORS_REQUIRED env var (see
    # create_app_from_env).
    priors_missing = check_priors_coverage(config)
    app.state.priors_missing_for_grades = priors_missing
    if priors_missing:
        log = get_logger("engine.startup")
        for grade in priors_missing:
            log.warning(
                f"no priors configured for grade {grade}; engine will use "
                f"default 0.5 for all skills at this grade. Safe for testing "
                f"but should be addressed before production for grade {grade}."
            )

    # Use a fresh CollectorRegistry per app so tests don't collide on the
    # prometheus_client global default registry across test cases.
    registry = metrics_registry if metrics_registry is not None else CollectorRegistry()
    app.state.prometheus_registry = registry
    app.state.metrics = register_metrics(registry)

    # Routes
    app.include_router(router)         # prefix /api/v1/diagnostic
    app.include_router(flat_router)    # bare /health, /metrics

    # Middleware. Starlette runs middleware in reverse-registration order on
    # the way in, so the LAST one added (RequestIdMiddleware here) is the
    # FIRST to run. The id is therefore bound before any other handler.
    app.add_middleware(RequestIdMiddleware)

    # Exception handlers
    _register_exception_handlers(app)

    return app


def create_app_from_env() -> FastAPI:
    """Production factory: read all dependencies from environment variables.

    Required env vars:
      ENGINE_CONFIG_PATH  - path to engine_config.yaml
      TENANT_TOKENS_JSON  - JSON object mapping tenant_id to shared-secret token

    Optional env vars:
      ENGINE_VERSION              - engine version string (default: engine.__version__)
      STORAGE_BACKEND             - 'memory' or 'mongodb' (default: 'memory')
      MONGODB_URL                 - required when STORAGE_BACKEND=mongodb
      MONGODB_DATABASE            - database name (default: 'aml_engine')
      LOG_LEVEL                   - debug/info/warn/error (default: info)
      LOG_FORMAT                  - json/text (default: json)
      STRICT_PRIORS_REQUIRED      - 'true' / 'false' (default: false). When
                                    true, startup fails if any configured
                                    grade has no priors. Default behavior
                                    is to log a WARN and continue. See
                                    engine.config.check_priors_coverage.
      QUESTION_PARAMETERS_PATH    - path to question_parameters.csv (default:
                                    /etc/engine/question_parameters.csv). The
                                    production pool (CsvQuestionPool) reads
                                    this to return real question ids plus
                                    calibrated slip/guess. If the file is
                                    absent, startup fails with a clear error.
      TENANT_QUESTION_LOOKUP_PATH - optional path to tenant_question_lookup.csv
                                    (built offline). When set, the pool resolves
                                    tenant-scoped question_x_ids and filters to
                                    items the session tenant can serve. When
                                    unset, the pool uses the params q_x_id and
                                    ignores tenant (legacy single-file mode).
      RETIRED_LIST_PATH           - optional path to retired_questions_v2.csv (canonical 27-item list),
                                    applied at enumeration as defence-in-depth
                                    (the build step already drops retired rows
                                    from the lookup).
      OFFLINE_ARTIFACT_DIR        - optional path to the offline-tree artifact
                                    directory (<dir>/<tenant>/g<grade>.json.gz).
                                    Default: repo-relative artifact/ next to the
                                    engine package (no /mnt dependency). Used by
                                    session/start's offline_tree reference and
                                    the offline-tree fetch endpoint (B1).
    """
    config_path = os.environ.get("ENGINE_CONFIG_PATH", "/etc/engine/config.yaml")
    config = load_engine_config(config_path)

    # Fail-fast on missing priors if the operator opted in. The same gap is
    # also reported via WARN logs and /health when the engine starts; this
    # only short-circuits app construction when strict mode is requested.
    if os.environ.get("STRICT_PRIORS_REQUIRED", "false").lower() == "true":
        missing = check_priors_coverage(config)
        if missing:
            raise RuntimeError(
                f"STRICT_PRIORS_REQUIRED=true and the following grades have "
                f"no priors: {missing}. Add priors for these grades to the "
                f"engine_config.yaml, or unset STRICT_PRIORS_REQUIRED."
            )

    storage = get_storage_backend()
    lattice_edges = storage.load_lattice_edges()
    lattice_index = LatticeIndex(lattice_edges)

    tenant_tokens_json = os.environ.get("TENANT_TOKENS_JSON", "{}")
    try:
        tenant_tokens = json.loads(tenant_tokens_json)
    except json.JSONDecodeError as e:
        raise ValueError(f"TENANT_TOKENS_JSON is not valid JSON: {e}") from e
    if not isinstance(tenant_tokens, dict):
        raise ValueError("TENANT_TOKENS_JSON must be a JSON object")

    engine_version = os.environ.get("ENGINE_VERSION", engine.__version__)

    configure_logging(
        level=os.environ.get("LOG_LEVEL", "info"),
        fmt=os.environ.get("LOG_FORMAT", "json"),
        version=engine_version,
    )

    # Production question pool: real ids + calibrated slip/guess from the
    # calibration CSV. We pass the config's scope skills as expected_skills so
    # the pool logs a loud WARNING for any scope skill that has zero questions
    # (a content-pool gap). StubQuestionPool stays the create_app default for
    # unit tests that do not need real content.
    question_params_path = os.environ.get(
        "QUESTION_PARAMETERS_PATH", "/etc/engine/question_parameters.csv"
    )
    # Optional per-tenant lookup (built offline by build_question_lookup.py). When
    # set, the pool resolves tenant-scoped question_x_ids and applies the
    # tenant-availability filter at enumeration. The retired list is optional
    # defence-in-depth (the build step already drops retired rows from the
    # lookup). Both default to None, preserving the single-file legacy behaviour.
    lookup_path = os.environ.get("TENANT_QUESTION_LOOKUP_PATH") or None
    retired_path = os.environ.get("RETIRED_LIST_PATH") or None
    question_pool = CsvQuestionPool(
        question_params_path,
        expected_skills={s.name for s in config.skills},
        lookup_path=lookup_path,
        retired_path=retired_path,
        misconception_target=config.misconception.target,
    )

    return create_app(
        config=config,
        storage=storage,
        lattice_index=lattice_index,
        tenant_tokens=tenant_tokens,
        engine_version=engine_version,
        question_pool=question_pool,
        offline_artifact_dir=os.environ.get("OFFLINE_ARTIFACT_DIR") or None,
    )


# === Exception handlers =====================================================


def _endpoint_id_for_path(path: str) -> str:
    """Map a URL path to the canonical endpoint id for the envelope `id` field."""
    if path.endswith("/session/start"):
        return "api.diagnostic.session.start"
    if path.endswith("/response"):
        return "api.diagnostic.session.response"
    if path.endswith("/end"):
        return "api.diagnostic.session.end"
    if path.endswith("/offline-batch"):
        return "api.diagnostic.session.offline_batch"
    if path.endswith("/replace-question"):
        return "api.diagnostic.session.replace_question"
    if path.endswith("/responses"):
        return "api.diagnostic.session.responses"
    if "/offline-tree/" in path:
        return "api.diagnostic.offline_tree"
    if path.endswith("/verdicts"):
        return "api.diagnostic.session.verdicts"
    return "api.diagnostic.unknown"


def _record_api_error_metric(request: Request, endpoint_id: str, code: str) -> None:
    metrics = getattr(request.app.state, "metrics", None)
    if metrics is not None:
        metrics.api_errors_total.labels(endpoint=endpoint_id, error_code=code).inc()


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(EngineApiError)
    async def handle_engine_api_error(request: Request, exc: EngineApiError):
        endpoint_id = _endpoint_id_for_path(request.url.path)
        _record_api_error_metric(request, endpoint_id, exc.code.value)
        envelope = error_envelope(
            endpoint_id=endpoint_id,
            error_code=exc.code.value,
            error_message=exc.message,
            http_status=exc.http_status,
        )
        return JSONResponse(content=envelope, status_code=exc.http_status)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError):
        endpoint_id = _endpoint_id_for_path(request.url.path)
        errors = exc.errors()

        # Extra fields (extra='forbid' violations) -> PII_FIELD_PRESENT.
        extra_field_names = [
            str(e["loc"][-1])
            for e in errors
            if e.get("type") == "extra_forbidden" and e.get("loc")
        ]
        if extra_field_names:
            code = ErrorCode.PII_FIELD_PRESENT
            message = (
                f"unexpected field(s) in request body: {', '.join(extra_field_names)}. "
                "The engine rejects PII or unknown fields per spec section 6.3."
            )
            _record_api_error_metric(request, endpoint_id, code.value)
            envelope = error_envelope(
                endpoint_id=endpoint_id,
                error_code=code.value,
                error_message=message,
                http_status=400,
            )
            return JSONResponse(content=envelope, status_code=400)

        # Grade-field validation errors -> INVALID_GRADE.
        grade_errors = [
            e for e in errors
            if e.get("loc") and "grade" in [str(x) for x in e["loc"]]
        ]
        if grade_errors:
            code = ErrorCode.INVALID_GRADE
            message = f"invalid grade: {grade_errors[0].get('msg', 'invalid value')}"
            _record_api_error_metric(request, endpoint_id, code.value)
            envelope = error_envelope(
                endpoint_id=endpoint_id,
                error_code=code.value,
                error_message=message,
                http_status=400,
            )
            return JSONResponse(content=envelope, status_code=400)

        # Generic validation error -> 400 with detail.
        detail_parts = []
        for e in errors:
            loc = ".".join(str(x) for x in (e.get("loc") or []))
            detail_parts.append(f"{loc}: {e.get('msg', '')}")
        _record_api_error_metric(request, endpoint_id, "VALIDATION_ERROR")
        envelope = error_envelope(
            endpoint_id=endpoint_id,
            error_code="VALIDATION_ERROR",
            error_message="; ".join(detail_parts),
            http_status=400,
        )
        return JSONResponse(content=envelope, status_code=400)


# === Module-level app for uvicorn entry point ===============================

# `uvicorn engine.api.main:app` loads this. Constructed from env on import.
# In test/CLI contexts where env is not set, construction fails and app stays
# None - tests build their own app via create_app().
try:
    app: Optional[FastAPI] = create_app_from_env()
except Exception:
    # Common cases: ENGINE_CONFIG_PATH not set, config file missing,
    # TENANT_TOKENS_JSON malformed. Production deployments must have these.
    app = None  # type: ignore
