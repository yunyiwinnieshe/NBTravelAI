"""HTTP integration coverage for the offline recommendation service."""

import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from travel_ai.clients.duffel import DuffelClient
from travel_ai.main import create_app
from travel_ai.providers.fixtures import FixtureFlightOfferProvider
from travel_ai.routers.recommendations import get_recommendation_service
from travel_ai.schemas.flights import FlightOffer, FlightSearchQuery
from travel_ai.schemas.recommendations import RecommendationResponse
from travel_ai.services.recommendation_service import RecommendationService

EVALUATED_AT = datetime(2026, 9, 19, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def forbid_external_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail before Duffel or real HTTP/socket traffic; TestClient is in-process."""

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Fixture API tests must not call Duffel or external networks")

    monkeypatch.setattr(DuffelClient, "create_offer_request", forbidden)
    monkeypatch.setattr(DuffelClient, "get_place_suggestions", forbidden)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)


@pytest.fixture
def api_client() -> Iterator[TestClient]:
    """Use an isolated app with the real workflow and a fixed metadata clock."""
    app = create_app()
    service = RecommendationService(clock=lambda: EVALUATED_AT)
    app.dependency_overrides[get_recommendation_service] = lambda: service
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def trip_payload(budget: int = 500) -> dict[str, Any]:
    return {
        "start_date": "2099-06-10",
        "end_date": "2099-06-14",
        "travelers": [
            {
                "traveler_id": traveler_id,
                "origin_id": origin_id,
                "budget_usd": budget,
                "max_one_way_travel_minutes": 600,
                "preferences": {"interest_tags": ["food"]},
            }
            for traveler_id, origin_id in (
                ("alice", "boston_ma"),
                ("bob", "new_york_ny"),
            )
        ],
    }


@pytest.mark.parametrize(
    ("budget", "expected_cities"),
    [
        (500, {"chicago_il", "miami_fl", "seattle_wa"}),
        (300, {"chicago_il", "miami_fl"}),
        (260, {"miami_fl"}),
        (1, set()),
    ],
)
def test_api_returns_exact_eligible_results(
    api_client: TestClient,
    budget: int,
    expected_cities: set[str],
) -> None:
    response = api_client.post("/recommendations", json=trip_payload(budget))
    assert response.status_code == 200
    body = response.json()
    validated = RecommendationResponse.model_validate(body)
    assert body["status"] == ("success" if expected_cities else "no_match")
    assert {
        r["destination"]["destination_id"] for r in body["recommendations"]
    } == expected_cities
    assert len(body["recommendations"]) == len(expected_cities)
    assert [r["rank"] for r in body["recommendations"]] == list(
        range(1, len(expected_cities) + 1)
    )
    assert validated.metadata.eligible_destination_count == len(expected_cities)
    assert validated.metadata.data_mode == "fixture"
    assert validated.metadata.evaluated_at == EVALUATED_AT
    for recommendation in validated.recommendations:
        assert {
            group.traveler_id for group in recommendation.flight_options_by_traveler
        } == {"alice", "bob"}
    assert all(e.destination_id not in expected_cities for e in validated.exclusions)
    if not expected_cities:
        assert body["exclusions"]


def test_api_reports_traveler_specific_exclusions(api_client: TestClient) -> None:
    body = api_client.post("/recommendations", json=trip_payload()).json()
    denver = [e for e in body["exclusions"] if e["destination_id"] == "denver_co"]
    assert denver == [
        {
            "destination_id": "denver_co",
            "traveler_id": traveler_id,
            "reason_code": "no_eligible_flight",
        }
        for traveler_id in ("alice", "bob")
    ]


class IncompatibleAirportProvider(FixtureFlightOfferProvider):
    """Return eligible Chicago offers at different airports for the two travelers."""

    def search(self, query: FlightSearchQuery) -> list[FlightOffer]:
        offers = super().search(query)
        if query.destination_id == "chicago_il" and query.origin_id == "new_york_ny":
            for offer in offers:
                offer.outbound_slice.destination_airport_code = "MDW"
                offer.outbound_slice.segments[-1].destination_airport_code = "MDW"
                offer.return_slice.origin_airport_code = "MDW"
                offer.return_slice.segments[0].origin_airport_code = "MDW"
        return offers


def test_api_reports_pair_exclusions_without_blaming_one_traveler() -> None:
    app = create_app()
    service = RecommendationService(flight_provider=IncompatibleAirportProvider())
    app.dependency_overrides[get_recommendation_service] = lambda: service
    with TestClient(app) as client:
        response = client.post("/recommendations", json=trip_payload())
    assert response.status_code == 200
    body = response.json()
    assert len(body["recommendations"]) == 2
    assert [e for e in body["exclusions"] if e["destination_id"] == "chicago_il"] == [
        {
            "destination_id": "chicago_il",
            "traveler_id": None,
            "reason_code": "no_compatible_flight_pair",
        }
    ]


def test_api_repeated_requests_are_identical(api_client: TestClient) -> None:
    first = api_client.post("/recommendations", json=trip_payload())
    # Interleave another request to expose state leaking through the cached service.
    no_match = api_client.post("/recommendations", json=trip_payload(1))
    repeated = api_client.post("/recommendations", json=trip_payload())
    assert first.status_code == repeated.status_code == no_match.status_code == 200
    assert no_match.json()["status"] == "no_match"
    assert first.json() == repeated.json()


@pytest.mark.parametrize(
    "invalid_case", ["one_traveler", "negative_budget", "bad_dates", "missing_origin"]
)
def test_api_rejects_invalid_requests_before_workflow(
    invalid_case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_workflow(trip_request: object) -> None:
        pytest.fail("Invalid request reached recommendation workflow")

    service = RecommendationService()
    monkeypatch.setattr(service, "get_recommendations", unexpected_workflow)
    app = create_app()
    app.dependency_overrides[get_recommendation_service] = lambda: service
    payload = trip_payload()
    if invalid_case == "one_traveler":
        payload["travelers"].pop()
    elif invalid_case == "negative_budget":
        payload["travelers"][0]["budget_usd"] = -1
    elif invalid_case == "bad_dates":
        payload["end_date"] = "2099-06-01"
    else:
        del payload["travelers"][0]["origin_id"]
    with TestClient(app) as client:
        response = client.post("/recommendations", json=payload)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_default_api_dependency_is_offline_without_duffel_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DUFFEL_ACCESS_TOKEN", raising=False)
    get_recommendation_service.cache_clear()
    try:
        with TestClient(create_app()) as client:
            response = client.post("/recommendations", json=trip_payload())
        assert response.status_code == 200
        assert len(response.json()["recommendations"]) == 3
        assert response.json()["metadata"]["data_mode"] == "fixture"
    finally:
        get_recommendation_service.cache_clear()
