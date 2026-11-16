"""Request traces connect stages without retaining traveler input or secrets."""

import json

from fastapi.testclient import TestClient

import travel_ai.services.recommendation_service as recommendation_module
from travel_ai.main import create_app
from travel_ai.providers.fixtures import FixtureFlightOfferProvider
from travel_ai.routers.recommendations import get_recommendation_service
from travel_ai.routers.trip_sessions import get_trip_session_service
from travel_ai.schemas.flights import FlightSearchQuery
from travel_ai.services.recommendation_service import RecommendationService

_AUTH_HEADERS = {"Authorization": "Basic bG9jYWw6dGVzdC1wYXNzd29yZA=="}


def _enable_dashboard(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_LOCAL_AI_DASHBOARD", "1")
    monkeypatch.setenv("LOCAL_AI_DASHBOARD_PASSWORD", "test-password")


def _trip() -> dict:
    return {
        "start_date": "2099-06-10",
        "end_date": "2099-06-14",
        "travelers": [
            {
                "traveler_id": traveler_id,
                "origin_id": origin,
                "budget_usd": 500,
                "max_one_way_travel_minutes": 600,
            }
            for traveler_id, origin in (
                ("traveler_a", "boston_ma"),
                ("traveler_b", "new_york_ny"),
            )
        ],
    }


def test_recommendation_trace_follows_all_stages_without_personal_data(
    monkeypatch,
) -> None:
    _enable_dashboard(monkeypatch)
    with TestClient(create_app(), headers=_AUTH_HEADERS) as client:
        response = client.post("/recommendations", json=_trip())
        assert response.status_code == 200
        trace_id = response.headers["X-Trace-ID"]
        trace = client.get(f"/observability/traces/{trace_id}").json()
        assert trace["trace_id"] == trace_id
        stages = [event["stage"] for event in trace["stages"]]
        assert set(stages) >= {
            "provider", "constraints", "ranking",
            "explanation", "response_validation", "response",
        }
        assert all("cache" not in s for s in trace["stages"])
        provider_versions = {
            event["version"] for event in trace["stages"]
            if event["stage"] == "provider"
        }
        assert len(provider_versions) == 2
        assert all(len(version) == 12 for version in provider_versions)
        assert trace["stages"][-1]["http_status"] == 200
        assert all(event["trace_id"] == trace_id for event in trace["stages"])
        assert all(event["latency_ms"] >= 0 for event in trace["stages"])
        assert "boston_ma" not in json.dumps(trace)
        assert "new_york_ny" not in json.dumps(trace)
        assert client.get("/observability/dashboard").status_code == 200


def test_session_confirmation_reports_cache_hit(monkeypatch) -> None:
    _enable_dashboard(monkeypatch)
    get_trip_session_service.cache_clear()
    try:
        with TestClient(create_app(), headers=_AUTH_HEADERS) as client:
            start = client.post(
                "/trip-sessions",
                json={"initial_message": (
                    "Alice is leaving from Boston and Bob is leaving from New York."
                )},
            )
            session_id = start.json()["session_id"]
            extraction = client.get(
                f"/observability/traces/{start.headers['X-Trace-ID']}"
            ).json()
            assert "extraction" in [s["stage"] for s in extraction["stages"]]
            client.post(
                f"/trip-sessions/{session_id}/messages",
                json={"message": (
                    "We will travel June 10 to June 14, 2099. Alice and Bob "
                    "each have a $500 budget and can travel up to 10 hours."
                )},
            )
            confirm = client.post(
                f"/trip-sessions/{session_id}/messages",
                json={"action": "confirm"},
            )
            assert confirm.status_code == 200
            first = client.get(
                f"/observability/traces/{confirm.headers['X-Trace-ID']}"
            ).json()
            assert any(
                s["stage"] == "recommendation_cache" and s["cache"] == "miss"
                for s in first["stages"]
            )
            assert any(s["stage"] == "ranking" for s in first["stages"])
            repeat = client.post(
                f"/trip-sessions/{session_id}/messages",
                json={"action": "confirm"},
            )
            second = client.get(
                f"/observability/traces/{repeat.headers['X-Trace-ID']}"
            ).json()
            assert any(
                s["stage"] == "recommendation_cache" and s["cache"] == "hit"
                for s in second["stages"]
            )
    finally:
        get_trip_session_service.cache_clear()


def test_provider_error_retains_trace_id_without_error_details(monkeypatch) -> None:
    _enable_dashboard(monkeypatch)

    class FailingProvider(FixtureFlightOfferProvider):
        def search(self, query: FlightSearchQuery):
            raise RuntimeError("private provider diagnostic")

    app = create_app()
    app.dependency_overrides[get_recommendation_service] = lambda: (
        RecommendationService(flight_provider=FailingProvider())
    )
    with TestClient(app, headers=_AUTH_HEADERS) as client:
        response = client.post("/recommendations", json=_trip())
        assert response.status_code == 500
        trace = client.get(
            f"/observability/traces/{response.headers['X-Trace-ID']}"
        ).json()
        assert any(
            s["stage"] == "provider" and s.get("error_type") == "RuntimeError"
            for s in trace["stages"]
        )
        assert trace["stages"][-1]["http_status"] == 500
        assert "private provider diagnostic" not in json.dumps(trace)
        assert "private provider diagnostic" not in response.text


def test_explanation_failure_keeps_scores_and_records_error(monkeypatch) -> None:
    _enable_dashboard(monkeypatch)

    def fail_explanation(_recommendation):
        raise RuntimeError("private explanation diagnostic")

    monkeypatch.setattr(recommendation_module, "build_explanation", fail_explanation)
    with TestClient(create_app(), headers=_AUTH_HEADERS) as client:
        response = client.post("/recommendations", json=_trip())
        assert response.status_code == 200
        assert response.json()["status"] == "success"
        assert all(
            result["explanation"] is None
            for result in response.json()["recommendations"]
        )
        trace = client.get(
            f"/observability/traces/{response.headers['X-Trace-ID']}"
        ).json()
        assert any(
            stage["stage"] == "explanation"
            and stage["status"] == "error"
            and stage["validation"] == "failed"
            for stage in trace["stages"]
        )
        assert "private explanation diagnostic" not in json.dumps(trace)


def test_trace_lookup_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_LOCAL_AI_DASHBOARD", raising=False)
    with TestClient(create_app()) as client:
        assert client.get("/observability/traces").status_code == 404


def test_trace_lookup_requires_password(monkeypatch) -> None:
    _enable_dashboard(monkeypatch)
    with TestClient(create_app()) as client:
        for path in (
            "/observability/traces",
            "/observability/traces/unknown",
            "/observability/ai-calls",
            "/observability/dashboard",
        ):
            assert client.get(path).status_code == 401
            assert client.get(path, auth=("local", "wrong")).status_code == 401
