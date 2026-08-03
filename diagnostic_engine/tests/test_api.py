"""End-to-end tests for the API layer.

Uses FastAPI's TestClient (httpx-based) to drive the engine through real
HTTP request/response cycles against an in-memory storage backend.
"""

from pathlib import Path
from typing import Dict

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry

from engine.api.envelope import error_envelope, success_envelope
from engine.api.errors import (
    EngineApiError,
    ErrorCode,
    HTTP_STATUS,
    InvalidTenantTokenError,
    SessionNotFoundError,
)
from engine.api.main import create_app
from engine.config import load_engine_config
from engine.lattice import LatticeIndex
from engine.question_pool import StubQuestionPool
from engine.storage.memory import InMemoryStorage

import engine

TEST_FIXTURE = Path(__file__).parent / "fixtures" / "engine_config_test.yaml"

TENANT_A = "tenant-a"
TOKEN_A = "secret-token-a"
TENANT_B = "tenant-b"
TOKEN_B = "secret-token-b"


# === Fixtures ===============================================================


@pytest.fixture
def test_config():
    return load_engine_config(str(TEST_FIXTURE))


@pytest.fixture
def test_storage():
    return InMemoryStorage()


@pytest.fixture
def test_lattice():
    return LatticeIndex([])


@pytest.fixture
def test_tenant_tokens() -> Dict[str, str]:
    return {TENANT_A: TOKEN_A, TENANT_B: TOKEN_B}


@pytest.fixture
def app(test_config, test_storage, test_lattice, test_tenant_tokens):
    return create_app(
        config=test_config,
        storage=test_storage,
        lattice_index=test_lattice,
        tenant_tokens=test_tenant_tokens,
        engine_version="test-0.1.0",
        metrics_registry=CollectorRegistry(),
    )


@pytest.fixture
def client(app):
    return TestClient(app)


def _auth_headers(token: str = TOKEN_A) -> Dict[str, str]:
    return {"X-Internal-Service-Token": token}


def _start_body(
    sub_session_id="s1",
    learner_id="learner-1",
    tenant_id=TENANT_A,
    class_id="class-1",
    grade=3,
) -> Dict:
    return {
        "learner_id": learner_id,
        "tenant_id": tenant_id,
        "sub_session_id": sub_session_id,
        "class_id": class_id,
        "grade": grade,
    }


# === TestEnvelope ===========================================================


class TestEnvelope:
    def test_success_envelope_shape(self):
        env = success_envelope("api.test", {"hello": "world"})
        assert env["id"] == "api.test"
        assert env["ver"] == "1.0"
        assert env["params"]["status"] == "SUCCESS"
        assert env["params"]["resmsgid"]  # generated
        assert env["responseCode"] == "OK"
        assert env["result"] == {"hello": "world"}
        assert "error" not in env

    def test_error_envelope_shape(self):
        env = error_envelope("api.test", "BAD_THING", "something broke", 400)
        assert env["params"]["status"] == "FAILED"
        assert env["responseCode"] == "BAD_REQUEST"
        assert env["result"] == {}
        assert env["error"]["code"] == "BAD_THING"
        assert env["error"]["message"] == "something broke"

    def test_envelope_msgid_passthrough(self):
        env = success_envelope("api.test", {}, msgid="caller-abc")
        assert env["params"]["msgid"] == "caller-abc"

    def test_response_code_maps_for_known_codes(self):
        assert error_envelope("api.x", "x", "m", 401)["responseCode"] == "UNAUTHORIZED"
        assert error_envelope("api.x", "x", "m", 404)["responseCode"] == "NOT_FOUND"
        assert error_envelope("api.x", "x", "m", 409)["responseCode"] == "CONFLICT"
        assert error_envelope("api.x", "x", "m", 503)["responseCode"] == "SERVICE_UNAVAILABLE"


# === TestErrors =============================================================


class TestErrors:
    def test_error_codes_have_http_mappings(self):
        for code in ErrorCode:
            assert code in HTTP_STATUS

    def test_error_subclass_carries_code_and_status(self):
        err = SessionNotFoundError("not found")
        assert err.code == ErrorCode.SESSION_NOT_FOUND
        assert err.http_status == 404
        assert err.message == "not found"

    def test_engine_api_error_is_base(self):
        err = InvalidTenantTokenError("bad token")
        assert isinstance(err, EngineApiError)
        assert err.http_status == 401


# === TestAuth ===============================================================


class TestAuth:
    def test_missing_header_rejected(self, client):
        r = client.post("/api/v1/diagnostic/session/start", json=_start_body())
        assert r.status_code == 401
        body = r.json()
        assert body["error"]["code"] == "INVALID_TENANT_TOKEN"
        assert body["params"]["status"] == "FAILED"

    def test_wrong_token_rejected(self, client):
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers("wrong-token"),
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_TENANT_TOKEN"

    def test_unknown_tenant_rejected(self, client):
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(tenant_id="unknown-tenant"),
            headers=_auth_headers(TOKEN_A),
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "INVALID_TENANT_TOKEN"

    def test_token_mismatch_across_tenants(self, client):
        # token_b belongs to tenant_b, not tenant_a
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(tenant_id=TENANT_A),
            headers=_auth_headers(TOKEN_B),
        )
        assert r.status_code == 401

    def test_valid_token_accepted(self, client):
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers(),
        )
        assert r.status_code == 200


# === TestSchemas (PII rejection) ============================================


class TestSchemas:
    def test_extra_field_rejected_as_pii(self, client):
        body = _start_body()
        body["username"] = "alice"  # not in schema
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=body,
            headers=_auth_headers(),
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "PII_FIELD_PRESENT"
        assert "username" in r.json()["error"]["message"]

    def test_multiple_extra_fields_all_reported(self, client):
        body = _start_body()
        body["username"] = "alice"
        body["email"] = "alice@example.com"
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=body,
            headers=_auth_headers(),
        )
        assert r.status_code == 400
        msg = r.json()["error"]["message"]
        assert "username" in msg
        assert "email" in msg

    @pytest.mark.parametrize("grade", [0, 1, 9, 12, 99])
    def test_grade_outside_supported_range_returns_invalid_grade(self, client, grade):
        """Spec section 2 supports grades 2-8 (2-5 configured, 6-8 fall back to G5).

        Anything outside this range fails Pydantic validation but is mapped
        to INVALID_GRADE (status 400) by the global exception handler so
        the error envelope shape stays consistent with engine-layer rejections.
        """
        body = _start_body(grade=grade)
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=body,
            headers=_auth_headers(),
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_GRADE"

    @pytest.mark.parametrize("grade", [2, 3, 4, 5, 6, 7, 8])
    def test_grade_inside_supported_range_passes_schema_validation(self, client, grade):
        """All grades 2-8 pass Pydantic validation.

        The TEST fixture only configures G2 and G3, so grades 4-8 still get
        rejected by the engine layer with INVALID_GRADE. This test only
        asserts the Pydantic layer accepts them.
        """
        body = _start_body(grade=grade)
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=body,
            headers=_auth_headers(),
        )
        # Status is 200 for G2/G3 (configured in fixture) or 400 with
        # INVALID_GRADE for G4-G8 (passed schema, rejected by engine).
        if grade in (2, 3):
            assert r.status_code == 200
        else:
            assert r.status_code == 400
            assert r.json()["error"]["code"] == "INVALID_GRADE"

    def test_missing_required_field_returns_400(self, client):
        body = _start_body()
        del body["learner_id"]
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=body,
            headers=_auth_headers(),
        )
        assert r.status_code == 400


# === TestSessionStart =======================================================


class TestSessionStart:
    def test_happy_path(self, client):
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["id"] == "api.diagnostic.session.start"
        assert body["params"]["status"] == "SUCCESS"
        result = body["result"]
        assert result["sub_session_id"] == "s1"
        assert result["first_question"] is not None
        assert "question_x_id" in result["first_question"]
        assert "skill_id" in result["first_question"]
        # G3 budget total = 42 per test fixture
        assert result["question_budget"] == 42

    def test_first_question_is_g3_anchor(self, client):
        # G3 operation order starts with Multiplication; G3 Mult anchor = "Tables 1 to 9"
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers(),
        )
        assert r.json()["result"]["first_question"]["skill_id"] == "Tables 1 to 9"

    def test_duplicate_sub_session_id_rejected(self, client):
        r1 = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers(),
        )
        assert r1.status_code == 200
        r2 = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),  # same sub_session_id
            headers=_auth_headers(),
        )
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "SESSION_ALREADY_EXISTS"

    def test_unconfigured_grade_returns_invalid_grade(self, client):
        # Test fixture only has G2/G3. Grade 5 is not configured.
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(grade=5),
            headers=_auth_headers(),
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_GRADE"


# === TestSessionResponse ====================================================


class TestSessionResponse:
    def _start(self, client, sub_session_id="s1"):
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(sub_session_id=sub_session_id),
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        return r.json()["result"]["first_question"]

    def test_response_returns_next_question(self, client):
        q = self._start(client)
        r = client.post(
            "/api/v1/diagnostic/session/s1/response",
            json={
                "learner_id": "learner-1",
                "tenant_id": TENANT_A,
                "skill_id": q["skill_id"],
                "question_x_id": q["question_x_id"],
                "is_correct": True,
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        result = r.json()["result"]
        # Either next question or session complete
        if not result["session_complete"]:
            assert result["next_question"] is not None
            assert result["questions_asked_so_far"] == 1
            assert result["questions_remaining_budget"] == 41

    def test_session_completes_after_enough_correct_responses(self, client):
        q = self._start(client)
        answers = 0
        max_iter = 100
        verdicts = None
        while q is not None and answers < max_iter:
            r = client.post(
                "/api/v1/diagnostic/session/s1/response",
                json={
                    "learner_id": "learner-1",
                    "tenant_id": TENANT_A,
                    "skill_id": q["skill_id"],
                    "question_x_id": q["question_x_id"],
                    "is_correct": True,
                },
                headers=_auth_headers(),
            )
            assert r.status_code == 200
            answers += 1
            result = r.json()["result"]
            if result["session_complete"]:
                verdicts = result["verdicts"]
                q = None
            else:
                q = result["next_question"]
        assert answers < max_iter, "session did not complete within iteration cap"
        assert verdicts is not None
        assert len(verdicts) > 0
        # Every verdict has the required fields
        for v in verdicts:
            assert "skill_id" in v
            assert "operation" in v
            assert "posterior" in v
            assert "confidence_label" in v
            assert "recommendation" in v

    def test_session_not_found(self, client):
        r = client.post(
            "/api/v1/diagnostic/session/nonexistent/response",
            json={
                "learner_id": "learner-1",
                "tenant_id": TENANT_A,
                "skill_id": "1D+1D sum upto 9",
                "question_x_id": "q1",
                "is_correct": True,
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "SESSION_NOT_FOUND"

    def test_learner_mismatch(self, client):
        q = self._start(client)
        r = client.post(
            "/api/v1/diagnostic/session/s1/response",
            json={
                "learner_id": "different-learner",
                "tenant_id": TENANT_A,
                "skill_id": q["skill_id"],
                "question_x_id": q["question_x_id"],
                "is_correct": True,
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "LEARNER_MISMATCH"

    def test_invalid_skill_id(self, client):
        q = self._start(client)
        r = client.post(
            "/api/v1/diagnostic/session/s1/response",
            json={
                "learner_id": "learner-1",
                "tenant_id": TENANT_A,
                "skill_id": "Not A Real Skill",
                "question_x_id": q["question_x_id"],
                "is_correct": True,
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "INVALID_SKILL_ID"

    def test_idempotent_replay(self, client):
        """Same response submitted twice returns the same result (no second update)."""
        q = self._start(client)
        body = {
            "learner_id": "learner-1",
            "tenant_id": TENANT_A,
            "skill_id": q["skill_id"],
            "question_x_id": q["question_x_id"],
            "is_correct": True,
        }
        r1 = client.post(
            "/api/v1/diagnostic/session/s1/response",
            json=body,
            headers=_auth_headers(),
        )
        assert r1.status_code == 200
        r2 = client.post(
            "/api/v1/diagnostic/session/s1/response",
            json=body,
            headers=_auth_headers(),
        )
        assert r2.status_code == 200
        # Same questions_asked_so_far between r1 and r2 (no double-count)
        # Note: trace ids differ; we compare the result payload only.
        assert (
            r1.json()["result"]["questions_asked_so_far"]
            == r2.json()["result"]["questions_asked_so_far"]
        )

    def test_response_conflict_returns_409(self, client):
        """Same question_id submitted with different is_correct triggers RESPONSE_CONFLICT."""
        q = self._start(client)
        body = {
            "learner_id": "learner-1",
            "tenant_id": TENANT_A,
            "skill_id": q["skill_id"],
            "question_x_id": q["question_x_id"],
        }
        client.post(
            "/api/v1/diagnostic/session/s1/response",
            json={**body, "is_correct": True},
            headers=_auth_headers(),
        )
        r2 = client.post(
            "/api/v1/diagnostic/session/s1/response",
            json={**body, "is_correct": False},
            headers=_auth_headers(),
        )
        assert r2.status_code == 409
        assert r2.json()["error"]["code"] == "RESPONSE_CONFLICT"


# === TestSessionEnd =========================================================


class TestSessionEnd:
    def test_end_active_session(self, client):
        client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers(),
        )
        r = client.post(
            "/api/v1/diagnostic/session/s1/end",
            json={
                "learner_id": "learner-1",
                "tenant_id": TENANT_A,
                "reason": "learner_quit",
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        result = r.json()["result"]
        assert result["session_complete"] is True
        assert result["next_question"] is None
        assert isinstance(result["verdicts"], list)

    def test_end_session_not_found(self, client):
        r = client.post(
            "/api/v1/diagnostic/session/nonexistent/end",
            json={"learner_id": "learner-1", "tenant_id": TENANT_A},
            headers=_auth_headers(),
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "SESSION_NOT_FOUND"

    def test_end_already_ended_session(self, client):
        client.post("/api/v1/diagnostic/session/start", json=_start_body(), headers=_auth_headers())
        client.post(
            "/api/v1/diagnostic/session/s1/end",
            json={"learner_id": "learner-1", "tenant_id": TENANT_A},
            headers=_auth_headers(),
        )
        r = client.post(
            "/api/v1/diagnostic/session/s1/end",
            json={"learner_id": "learner-1", "tenant_id": TENANT_A},
            headers=_auth_headers(),
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "SESSION_ALREADY_ENDED"

    def test_response_after_end_rejected(self, client):
        q_first = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers(),
        ).json()["result"]["first_question"]
        client.post(
            "/api/v1/diagnostic/session/s1/end",
            json={"learner_id": "learner-1", "tenant_id": TENANT_A},
            headers=_auth_headers(),
        )
        r = client.post(
            "/api/v1/diagnostic/session/s1/response",
            json={
                "learner_id": "learner-1",
                "tenant_id": TENANT_A,
                "skill_id": q_first["skill_id"],
                "question_x_id": q_first["question_x_id"],
                "is_correct": True,
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "SESSION_ALREADY_ENDED"


# === TestGetVerdicts ========================================================


class TestGetVerdicts:
    def _start_and_end(self, client, sub_session_id="s1"):
        client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(sub_session_id=sub_session_id),
            headers=_auth_headers(),
        )
        client.post(
            f"/api/v1/diagnostic/session/{sub_session_id}/end",
            json={"learner_id": "learner-1", "tenant_id": TENANT_A},
            headers=_auth_headers(),
        )

    def test_get_verdicts_after_end(self, client):
        self._start_and_end(client)
        r = client.get(
            "/api/v1/diagnostic/session/s1/verdicts",
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["params"]["status"] == "SUCCESS"
        assert isinstance(body["result"]["verdicts"], list)
        assert len(body["result"]["verdicts"]) > 0

    def test_get_verdicts_for_active_session_rejected(self, client):
        client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers(),
        )
        r = client.get(
            "/api/v1/diagnostic/session/s1/verdicts",
            headers=_auth_headers(),
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "SESSION_NOT_COMPLETE"

    def test_get_verdicts_session_not_found(self, client):
        r = client.get(
            "/api/v1/diagnostic/session/nonexistent/verdicts",
            headers=_auth_headers(),
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "SESSION_NOT_FOUND"

    def test_get_verdicts_no_auth(self, client):
        r = client.get("/api/v1/diagnostic/session/s1/verdicts")
        assert r.status_code == 401

    def test_get_verdicts_accepts_any_registered_token(self, client):
        """GET /verdicts has no body so any registered token is accepted."""
        self._start_and_end(client)
        # Use token_b (a different tenant's token); should still be accepted.
        r = client.get(
            "/api/v1/diagnostic/session/s1/verdicts",
            headers=_auth_headers(TOKEN_B),
        )
        assert r.status_code == 200


# === TestHealth =============================================================


class TestHealth:
    def test_health_returns_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["version"] == "test-0.1.0"
        assert body["engine_config_loaded"] is True
        assert body["storage"] == "connected"
        # Fixture has priors for both G2 and G3, so the gap list is empty.
        assert body["priors_missing_for_grades"] == []
        # /health returns a flat object (no envelope) for k8s probes
        assert "params" not in body

    def test_health_not_exposed_on_prefixed_path(self, client):
        """Prefixed /api/v1/diagnostic/health was removed (fix-pack #8).

        The API prefix is for tenant-facing endpoints; health probes are
        operational concerns and should not require knowing the API
        version. The bare /health is the single source of truth for k8s
        probes and operational tooling.
        """
        r = client.get("/api/v1/diagnostic/health")
        assert r.status_code == 404

    def test_health_reports_grades_missing_priors(
        self, test_storage, test_lattice, test_tenant_tokens,
    ):
        """A config with empty priors for a grade surfaces that grade in /health (fix-pack #2)."""
        import yaml as _yaml
        from engine.config import EngineConfig

        data = _yaml.safe_load(TEST_FIXTURE.read_text())
        data["priors"][2] = {}  # strip G2 priors
        config_with_gap = EngineConfig.model_validate(data)

        app = create_app(
            config=config_with_gap,
            storage=test_storage,
            lattice_index=test_lattice,
            tenant_tokens=test_tenant_tokens,
            engine_version="test-0.1.0",
            metrics_registry=CollectorRegistry(),
        )
        client = TestClient(app)
        body = client.get("/health").json()
        assert body["priors_missing_for_grades"] == [2]

    def test_create_app_emits_warning_for_missing_priors(
        self, test_storage, test_lattice, test_tenant_tokens,
    ):
        """create_app logs a WARN-level structlog event per grade missing priors (fix-pack #2)."""
        import yaml as _yaml
        from structlog.testing import capture_logs

        from engine.config import EngineConfig

        data = _yaml.safe_load(TEST_FIXTURE.read_text())
        data["priors"][2] = {}
        config_with_gap = EngineConfig.model_validate(data)

        with capture_logs() as cap_logs:
            create_app(
                config=config_with_gap,
                storage=test_storage,
                lattice_index=test_lattice,
                tenant_tokens=test_tenant_tokens,
                engine_version="test-0.1.0",
                metrics_registry=CollectorRegistry(),
            )

        warnings = [
            entry for entry in cap_logs
            if entry.get("log_level") == "warning"
        ]
        assert any("grade 2" in entry.get("event", "") for entry in warnings), (
            f"expected a WARN mentioning 'grade 2', got: {cap_logs}"
        )

    def test_no_warnings_when_all_grades_have_priors(
        self, test_config, test_storage, test_lattice, test_tenant_tokens,
    ):
        """When all configured grades have priors, no WARN is emitted (fix-pack #2 sanity)."""
        from structlog.testing import capture_logs

        with capture_logs() as cap_logs:
            create_app(
                config=test_config,
                storage=test_storage,
                lattice_index=test_lattice,
                tenant_tokens=test_tenant_tokens,
                engine_version="test-0.1.0",
                metrics_registry=CollectorRegistry(),
            )
        priors_warnings = [
            e for e in cap_logs
            if e.get("log_level") == "warning" and "priors" in e.get("event", "").lower()
        ]
        assert priors_warnings == []


# === TestMetrics ============================================================


class TestMetrics:
    def test_metrics_returns_prometheus_format(self, client):
        # Trigger a session start so counters move
        client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers(),
        )
        r = client.get("/metrics")
        assert r.status_code == 200
        text = r.text
        assert "diagnostic_sessions_started_total" in text
        assert 'tenant_id="tenant-a"' in text

    def test_metrics_records_session_completion(self, client):
        client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers(),
        )
        client.post(
            "/api/v1/diagnostic/session/s1/end",
            json={"learner_id": "learner-1", "tenant_id": TENANT_A, "reason": "abandoned"},
            headers=_auth_headers(),
        )
        r = client.get("/metrics")
        assert "diagnostic_sessions_completed_total" in r.text
        assert 'end_reason="abandoned"' in r.text

    def test_metrics_records_api_errors(self, client):
        # Trigger an INVALID_GRADE error
        client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(grade=99),
            headers=_auth_headers(),
        )
        r = client.get("/metrics")
        assert "diagnostic_api_errors_total" in r.text
        assert 'error_code="INVALID_GRADE"' in r.text


# === TestQuestionPool =======================================================


class TestQuestionPool:
    def test_stub_produces_deterministic_picks(self, test_config, test_lattice):
        """Build a real session via start_session and verify stub QuestionPick format."""
        from engine.question_pool import QuestionPick
        from engine.session import start_session

        params = test_config.get_engine_params(grade=3, lattice_index=test_lattice)
        result = start_session(
            sub_session_id="s1",
            learner_id="l1",
            tenant_id="t1",
            class_id="c1",
            grade=3,
            engine_version="0.1.0",
            params=params,
        )

        pool = StubQuestionPool()

        # First call: no history -> 0001
        pick1 = pool.pick_question_for_skill(
            skill="Tables 1 to 9", session=result.session, grade=3, tenant_id="t1",
        )
        assert isinstance(pick1, QuestionPick)
        assert pick1.question_id == "stub::Tables 1 to 9::0001"
        # Stub never sets per-item overrides; calibration is None
        assert pick1.slip_override is None
        assert pick1.guess_override is None

        # Same call without history change -> same id (deterministic)
        pick2 = pool.pick_question_for_skill(
            skill="Tables 1 to 9", session=result.session, grade=3, tenant_id="t1",
        )
        assert pick2.question_id == pick1.question_id

    def test_stub_increments_within_session(self, test_config, test_lattice):
        """Once history records a question, the next stub QuestionPick increments."""
        from engine.session import (
            QuestionHistoryEntry,
            RoutingMode,
            start_session,
        )
        from engine.routing import Purpose
        from datetime import datetime, timezone

        params = test_config.get_engine_params(grade=3, lattice_index=test_lattice)
        result = start_session(
            sub_session_id="s1",
            learner_id="l1",
            tenant_id="t1",
            class_id="c1",
            grade=3,
            engine_version="0.1.0",
            params=params,
        )

        # Manually add a history entry for the skill
        result.session.question_history.append(
            QuestionHistoryEntry(
                sequence=1,
                skill_id="Tables 1 to 9",
                question_id="stub::Tables 1 to 9::0001",
                is_correct=True,
                purpose=Purpose.ANCHOR,
                routing_mode=RoutingMode.ONLINE,
                asked_at=datetime.now(timezone.utc),
                posterior_before=0.5,
                posterior_after=0.857,
            )
        )

        pool = StubQuestionPool()
        pick = pool.pick_question_for_skill(
            skill="Tables 1 to 9", session=result.session, grade=3, tenant_id="t1",
        )
        assert pick.question_id == "stub::Tables 1 to 9::0002"


# === TestCreateAppFromEnv (fix-pack change #2 strict mode) ==================


class TestCreateAppFromEnv:
    """Production factory tests, focused on the STRICT_PRIORS_REQUIRED env var.

    create_app_from_env reads ENGINE_CONFIG_PATH + TENANT_TOKENS_JSON +
    STRICT_PRIORS_REQUIRED. When STRICT_PRIORS_REQUIRED=true and any
    configured grade has no priors, startup raises RuntimeError before
    the app is constructed (fail-fast).
    """

    def _write_fixture_with_gap(self, tmp_path: Path) -> Path:
        """Write a config YAML where G2 has anchors but empty priors."""
        import yaml as _yaml
        data = _yaml.safe_load(TEST_FIXTURE.read_text())
        data["priors"][2] = {}
        out = tmp_path / "config_with_gap.yaml"
        out.write_text(_yaml.safe_dump(data))
        return out

    def _write_question_params(self, tmp_path: Path) -> str:
        """Write a minimal valid question_parameters CSV covering the fixture's
        skills, so create_app_from_env can build its CsvQuestionPool. The app
        in these tests is not driven, so one question per skill is enough."""
        config = load_engine_config(str(TEST_FIXTURE))
        skills = {s.name for s in config.skills}
        return _write_pool_csv(tmp_path / "qp.csv", skills, slip=0.10, guess=0.15)

    def test_strict_mode_raises_when_priors_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        """STRICT_PRIORS_REQUIRED=true + missing priors -> RuntimeError before app build."""
        from engine.api.main import create_app_from_env

        config_path = self._write_fixture_with_gap(tmp_path)
        monkeypatch.setenv("ENGINE_CONFIG_PATH", str(config_path))
        monkeypatch.setenv("TENANT_TOKENS_JSON", '{"t": "x"}')
        monkeypatch.setenv("STORAGE_BACKEND", "memory")
        monkeypatch.setenv("STRICT_PRIORS_REQUIRED", "true")

        with pytest.raises(RuntimeError, match="STRICT_PRIORS_REQUIRED"):
            create_app_from_env()

    def test_strict_mode_succeeds_when_priors_complete(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        """STRICT_PRIORS_REQUIRED=true + full priors -> app builds normally."""
        from engine.api.main import create_app_from_env

        # The standard fixture has priors for G2 and G3, so strict mode passes.
        monkeypatch.setenv("ENGINE_CONFIG_PATH", str(TEST_FIXTURE))
        monkeypatch.setenv("TENANT_TOKENS_JSON", '{"t": "x"}')
        monkeypatch.setenv("STORAGE_BACKEND", "memory")
        monkeypatch.setenv("STRICT_PRIORS_REQUIRED", "true")
        monkeypatch.setenv("QUESTION_PARAMETERS_PATH", self._write_question_params(tmp_path))

        app = create_app_from_env()
        assert app is not None

    def test_strict_mode_false_allows_missing_priors(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        """STRICT_PRIORS_REQUIRED unset (or false) -> missing priors are warned, not raised."""
        from engine.api.main import create_app_from_env

        config_path = self._write_fixture_with_gap(tmp_path)
        monkeypatch.setenv("ENGINE_CONFIG_PATH", str(config_path))
        monkeypatch.setenv("TENANT_TOKENS_JSON", '{"t": "x"}')
        monkeypatch.setenv("STORAGE_BACKEND", "memory")
        monkeypatch.delenv("STRICT_PRIORS_REQUIRED", raising=False)
        monkeypatch.setenv("QUESTION_PARAMETERS_PATH", self._write_question_params(tmp_path))

        app = create_app_from_env()
        assert app is not None
        # The gap is still reported via app.state for /health to expose.
        assert app.state.priors_missing_for_grades == [2]

    def test_strict_mode_case_insensitive(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ):
        """STRICT_PRIORS_REQUIRED='TRUE' / 'True' / 'true' all enable strict mode."""
        from engine.api.main import create_app_from_env

        config_path = self._write_fixture_with_gap(tmp_path)
        monkeypatch.setenv("ENGINE_CONFIG_PATH", str(config_path))
        monkeypatch.setenv("TENANT_TOKENS_JSON", '{"t": "x"}')
        monkeypatch.setenv("STORAGE_BACKEND", "memory")
        monkeypatch.setenv("STRICT_PRIORS_REQUIRED", "TRUE")

        with pytest.raises(RuntimeError):
            create_app_from_env()


# === TestPerItemCalibration (fix-pack change #3 end-to-end) =================


class _CalibratedTestPool:
    """Test-only QuestionPool that returns fixed per-item overrides.

    Used to verify that calibrated slip / guess values produced by the pool
    flow through the HTTP path and into record_response's Bayes update.
    """

    def __init__(self, slip_override=None, guess_override=None):
        self.slip_override = slip_override
        self.guess_override = guess_override
        self._counter = 0

    def pick_question_for_skill(self, *, skill, session, grade, tenant_id):
        from engine.question_pool import QuestionPick
        self._counter += 1
        return QuestionPick(
            question_id=f"calib::{skill}::{self._counter:04d}",
            slip_override=self.slip_override,
            guess_override=self.guess_override,
        )


class _NoQuestionTestPool:
    """Test-only pool that always raises NoQuestionForSkillError.

    Simulates the spec section 7.8 failure mode (empty candidate set).
    """

    def pick_question_for_skill(self, *, skill, session, grade, tenant_id):
        from engine.api.errors import NoQuestionForSkillError
        raise NoQuestionForSkillError(
            f"no question available for skill '{skill}' at grade {grade}"
        )


class TestPerItemCalibration:
    def test_overrides_persisted_on_session_start(
        self, test_config, test_storage, test_lattice, test_tenant_tokens,
    ):
        """After /session/start, the session in storage carries the QuestionPick's overrides on pending_*."""
        pool = _CalibratedTestPool(slip_override=0.05, guess_override=0.20)
        app = create_app(
            config=test_config,
            storage=test_storage,
            lattice_index=test_lattice,
            tenant_tokens=test_tenant_tokens,
            engine_version="test-0.1.0",
            metrics_registry=CollectorRegistry(),
            question_pool=pool,
        )
        client = TestClient(app)
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        stored = test_storage.get_session("s1")
        assert stored.pending_question_id is not None
        assert stored.pending_question_slip_override == 0.05
        assert stored.pending_question_guess_override == 0.20

    def test_response_applies_overrides_in_bayes_update(
        self, test_config, test_storage, test_lattice, test_tenant_tokens,
    ):
        """The /response call uses the pending_* slip / guess in the Bayes update."""
        # Compare default-Bayes vs calibrated-Bayes by running the same
        # response against two engines that differ only in pool calibration.
        pool_default = _CalibratedTestPool(slip_override=None, guess_override=None)
        pool_low_slip = _CalibratedTestPool(slip_override=0.02, guess_override=None)

        def _run_one_response(pool, storage):
            app = create_app(
                config=test_config,
                storage=storage,
                lattice_index=test_lattice,
                tenant_tokens=test_tenant_tokens,
                engine_version="test-0.1.0",
                metrics_registry=CollectorRegistry(),
                question_pool=pool,
            )
            c = TestClient(app)
            first = c.post(
                "/api/v1/diagnostic/session/start", json=_start_body(),
                headers=_auth_headers(),
            ).json()["result"]["first_question"]
            c.post(
                "/api/v1/diagnostic/session/s1/response",
                json={
                    "learner_id": "learner-1",
                    "tenant_id": TENANT_A,
                    "skill_id": first["skill_id"],
                    "question_x_id": first["question_x_id"],
                    "is_correct": True,
                },
                headers=_auth_headers(),
            )
            stored = storage.get_session("s1")
            return stored.posteriors[first["skill_id"]]

        post_default = _run_one_response(pool_default, InMemoryStorage())
        post_low_slip = _run_one_response(pool_low_slip, InMemoryStorage())
        # Low-slip override -> stronger evidence on correct -> higher posterior
        assert post_low_slip > post_default

    def test_pending_cleared_after_response_and_reset_for_next(
        self, test_config, test_storage, test_lattice, test_tenant_tokens,
    ):
        """After /response, pending_* should reflect the NEXT question's overrides, not the previous one."""
        # Two-question scenario: pool always returns slip=0.05, guess=0.20.
        # After turn 1, pending_* must be set to turn-2 question's overrides.
        pool = _CalibratedTestPool(slip_override=0.05, guess_override=0.20)
        app = create_app(
            config=test_config,
            storage=test_storage,
            lattice_index=test_lattice,
            tenant_tokens=test_tenant_tokens,
            engine_version="test-0.1.0",
            metrics_registry=CollectorRegistry(),
            question_pool=pool,
        )
        client = TestClient(app)
        first = client.post(
            "/api/v1/diagnostic/session/start", json=_start_body(),
            headers=_auth_headers(),
        ).json()["result"]["first_question"]
        q1_id = first["question_x_id"]

        r2 = client.post(
            "/api/v1/diagnostic/session/s1/response",
            json={
                "learner_id": "learner-1", "tenant_id": TENANT_A,
                "skill_id": first["skill_id"], "question_x_id": q1_id,
                "is_correct": True,
            },
            headers=_auth_headers(),
        )
        result = r2.json()["result"]
        if not result["session_complete"]:
            # If a next question came back, pending_* should now point to it
            stored = test_storage.get_session("s1")
            assert stored.pending_question_id == result["next_question"]["question_x_id"]
            assert stored.pending_question_id != q1_id
            # Overrides still apply (pool returns same values)
            assert stored.pending_question_slip_override == 0.05
            assert stored.pending_question_guess_override == 0.20

    def test_no_question_for_skill_returns_500_envelope(
        self, test_config, test_storage, test_lattice, test_tenant_tokens,
    ):
        """When the pool raises NoQuestionForSkillError, the API returns 500 NO_QUESTION_FOR_SKILL (spec section 7.8)."""
        pool = _NoQuestionTestPool()
        app = create_app(
            config=test_config,
            storage=test_storage,
            lattice_index=test_lattice,
            tenant_tokens=test_tenant_tokens,
            engine_version="test-0.1.0",
            metrics_registry=CollectorRegistry(),
            question_pool=pool,
        )
        client = TestClient(app)
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(),
            headers=_auth_headers(),
        )
        assert r.status_code == 500
        body = r.json()
        assert body["params"]["status"] == "FAILED"
        assert body["error"]["code"] == "NO_QUESTION_FOR_SKILL"
        assert "skill" in body["error"]["message"].lower()


# === TestCsvQuestionPoolEndToEnd (CsvQuestionPool integration) =============


def _write_pool_csv(path: Path, skills, slip: float, guess: float) -> str:
    """Write a question_parameters-style CSV: one question per skill, every
    question carrying the same distinctive calibrated slip / guess."""
    import csv as _csv
    disc = round(1.0 - slip - guess, 4)
    header = ["item", "q_x_id", "l2_5_skill", "q_type", "grade", "slip", "guess", "discrimination"]
    with path.open("w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for i, skill in enumerate(sorted(skills)):
            w.writerow({
                "item": f"{skill}|item|Fib||{i}|0", "q_x_id": f"q_csv_{i:04d}",
                "l2_5_skill": skill, "q_type": "Fib", "grade": "all",
                "slip": slip, "guess": guess, "discrimination": disc,
            })
    return str(path)


def _bayes_correct(prior: float, slip: float, guess: float) -> float:
    """DINA-style posterior after a correct answer."""
    num = prior * (1.0 - slip)
    return num / (num + (1.0 - prior) * guess)


class TestCsvQuestionPoolEndToEnd:
    """A real CsvQuestionPool's calibrated slip/guess must reach the Bayes
    update, not the uniform config defaults (spec section 8 acceptance)."""

    def test_calibrated_values_reach_bayes_update(
        self, test_config, test_storage, test_lattice, test_tenant_tokens, tmp_path,
    ):
        from engine.question_pool import CsvQuestionPool

        # Distinctive calibrated values, clearly different from the config
        # defaults (slip 0.10 / guess 0.15 in the test fixture).
        CAL_SLIP, CAL_GUESS = 0.02, 0.30
        scope_skills = {s.name for s in test_config.skills if s.content_grade <= 3}
        csv_path = _write_pool_csv(tmp_path / "qp.csv", scope_skills, CAL_SLIP, CAL_GUESS)
        pool = CsvQuestionPool(csv_path, seed=1)

        app = create_app(
            config=test_config, storage=test_storage, lattice_index=test_lattice,
            tenant_tokens=test_tenant_tokens, engine_version="test-0.1.0",
            metrics_registry=CollectorRegistry(), question_pool=pool,
        )
        client = TestClient(app)
        first = client.post(
            "/api/v1/diagnostic/session/start", json=_start_body(),
            headers=_auth_headers(),
        ).json()["result"]["first_question"]

        # The returned question_id must be a real CSV id, not a stub id.
        assert first["question_x_id"].startswith("q_csv_")

        client.post(
            "/api/v1/diagnostic/session/s1/response",
            json={
                "learner_id": "learner-1", "tenant_id": TENANT_A,
                "skill_id": first["skill_id"], "question_x_id": first["question_x_id"],
                "is_correct": True,
            },
            headers=_auth_headers(),
        )

        stored = test_storage.get_session("s1")
        entry = next(
            e for e in stored.question_history if e.question_id == first["question_x_id"]
        )
        # The update must match the CALIBRATED params, and differ from what the
        # config defaults (0.10 / 0.15) would have produced.
        expected_calibrated = _bayes_correct(entry.posterior_before, CAL_SLIP, CAL_GUESS)
        expected_default = _bayes_correct(entry.posterior_before, 0.10, 0.15)
        assert entry.posterior_after == pytest.approx(expected_calibrated, abs=1e-6)
        assert abs(entry.posterior_after - expected_default) > 1e-3

    def test_factory_builds_csv_pool_with_scope_warning(self, monkeypatch, tmp_path):
        """create_app_from_env builds a CsvQuestionPool and passes scope skills,
        so a scope skill missing from the CSV produces a startup WARNING."""
        from engine.api import main as main_mod

        # Build a CSV that covers only SOME of the config's scope skills, so at
        # least one scope skill is missing and should trigger the WARNING.
        config = load_engine_config(str(TEST_FIXTURE))
        all_scope = sorted({s.name for s in config.skills})
        covered = all_scope[:-1]  # drop one so it is "missing" from the CSV
        csv_path = _write_pool_csv(tmp_path / "qp.csv", covered, 0.05, 0.20)

        warnings = []

        class _FakeLogger:
            def warning(self, msg, *a, **k):
                warnings.append(msg)
            def info(self, *a, **k):
                pass

        monkeypatch.setattr(
            "engine.question_pool.get_logger", lambda *a, **k: _FakeLogger()
        )
        monkeypatch.setenv("ENGINE_CONFIG_PATH", str(TEST_FIXTURE))
        monkeypatch.setenv("QUESTION_PARAMETERS_PATH", csv_path)
        monkeypatch.setenv("TENANT_TOKENS_JSON", '{"tenant-a": "tok"}')
        monkeypatch.setenv("STORAGE_BACKEND", "memory")

        app = main_mod.create_app_from_env()
        from engine.question_pool import CsvQuestionPool
        assert isinstance(app.state.question_pool, CsvQuestionPool)
        # The dropped scope skill should have produced a warning.
        assert any(all_scope[-1] in w for w in warnings)


# === TestRequestIdMiddleware (fix-pack change #4) ==========================


class TestRequestIdMiddleware:
    """RequestIdMiddleware binds request_id to structlog contextvars and echoes the header.

    Spec section 9.3 includes request_id in the log allow-list. The middleware
    is the producer; engine.observability.logging.configure_logging already
    has structlog.contextvars.merge_contextvars in its processor chain, so
    log lines emitted during a request automatically carry the id.
    """

    def test_client_supplied_request_id_echoes_back(self, client):
        """When the client sends X-Request-Id, the response echoes the same value."""
        supplied = "req-abc-123"
        r = client.get("/health", headers={"X-Request-Id": supplied})
        assert r.status_code == 200
        assert r.headers.get("X-Request-Id") == supplied

    def test_missing_header_generates_uuid(self, client):
        """When no X-Request-Id is sent, the response carries a fresh UUID4."""
        import uuid as _uuid
        r = client.get("/health")
        assert r.status_code == 200
        echoed = r.headers.get("X-Request-Id")
        assert echoed is not None
        # Parses as a valid UUID
        parsed = _uuid.UUID(echoed)
        assert parsed.version == 4

    def test_each_request_gets_distinct_uuid(self, client):
        """Two requests without X-Request-Id get two different generated ids."""
        r1 = client.get("/health")
        r2 = client.get("/health")
        id1 = r1.headers["X-Request-Id"]
        id2 = r2.headers["X-Request-Id"]
        assert id1 != id2

    def test_request_id_bound_in_route_handler(
        self, test_config, test_storage, test_lattice, test_tenant_tokens,
    ):
        """During a route handler, structlog contextvars carry the request_id.

        This is the production-relevant check: merge_contextvars (already in
        the structlog processor chain) injects request_id into every log
        event during the request. Verified here by inspecting the contextvar
        directly from inside a handler.
        """
        import structlog

        app = create_app(
            config=test_config,
            storage=test_storage,
            lattice_index=test_lattice,
            tenant_tokens=test_tenant_tokens,
            engine_version="test-0.1.0",
            metrics_registry=CollectorRegistry(),
        )
        captured = {}

        @app.get("/__capture_contextvars")
        def _capture():
            captured.update(structlog.contextvars.get_contextvars())
            return {"ok": True}

        client = TestClient(app)
        client.get("/__capture_contextvars", headers={"X-Request-Id": "req-42"})
        assert captured.get("request_id") == "req-42"

    def test_middleware_unbinds_after_response(self, client):
        """Two sequential requests don't leak request_id into each other's log context."""
        import structlog
        # Issue one request to set+unset the contextvar.
        client.get("/health", headers={"X-Request-Id": "req-1"})
        # The contextvar should now be unset.
        bound = structlog.contextvars.get_contextvars()
        assert "request_id" not in bound


# === TestPropagationUpdatesEndToEnd (fix-pack change #6) ===================


class TestPropagationUpdatesEndToEnd:
    """propagation_updates threads from session -> verdict storage -> API payload.

    Spec section 6.1 (verdict document field) and spec section 7.6 (verdict
    rules that consume it). The headline behavior verified here: priors-only
    skills now earn confident_mastered (Rule 2) instead of being downgraded.
    """

    def test_verdict_payload_includes_propagation_updates_field(
        self, test_config, test_storage, test_lattice, test_tenant_tokens,
    ):
        """Every verdict in the API response includes the new field."""
        app = create_app(
            config=test_config,
            storage=test_storage,
            lattice_index=test_lattice,
            tenant_tokens=test_tenant_tokens,
            engine_version="test-0.1.0",
            metrics_registry=CollectorRegistry(),
        )
        client = TestClient(app)
        client.post(
            "/api/v1/diagnostic/session/start", json=_start_body(),
            headers=_auth_headers(),
        )
        # Force end without any responses; this is the abandoned path.
        r = client.post(
            "/api/v1/diagnostic/session/s1/end",
            json={"learner_id": "learner-1", "tenant_id": TENANT_A, "reason": "abandoned"},
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        verdicts = r.json()["result"]["verdicts"]
        assert len(verdicts) > 0
        for v in verdicts:
            assert "propagation_updates" in v
            # No question was answered, so no propagation could have fired.
            assert v["propagation_updates"] == 0

    def test_priors_only_high_skill_returns_confident_mastered(
        self, test_config, test_storage, test_lattice, test_tenant_tokens,
    ):
        """Spec section 7.6 Rule 2: priors-only mastery skill -> confident_mastered.

        End a session immediately. All skills are at their prior; nothing has
        moved any posterior. Per spec section 7.6 Rule 2, any skill whose
        prior is already in the mastery zone earns confident_mastered.
        """
        app = create_app(
            config=test_config,
            storage=test_storage,
            lattice_index=test_lattice,
            tenant_tokens=test_tenant_tokens,
            engine_version="test-0.1.0",
            metrics_registry=CollectorRegistry(),
        )
        client = TestClient(app)
        client.post(
            "/api/v1/diagnostic/session/start", json=_start_body(),
            headers=_auth_headers(),
        )
        r = client.post(
            "/api/v1/diagnostic/session/s1/end",
            json={"learner_id": "learner-1", "tenant_id": TENANT_A, "reason": "abandoned"},
            headers=_auth_headers(),
        )
        verdicts = r.json()["result"]["verdicts"]
        # Find any verdict whose prior was already >= 0.95 in the fixture.
        # The test config has priors at 0.95 for several skills.
        high_priors_verdicts = [v for v in verdicts if v["posterior"] >= 0.95]
        assert len(high_priors_verdicts) > 0, (
            "test fixture should have at least one priors-only mastery skill"
        )
        for v in high_priors_verdicts:
            assert v["direct_observations"] == 0
            assert v["propagation_updates"] == 0
            assert v["confidence_label"] == "confident_mastered", (
                f"priors-only mastery skill {v['skill_id']} (posterior={v['posterior']}) "
                f"should be confident_mastered per spec section 7.6 Rule 2"
            )
            assert v["recommendation"] == "skip_maind"


def test_verdict_end_to_end_carries_default_engine_version(
    test_config, test_storage, test_lattice, test_tenant_tokens
):
    """P0-1: with no ENGINE_VERSION override the app defaults to engine.__version__,
    so a completed session (which produces the verdicts) is stamped with it."""
    assert engine.__version__ == "0.10.0"
    app = create_app(
        config=test_config,
        storage=test_storage,
        lattice_index=test_lattice,
        tenant_tokens=test_tenant_tokens,
        engine_version=engine.__version__,
        metrics_registry=CollectorRegistry(),
    )
    client = TestClient(app)
    r = client.post(
        "/api/v1/diagnostic/session/start",
        json=_start_body(), headers=_auth_headers(),
    )
    assert r.status_code == 200
    q = r.json()["result"]["first_question"]
    verdicts = None
    for _ in range(100):
        if q is None:
            break
        rr = client.post(
            "/api/v1/diagnostic/session/s1/response",
            json={
                "learner_id": "learner-1", "tenant_id": TENANT_A,
                "skill_id": q["skill_id"], "question_x_id": q["question_x_id"],
                "is_correct": True,
            },
            headers=_auth_headers(),
        )
        assert rr.status_code == 200
        res = rr.json()["result"]
        if res["session_complete"]:
            verdicts = res["verdicts"]
            break
        q = res["next_question"]
    assert verdicts is not None and len(verdicts) > 0
    # The session that produced the verdicts carries the default engine version.
    assert test_storage.get_session("s1").engine_version == "0.10.0"


# === TestRawResponseB2 (B2: raw_response persistence + 8.4 responses fetch) ==


class TestRawResponseB2:
    """B2: optional raw_response on the response request, persisted per
    question and returned by GET /session/:id/responses (spec section 8.4).
    Uses the light StubQuestionPool app; offline_tree is null here (irrelevant
    to B2). is_correct stays the only mastery input."""

    def _start(self, client, sid="s1", grade=3):
        r = client.post(
            "/api/v1/diagnostic/session/start",
            json=_start_body(sub_session_id=sid, grade=grade),
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        return r.json()["result"]["first_question"]

    def test_openapi_shows_raw_response_optional(self, client):
        spec = client.get("/openapi.json").json()
        schema = spec["components"]["schemas"]["SessionResponseRequest"]
        assert "raw_response" in schema["properties"], (
            "raw_response must be declared on the schema (extra=forbid rejects "
            "undeclared fields)"
        )
        assert "raw_response" not in schema.get("required", []), (
            "raw_response must be optional / nullable"
        )

    def test_response_without_raw_response_still_succeeds(self, client):
        # Backward-compat: the core pilot never sends raw_response; a response
        # without it produces a verdict unchanged.
        q = self._start(client)
        verdicts = None
        for _ in range(100):
            r = client.post(
                "/api/v1/diagnostic/session/s1/response",
                json={
                    "learner_id": "learner-1", "tenant_id": TENANT_A,
                    "skill_id": q["skill_id"], "question_x_id": q["question_x_id"],
                    "is_correct": True,
                },
                headers=_auth_headers(),
            )
            assert r.status_code == 200
            result = r.json()["result"]
            if result["session_complete"]:
                verdicts = result["verdicts"]
                break
            q = result["next_question"]
        assert verdicts is not None and len(verdicts) > 0

    def test_raw_response_persisted_and_returned_by_8_4(self, client):
        q = self._start(client)
        first_qxid = q["question_x_id"]
        r = client.post(
            "/api/v1/diagnostic/session/s1/response",
            json={
                "learner_id": "learner-1", "tenant_id": TENANT_A,
                "skill_id": q["skill_id"], "question_x_id": first_qxid,
                "is_correct": True, "raw_response": "42",
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 200
        got = client.get(
            "/api/v1/diagnostic/session/s1/responses", headers=_auth_headers()
        )
        assert got.status_code == 200
        res = got.json()["result"]
        assert res["sub_session_id"] == "s1"
        assert res["learner_id"] == "learner-1"
        first = next(x for x in res["responses"] if x["question_x_id"] == first_qxid)
        assert first["raw_response"] == "42"
        assert first["is_correct"] is True
        assert first["skill_id"] == q["skill_id"]

    def test_8_4_requires_valid_token(self, client):
        self._start(client)
        r = client.get(
            "/api/v1/diagnostic/session/s1/responses",
            headers={"X-Internal-Service-Token": "not-a-real-token"},
        )
        assert r.status_code == 401
