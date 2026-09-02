"""HTTP contract tests for the FastAPI application."""

from fastapi.testclient import TestClient

from travel_ai.main import app

client = TestClient(app)


def valid_trip_request() -> dict[str, object]:
    """Return a request that meets the v1 two-traveler trip contract."""
    return {
        "travelers": [
            {
                "origin": "Boston, MA",
                "budget_usd": 2000,
                "max_travel_time_hours": 8,
                "preferences": {
                    "temperature_range": {
                        "minimum_celsius": 20,
                        "maximum_celsius": 30,
                    },
                    "interest_tags": ["food", "museums"],
                },
            },
            {
                "origin": "San Francisco, CA",
                "budget_usd": 2000,
                "max_travel_time_hours": 8,
                "preferences": {
                    "interest_tags": ["mountain", "outdoor_activities"],
                },
            },
        ],
        "start_date": "2026-10-09",
        "end_date": "2026-10-13",
    }


def test_health_check_returns_ok() -> None:
    """The liveness endpoint is available without application dependencies."""
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_recommendations_validates_and_returns_placeholder() -> None:
    """A valid request reaches the placeholder while ranking is not implemented."""
    response = client.post("/recommendations", json=valid_trip_request())

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_implemented",
        "recommendations": [],
        "message": (
            "Trip request is valid. Deterministic destination ranking "
            "will be added in Week 2."
        ),
    }


def test_recommendations_rejects_a_request_without_two_travelers() -> None:
    """The v1 API requires exactly two travelers."""
    request = valid_trip_request()
    request["travelers"] = request["travelers"][:1]  # type: ignore[index]

    response = client.post("/recommendations", json=request)

    assert response.status_code == 422


def test_recommendations_rejects_an_invalid_trip_length() -> None:
    """The initial scope accepts only trips from three through seven days."""
    request = valid_trip_request()
    request["end_date"] = "2026-10-20"

    response = client.post("/recommendations", json=request)

    assert response.status_code == 422


def test_trip_session_routes_are_explicitly_not_implemented() -> None:
    """Conversation routes are documented before session storage is introduced."""
    response = client.post("/trip-sessions", json={"initial_message": "Help us plan."})

    assert response.status_code == 501
    assert response.json() == {
        "detail": "Trip sessions will be implemented with the LLM workflow in Week 4."
    }
