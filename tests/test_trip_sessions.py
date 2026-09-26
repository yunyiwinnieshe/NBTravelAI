"""API coverage for the fixture-backed conversational planning flow."""

import pytest
from fastapi.testclient import TestClient

from travel_ai.main import create_app
from travel_ai.routers.trip_sessions import get_trip_session_service

ORIGINS_MESSAGE = "Alice is leaving from Boston and Bob is leaving from New York."
DETAILS_MESSAGE = (
    "We will travel June 10 to June 14, 2099. Alice and Bob each have a $500 "
    "budget and can travel up to 10 hours."
)


@pytest.fixture
def client() -> TestClient:
    """Use a fresh in-memory session store for every test."""
    get_trip_session_service.cache_clear()
    with TestClient(create_app()) as test_client:
        yield test_client
    get_trip_session_service.cache_clear()


def test_fixture_conversation_collects_reviews_and_confirms(client: TestClient) -> None:
    """Fixture extraction reaches real fixture recommendations after confirmation."""
    collecting = client.post(
        "/trip-sessions",
        json={"initial_message": ORIGINS_MESSAGE},
    )

    assert collecting.status_code == 200
    collecting_body = collecting.json()
    assert collecting_body["state"] == "collecting"
    assert [
        traveler["traveler_id"]
        for traveler in collecting_body["trip_request_draft"]["travelers"]
    ] == ["traveler_a", "traveler_b"]
    assert [
        t["display_name"] for t in collecting_body["trip_request_draft"]["travelers"]
    ] == ["Alice", "Bob"]
    assert len(collecting_body["missing_fields"]) == 6

    session_id = collecting_body["session_id"]
    review = client.post(
        f"/trip-sessions/{session_id}/messages",
        json={"message": DETAILS_MESSAGE},
    )

    assert review.status_code == 200
    assert review.json()["state"] == "review"
    assert review.json()["missing_fields"] == []

    confirmed = client.post(
        f"/trip-sessions/{session_id}/messages", json={"action": "confirm"}
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["state"] == "results"
    assert len(confirmed.json()["recommendations"]) == 3


def test_session_cannot_confirm_before_review(client: TestClient) -> None:
    """Recommendations only run after a complete draft is explicitly confirmed."""
    session_id = client.post("/trip-sessions", json={}).json()["session_id"]

    response = client.post(
        f"/trip-sessions/{session_id}/messages", json={"action": "confirm"}
    )

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "complete the trip details before confirming this session"
    )


def test_session_rejects_unknown_fixture_messages(client: TestClient) -> None:
    """Fixture mode is explicit and never pretends to understand arbitrary text."""
    session_id = client.post("/trip-sessions", json={}).json()["session_id"]

    response = client.post(
        f"/trip-sessions/{session_id}/messages",
        json={"message": "Could you find us a beach trip next spring?"},
    )

    assert response.status_code == 422
    assert "no fixture extraction result" in response.json()["detail"]


def test_session_returns_not_found_for_an_unknown_id(client: TestClient) -> None:
    """Session state is never silently created for an arbitrary URL ID."""
    response = client.post(
        "/trip-sessions/not-a-session/messages",
        json={"message": ORIGINS_MESSAGE},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "trip session was not found"
