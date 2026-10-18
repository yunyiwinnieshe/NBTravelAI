"""Offline integration checks for Duffel-backed origin resolution."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from travel_ai.clients.duffel import DuffelClient, DuffelSettings
from travel_ai.main import create_app
from travel_ai.providers.duffel import DuffelAirportPlaceProvider
from travel_ai.routers.trip_sessions import get_trip_session_service
from travel_ai.schemas.preference_extraction import (
    PreferenceExtractionResult,
    PreferenceExtractionStatus,
)
from travel_ai.schemas.sessions import TravelerPreferencesDraft, TripRequestDraft
from travel_ai.services.live_origin_resolution import (
    DuffelOriginResolver,
    OriginResolutionError,
    SQLiteLocationStore,
)
from travel_ai.services.preference_extraction import FixturePreferenceExtractor
from travel_ai.services.recommendation_service import RecommendationService
from travel_ai.services.trip_session_service import TripSessionService


def airport(
    code: str, name: str, place_id: str, city_name: str | None = None
) -> dict[str, object]:
    return {
        "id": place_id,
        "type": "airport",
        "iata_code": code,
        "name": name,
        "city_name": city_name or name,
        "iata_country_code": "US",
        "latitude": 42.0,
        "longitude": -71.0,
        "time_zone": "America/New_York",
    }


def city(name: str, code: str, place_id: str, airports: list[dict]) -> dict:
    return {
        "id": place_id,
        "type": "city",
        "iata_code": code,
        "name": name,
        "iata_country_code": "US",
        "latitude": 42.0,
        "longitude": -71.0,
        "airports": airports,
    }


def resolver(tmp_path: Path, responses: dict[str, list[dict]]) -> DuffelOriginResolver:
    def handle(request: httpx.Request) -> httpx.Response:
        query = request.url.params["query"]
        if query == "error":
            return httpx.Response(503, json={"errors": []})
        return httpx.Response(200, json={"data": responses.get(query, [])})

    client = DuffelClient(
        DuffelSettings(access_token="duffel_test_not_a_real_token"),
        http_client=httpx.Client(
            base_url="https://api.duffel.com",
            transport=httpx.MockTransport(handle),
        ),
    )
    return DuffelOriginResolver(
        DuffelAirportPlaceProvider(client),
        SQLiteLocationStore(tmp_path / "locations.sqlite3"),
    )


def sample_responses() -> dict[str, list[dict]]:
    pdx = airport("PDX", "Portland International", "arp_pdx_us")
    pwm = airport("PWM", "Portland International Jetport", "arp_pwm_us")
    bos = airport("BOS", "Logan International", "arp_bos_us")
    bnh = airport("BNH", "Boston Harbor Seaplane", "arp_bnh_us")
    mht = airport("MHT", "Manchester-Boston Regional", "arp_mht_us")
    psm = airport("PSM", "Portsmouth International", "arp_psm_us")
    pvd = airport("PVD", "Rhode Island T. F. Green", "arp_pvd_us")
    return {
        "Portland": [
            city("Portland", "PDX", "cit_pdx_us", [pdx]),
            city("Portland", "PWM", "cit_pwm_us", [pwm]),
        ],
        "Boston": [city("Boston", "BOS", "cit_bos_us", [bnh, bos, mht, psm, pvd])],
        "PWM": [pwm],
        "Portland International Jetport": [pwm],
    }


def extraction(origin: str) -> PreferenceExtractionResult:
    return PreferenceExtractionResult(
        draft=TripRequestDraft(
            travelers=[
                TravelerPreferencesDraft(traveler_id="traveler_a", origin=origin),
                TravelerPreferencesDraft(traveler_id="traveler_b"),
            ]
        ),
        status=PreferenceExtractionStatus.READY_FOR_REVIEW,
    )


def test_city_state_filters_ourairports_and_reuses_id_after_resolver_restart(
    tmp_path: Path,
) -> None:
    first = resolver(tmp_path, sample_responses())
    location_id = first.resolve("Portland, OR")
    assert location_id.startswith("loc_")
    assert first.location_store.get_airports(location_id) == ["PDX"]

    restarted = resolver(tmp_path, sample_responses())
    assert restarted.resolve("Portland, OR") == location_id
    assert restarted.resolve("Portland, Oregon") == location_id
    airport_id = restarted.resolve("PWM")
    assert airport_id != location_id
    assert restarted.location_store.get_airports(airport_id) == ["PWM"]
    assert restarted.resolve("Portland International Jetport") == airport_id
    boston_id = restarted.resolve("Boston, MA")
    assert boston_id != airport_id
    assert len(restarted.location_store.get_airports(boston_id)) == 3
    assert "BNH" not in restarted.location_store.get_airports(boston_id)
    assert b"duffel_test_" not in (tmp_path / "locations.sqlite3").read_bytes()


def test_city_state_uses_airport_suggestions_when_duffel_omits_city(
    tmp_path: Path,
) -> None:
    replies = {
        "Portland": [
            airport("PDX", "Portland International Airport", "arp_pdx", "Portland"),
            airport("PWM", "Portland International Jetport", "arp_pwm", "Portland"),
            city("Orlando", "ORL", "cit_orlando", []),
        ]
    }
    service = resolver(tmp_path, replies)
    oregon_id = service.resolve("Portland, OR")
    maine_id = service.resolve("Portland, ME")
    assert service.location_store.get_airports(oregon_id) == ["PDX"]
    assert service.location_store.get_airports(maine_id) == ["PWM"]
    assert service.resolve("Portland, Oregon") == oregon_id

    city_result = resolver(tmp_path, sample_responses())
    assert city_result.resolve("Portland, OR") == oregon_id


def test_rejects_wrong_state_foreign_and_ineligible_airports(
    tmp_path: Path,
) -> None:
    foreign = airport("YYZ", "Toronto Pearson", "arp_yyz", "Toronto")
    foreign["iata_country_code"] = "CA"
    replies = {
        "Portland": [
            airport("PDX", "Portland International", "arp_pdx", "Portland"),
        ],
        "YYZ": [foreign],
        "BNH": [airport("BNH", "Boston Harbor Seaplane", "arp_bnh", "Boston")],
        "PDX": [airport("PDX", "Portland International", "arp_pdx", "Portland")],
    }
    service = resolver(tmp_path, replies)

    with pytest.raises(OriginResolutionError, match="Portland, ME"):
        service.resolve("Portland, ME")
    with pytest.raises(OriginResolutionError, match="eligible US commercial"):
        service.resolve("YYZ")
    with pytest.raises(OriginResolutionError, match="scheduled commercial"):
        service.resolve("BNH")
    assert service.location_store.get_airports(service.resolve("PDX")) == ["PDX"]

    with pytest.raises(OriginResolutionError, match="Which US state"):
        service.resolve("Portland, Atlantis")


def test_requires_state_and_does_not_store_ambiguous_place(tmp_path: Path) -> None:
    spi = airport("SPI", "Springfield Airport", "arp_spi_us")
    replies = {
        "Springfield": [
            city("Springfield", "SPI", "cit_spi_one_us", [spi]),
            city("Springfield", "SPI", "cit_spi_two_us", [spi]),
        ]
    }
    service = resolver(tmp_path, replies)
    with pytest.raises(OriginResolutionError, match="city and state"):
        service.resolve("Springfield")
    with pytest.raises(OriginResolutionError, match="Which location"):
        service.resolve("Springfield, IL")
    assert service.location_store.get_airports("loc_not_saved") is None


def test_concurrent_workers_reuse_one_location_id(tmp_path: Path) -> None:
    first = resolver(tmp_path, sample_responses())
    second = resolver(tmp_path, sample_responses())
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda item: item.resolve("Portland, OR"), (first, second)))
    assert ids[0] == ids[1]


def test_http_clarification_retains_origin_and_traveler_context(tmp_path: Path) -> None:
    origin_resolver = resolver(tmp_path, sample_responses())
    service = TripSessionService(
        FixturePreferenceExtractor(
            {
                "Boston": extraction("Boston, MA"),
                "Portland without state": extraction("Portland"),
            }
        ),
        RecommendationService(),
        origin_resolver,
    )
    app = create_app()
    app.dependency_overrides[get_trip_session_service] = lambda: service
    with TestClient(app) as client:
        first = client.post("/trip-sessions", json={"initial_message": "Boston"})
        assert first.status_code == 200
        previous = first.json()["trip_request_draft"]["travelers"][0]
        response = client.post(
            f"/trip-sessions/{first.json()['session_id']}/messages",
            json={"message": "Portland without state"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["trip_request_draft"]["travelers"][0] == previous
    question = next(
        item
        for item in body["pending_questions"]
        if item["field_path"] == "travelers.traveler_a.origin"
    )
    assert question["source_message"] == "Portland without state"
    assert "city and state" in question["question"]


def test_http_success_saves_new_origin_and_reuses_it_without_searching_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin_resolver = resolver(tmp_path, sample_responses())
    service = TripSessionService(
        FixturePreferenceExtractor(
            {
                "Boston": extraction("Boston, MA"),
                "Portland": extraction("Portland, OR"),
            }
        ),
        RecommendationService(),
        origin_resolver,
    )
    app = create_app()
    app.dependency_overrides[get_trip_session_service] = lambda: service
    with TestClient(app) as client:
        first = client.post("/trip-sessions", json={"initial_message": "Boston"})
        session_id = first.json()["session_id"]
        before = first.json()["trip_request_draft"]
        changed = client.post(
            f"/trip-sessions/{session_id}/messages", json={"message": "Portland"}
        )
        assert changed.status_code == 200
        after = changed.json()["trip_request_draft"]
        assert after["travelers"][0]["origin"] == "Portland, OR"
        assert after["travelers"][0]["origin_id"] != before["travelers"][0]["origin_id"]
        assert after["travelers"][1] == before["travelers"][1]

        def unexpected_search(_origin: str) -> str:
            raise AssertionError("unchanged resolved origin should not search again")

        monkeypatch.setattr(origin_resolver, "resolve", unexpected_search)
        repeated = client.post(
            f"/trip-sessions/{session_id}/messages", json={"message": "Portland"}
        )
        assert repeated.status_code == 200
        assert repeated.json()["trip_request_draft"] == after


def test_provider_failure_and_failed_location_write_keep_previous_session_draft(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin_resolver = resolver(tmp_path, sample_responses())
    extractor = FixturePreferenceExtractor(
        {
            "Boston": extraction("Boston, MA"),
            "Portland": extraction("Portland, OR"),
            "Provider error": extraction("error, MA"),
        }
    )
    service = TripSessionService(extractor, RecommendationService(), origin_resolver)
    session_id = service.create_session(None).session_id
    first = service.add_message(session_id, "Boston")
    saved_id = first.trip_request_draft.travelers[0].origin_id

    def fail_save(**_kwargs: object) -> str:
        raise sqlite3.OperationalError("simulated failed write")

    monkeypatch.setattr(origin_resolver.location_store, "save", fail_save)
    app = create_app()
    app.dependency_overrides[get_trip_session_service] = lambda: service
    with TestClient(app) as client:
        write_response = client.post(
            f"/trip-sessions/{session_id}/messages", json={"message": "Portland"}
        )
        provider_response = client.post(
            f"/trip-sessions/{session_id}/messages",
            json={"message": "Provider error"},
        )
    assert write_response.status_code == 503
    assert write_response.json()["detail"]["code"] == "origin_storage_unavailable"
    assert service._get_session(session_id).draft.travelers[0].origin_id == saved_id
    assert provider_response.status_code == 503
    assert provider_response.json()["detail"]["code"] == (
        "origin_resolution_unavailable"
    )
    assert service._get_session(session_id).draft.travelers[0].origin == "Boston, MA"


def test_resolved_origin_without_fixture_flights_returns_cached_coverage_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    origin_resolver = resolver(tmp_path, sample_responses())
    from datetime import date

    complete = PreferenceExtractionResult(
        draft=TripRequestDraft(
            travelers=[
                TravelerPreferencesDraft(
                    traveler_id="traveler_a",
                    origin="Portland, OR",
                    budget_usd=500,
                    max_travel_time_hours=10,
                ),
                TravelerPreferencesDraft(
                    traveler_id="traveler_b",
                    origin="Boston, MA",
                    budget_usd=500,
                    max_travel_time_hours=10,
                ),
            ],
            start_date=date(2099, 6, 10),
            end_date=date(2099, 6, 14),
        ),
        status=PreferenceExtractionStatus.READY_FOR_REVIEW,
    )
    recommendations = RecommendationService()
    calls = 0
    original = recommendations.get_recommendations

    def counted(*args: object, **kwargs: object):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(recommendations, "get_recommendations", counted)
    service = TripSessionService(
        FixturePreferenceExtractor({"complete": complete}),
        recommendations,
        origin_resolver,
    )
    session_id = service.create_session("complete").session_id
    first = service.confirm_session(session_id)
    second = service.confirm_session(session_id)
    assert first == second
    assert first.state == "no_match"
    assert "configured flight provider has no coverage" in first.assistant_message
    assert calls == 1
