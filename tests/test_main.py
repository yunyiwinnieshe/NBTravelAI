"""HTTP contract tests for the FastAPI application."""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from travel_ai.main import app

client = TestClient(app)


def valid_trip_request() -> dict[str, object]:
    """Return a request that meets the v1 two-traveler trip contract."""
    start_date = date.today() + timedelta(days=30)
    end_date = start_date + timedelta(days=4)

    return {
        "travelers": [
            {
                "traveler_id": "traveler_a",
                "origin_id": "boston_ma",
                "budget_usd": 2000,
                "max_one_way_travel_minutes": 480,
                "preferences": {
                    "temperature_range": {
                        "minimum_celsius": 20,
                        "maximum_celsius": 30,
                    },
                    "interest_tags": ["food", "museums"],
                },
            },
            {
                "traveler_id": "traveler_b",
                "origin_id": "new_york_ny",
                "budget_usd": 2000,
                "max_one_way_travel_minutes": 480,
                "preferences": {
                    "interest_tags": ["mountain", "outdoor_activities"],
                },
            },
        ],
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


def test_health_check_returns_ok() -> None:
    """The liveness endpoint is available without application dependencies."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_recommendations_returns_no_match_for_dates_without_fixtures() -> None:
    response = client.post("/recommendations", json=valid_trip_request())
    assert response.status_code == 200
    assert response.json()["status"] == "no_match"


def test_recommendations_returns_fixture_results_through_api() -> None:
    request = valid_trip_request()
    request.update(start_date="2099-06-10", end_date="2099-06-14")
    response = client.post("/recommendations", json=request)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert 1 <= len(body["recommendations"]) <= 3
    assert body["metadata"]["data_mode"] == "fixture"


def test_recommendations_rejects_unsupported_fixture_origin() -> None:
    request = valid_trip_request()
    request["travelers"][0]["origin_id"] = "unknown_city"
    response = client.post("/recommendations", json=request)
    assert response.status_code == 422
    assert "origin ID is not configured" in response.json()["detail"]


def test_recommendations_rejects_a_request_without_two_travelers() -> None:
    """The v1 API requires exactly two travelers."""
    request = valid_trip_request()
    request["travelers"] = request["travelers"][:1]  # type: ignore[index]

    response = client.post("/recommendations", json=request)

    assert response.status_code == 422


def test_recommendations_rejects_an_invalid_trip_length() -> None:
    """The initial scope accepts only trips from three through seven days."""
    request = valid_trip_request()
    start_date = date.fromisoformat(str(request["start_date"]))
    request["end_date"] = (start_date + timedelta(days=7)).isoformat()

    response = client.post("/recommendations", json=request)

    assert response.status_code == 422


def test_recommendations_rejects_a_trip_with_a_past_start_date() -> None:
    """Past trips are outside the v1 planning scope."""
    start_date = date.today() - timedelta(days=7)
    request = valid_trip_request()
    request["start_date"] = start_date.isoformat()
    request["end_date"] = (start_date + timedelta(days=4)).isoformat()

    response = client.post("/recommendations", json=request)

    assert response.status_code == 422


def test_recommendations_rejects_duplicate_traveler_ids() -> None:
    """Each traveler needs a stable, unique identifier within the request."""
    request = valid_trip_request()
    request["travelers"][1]["traveler_id"] = "traveler_a"  # type: ignore[index]

    response = client.post("/recommendations", json=request)

    assert response.status_code == 422


def test_recommendations_rejects_the_same_resolved_origin() -> None:
    """V1 is limited to travelers departing from different resolved origins."""
    request = valid_trip_request()
    request["travelers"][1]["origin_id"] = "boston_ma"  # type: ignore[index]

    response = client.post("/recommendations", json=request)

    assert response.status_code == 422


def test_trip_session_starts_collecting_without_an_initial_message() -> None:
    """A new fixture session is ready to collect the first planning detail."""
    response = client.post("/trip-sessions", json={})

    assert response.status_code == 200
    assert response.json()["state"] == "collecting"
    assert len(response.json()["missing_fields"]) == 8
    assert response.json()["assistant_message"] == "What is your start date?"
