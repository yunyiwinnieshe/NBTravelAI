"""Tests for Duffel request mapping, errors, and offer normalization."""

import json
from datetime import UTC, date, datetime

import httpx
import pytest

from travel_ai.clients.duffel import (
    DuffelApiError,
    DuffelAuthenticationError,
    DuffelClient,
    DuffelConfigurationError,
    DuffelRateLimitError,
    DuffelResponseError,
    DuffelSettings,
)
from travel_ai.providers.duffel import (
    DuffelAirportPlaceProvider,
    DuffelFlightOfferProvider,
)
from travel_ai.schemas.flights import FlightSearchQuery
from travel_ai.schemas.locations import LocationSearchQuery

EVALUATED_AT = datetime(2099, 6, 1, 12, tzinfo=UTC)


def search_query(
    origin_airport_codes: list[str] | None = None,
    destination_airport_codes: list[str] | None = None,
) -> FlightSearchQuery:
    """Return a query suitable for the representative Duffel response."""
    return FlightSearchQuery(
        traveler_id="traveler_a",
        origin_id="boston_ma",
        destination_id="chicago_il",
        origin_airport_codes=origin_airport_codes or ["BOS"],
        destination_airport_codes=destination_airport_codes or ["ORD"],
        departure_date=date(2099, 6, 10),
        return_date=date(2099, 6, 14),
    )


def raw_offer(
    *,
    offer_id: str = "off_test_123",
    amount: str = "324.00",
    currency: str = "USD",
) -> dict[str, object]:
    """Return the provider fields Travel AI consumes from one Duffel offer."""
    return {
        "id": offer_id,
        "total_amount": amount,
        "total_currency": currency,
        "expires_at": "2099-06-01T13:00:00Z",
        "slices": [
            {
                "duration": "PT2H30M",
                "segments": [
                    {
                        "origin": {
                            "iata_code": "BOS",
                            "time_zone": "America/New_York",
                        },
                        "destination": {
                            "iata_code": "ORD",
                            "time_zone": "America/Chicago",
                        },
                        "departing_at": "2099-06-10T08:00:00",
                        "arriving_at": "2099-06-10T09:30:00",
                        "marketing_carrier": {"iata_code": "ZZ"},
                        "operating_carrier": {"iata_code": "ZZ"},
                        "marketing_carrier_flight_number": "201",
                    }
                ],
            },
            {
                "duration": "PT2H20M",
                "segments": [
                    {
                        "origin": {
                            "iata_code": "ORD",
                            "time_zone": "America/Chicago",
                        },
                        "destination": {
                            "iata_code": "BOS",
                            "time_zone": "America/New_York",
                        },
                        "departing_at": "2099-06-14T15:00:00",
                        "arriving_at": "2099-06-14T18:20:00",
                        "marketing_carrier": {"iata_code": "ZZ"},
                        "operating_carrier": {"iata_code": "ZZ"},
                        "marketing_carrier_flight_number": "202",
                    }
                ],
            },
        ],
    }


def provider_with_handler(
    handler: httpx.MockTransport,
    *,
    maximum_offers: int = 20,
) -> DuffelFlightOfferProvider:
    """Build a Duffel provider around a network-free HTTP transport."""
    http_client = httpx.Client(
        base_url="https://api.duffel.com",
        transport=handler,
    )
    client = DuffelClient(
        DuffelSettings(access_token="duffel_test_not_a_real_token"),
        http_client=http_client,
    )
    return DuffelFlightOfferProvider(
        client,
        clock=lambda: EVALUATED_AT,
        maximum_offers=maximum_offers,
    )


def place_provider_with_handler(
    handler: httpx.MockTransport,
) -> DuffelAirportPlaceProvider:
    """Build a Duffel Places provider around a network-free HTTP transport."""
    http_client = httpx.Client(
        base_url="https://api.duffel.com",
        transport=handler,
    )
    client = DuffelClient(
        DuffelSettings(access_token="duffel_test_not_a_real_token"),
        http_client=http_client,
    )
    return DuffelAirportPlaceProvider(client)


def test_place_search_expands_city_airports_and_deduplicates_results() -> None:
    """The Boston response becomes unique provider-independent candidates."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/places/suggestions"
        assert request.url.params["query"] == "Boston"
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "cit_bos_us",
                        "type": "city",
                        "iata_code": "BOS",
                        "name": "Boston",
                        "iata_country_code": "US",
                        "airports": [
                            {
                                "id": "arp_bnh_us",
                                "iata_code": "BNH",
                                "name": "Boston Harbor Seaplane Base",
                                "city_name": "Boston",
                                "iata_country_code": "US",
                                "latitude": 42.352509,
                                "longitude": -71.025732,
                                "time_zone": "America/New_York",
                            },
                            {
                                "id": "arp_bos_us",
                                "iata_code": "BOS",
                                "name": "Logan International Airport",
                                "city_name": "Boston",
                                "iata_country_code": "US",
                                "latitude": 42.364956,
                                "longitude": -71.007381,
                                "time_zone": "America/New_York",
                            },
                        ],
                    },
                    {
                        "id": "arp_bos_us",
                        "type": "airport",
                        "iata_code": "BOS",
                        "name": "Logan International Airport",
                        "city_name": "Boston",
                        "iata_country_code": "US",
                        "latitude": 42.364956,
                        "longitude": -71.007381,
                        "time_zone": "America/New_York",
                    },
                ]
            },
        )

    provider = place_provider_with_handler(httpx.MockTransport(handle))

    candidates = provider.search_airports(LocationSearchQuery(query="Boston"))

    assert [candidate.iata_code for candidate in candidates] == ["BNH", "BOS"]
    assert next(
        candidate for candidate in candidates if candidate.iata_code == "BOS"
    ).associated_with_selected_city is True


def test_place_search_supports_coordinate_radius_parameters() -> None:
    """A previously geocoded city can request nearby Duffel airports."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.params["lat"] == "42.3601"
        assert request.url.params["lng"] == "-71.0589"
        assert request.url.params["rad"] == "100000"
        return httpx.Response(200, json={"data": []})

    provider = place_provider_with_handler(httpx.MockTransport(handle))

    candidates = provider.search_airports(
        LocationSearchQuery(
            latitude=42.3601,
            longitude=-71.0589,
            radius_metres=100_000,
        )
    )

    assert candidates == []


def test_search_builds_round_trip_request_and_normalizes_offer() -> None:
    """The adapter sends two slices and returns a provider-independent offer."""

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/air/offer_requests"
        assert request.url.params["return_offers"] == "true"
        assert request.url.params["supplier_timeout"] == "10000"
        assert request.headers["Duffel-Version"] == "v2"
        assert request.headers["Authorization"] == (
            "Bearer duffel_test_not_a_real_token"
        )
        assert json.loads(request.content) == {
            "data": {
                "cabin_class": "economy",
                "slices": [
                    {
                        "origin": "BOS",
                        "destination": "ORD",
                        "departure_date": "2099-06-10",
                    },
                    {
                        "origin": "ORD",
                        "destination": "BOS",
                        "departure_date": "2099-06-14",
                    },
                ],
                "passengers": [{"type": "adult"}],
            }
        }
        return httpx.Response(201, json={"data": {"offers": [raw_offer()]}})

    provider = provider_with_handler(httpx.MockTransport(handle))

    offers = provider.search(search_query())

    assert len(offers) == 1
    offer = offers[0]
    assert offer.provider == "duffel"
    assert offer.provider_offer_id == "off_test_123"
    assert offer.offer_id.startswith("duffel_")
    assert offer.total_amount == 324
    assert offer.outbound_slice.duration_minutes == 150
    assert offer.return_slice.duration_minutes == 140
    assert offer.outbound_slice.segments[0].departure_at.tzinfo is not None
    assert offer.outbound_slice.segments[0].arrival_at.tzinfo is not None
    assert offer.outbound_slice.segments[0].departure_at.utcoffset() != (
        offer.outbound_slice.segments[0].arrival_at.utcoffset()
    )
    assert offer.is_round_trip_nonstop is True
    assert offer.is_fixture is False


def test_search_expands_airport_pairs_and_deduplicates_provider_ids() -> None:
    """Repeated provider offers appear once after all approved pairs are searched."""
    request_count = 0

    def handle(_request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(201, json={"data": {"offers": [raw_offer()]}})

    provider = provider_with_handler(httpx.MockTransport(handle))

    offers = provider.search(
        search_query(
            origin_airport_codes=["BOS", "PVD"],
            destination_airport_codes=["ORD", "MDW"],
        )
    )

    assert request_count == 4
    assert len(offers) == 1


def test_search_applies_offer_limit_with_lowest_price_first() -> None:
    """A one-offer bound retains the deterministic lowest-price winner."""

    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            json={
                "data": {
                    "offers": [
                        raw_offer(offer_id="off_expensive", amount="500.00"),
                        raw_offer(offer_id="off_cheapest", amount="250.00"),
                    ]
                }
            },
        )

    provider = provider_with_handler(httpx.MockTransport(handle), maximum_offers=1)

    offers = provider.search(search_query())

    assert [offer.provider_offer_id for offer in offers] == ["off_cheapest"]


def test_search_bound_retains_price_and_travel_time_winners() -> None:
    """The bounded set is diversified instead of containing only cheap offers."""
    cheapest = raw_offer(offer_id="off_cheapest", amount="250.00")
    fastest = raw_offer(offer_id="off_fastest", amount="400.00")
    fastest["slices"][0]["duration"] = "PT1H"  # type: ignore[index]
    fastest["slices"][1]["duration"] = "PT1H"  # type: ignore[index]

    provider = provider_with_handler(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                201,
                json={"data": {"offers": [cheapest, fastest]}},
            )
        ),
        maximum_offers=2,
    )

    offers = provider.search(search_query())

    assert [offer.provider_offer_id for offer in offers] == [
        "off_cheapest",
        "off_fastest",
    ]


def test_search_returns_empty_list_when_duffel_has_no_offers() -> None:
    """A successful search with no availability is not a provider failure."""
    provider = provider_with_handler(
        httpx.MockTransport(
            lambda _request: httpx.Response(201, json={"data": {"offers": []}})
        )
    )

    assert provider.search(search_query()) == []


@pytest.mark.parametrize(
    ("status_code", "expected_error"),
    [
        (401, DuffelAuthenticationError),
        (403, DuffelAuthenticationError),
        (429, DuffelRateLimitError),
        (500, DuffelApiError),
    ],
)
def test_client_translates_http_errors(
    status_code: int,
    expected_error: type[Exception],
) -> None:
    """Provider-specific HTTP failures become stable application errors."""
    provider = provider_with_handler(
        httpx.MockTransport(
            lambda _request: httpx.Response(
                status_code,
                headers={"x-request-id": "request_123"},
                json={"errors": []},
            )
        )
    )

    with pytest.raises(expected_error, match="request_123"):
        provider.search(search_query())


def test_client_translates_timeout_without_exposing_token() -> None:
    """Transport messages remain controlled and do not include credentials."""

    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("provider timeout", request=request)

    provider = provider_with_handler(httpx.MockTransport(handle))

    with pytest.raises(DuffelApiError, match="timed out") as captured:
        provider.search(search_query())

    assert "duffel_test" not in str(captured.value)


@pytest.mark.parametrize(
    "response",
    [
        {"unexpected": "shape"},
        {"data": {"offers": [raw_offer(currency="GBP")]}},
        {
            "data": {
                "offers": [
                    {
                        **raw_offer(),
                        "slices": [
                            {
                                **raw_offer()["slices"][0],  # type: ignore[index]
                                "duration": "not-a-duration",
                            },
                            raw_offer()["slices"][1],  # type: ignore[index]
                        ],
                    }
                ]
            }
        },
    ],
)
def test_search_rejects_unusable_provider_data(response: dict[str, object]) -> None:
    """Malformed or unsupported provider data cannot enter deterministic ranking."""
    provider = provider_with_handler(
        httpx.MockTransport(lambda _request: httpx.Response(201, json=response))
    )

    with pytest.raises(DuffelResponseError):
        provider.search(search_query())


def test_settings_require_a_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing secrets fail at configuration rather than at the network boundary."""
    monkeypatch.delenv("DUFFEL_ACCESS_TOKEN", raising=False)

    with pytest.raises(DuffelConfigurationError, match="required"):
        DuffelSettings.from_environment()


def test_settings_reject_live_tokens() -> None:
    """The portfolio integration cannot accidentally access Duffel live mode."""
    with pytest.raises(DuffelConfigurationError, match="test-mode"):
        DuffelSettings(access_token="duffel_live_not_a_real_token")
