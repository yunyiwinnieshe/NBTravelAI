"""End-to-end offline recommendation workflow tests."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from travel_ai.providers.fixtures import FixtureFlightOfferProvider
from travel_ai.schemas.recommendations import RecommendationResponse
from travel_ai.schemas.trip import TripRequest
from travel_ai.services.recommendation_service import RecommendationService


def request() -> TripRequest:
    return TripRequest.model_validate(
        {
            "start_date": "2099-06-10",
            "end_date": "2099-06-14",
            "travelers": [
                {
                    "traveler_id": "alice",
                    "origin_id": "boston_ma",
                    "budget_usd": 500,
                    "max_one_way_travel_minutes": 600,
                    "preferences": {"interest_tags": ["food"]},
                },
                {
                    "traveler_id": "bob",
                    "origin_id": "new_york_ny",
                    "budget_usd": 500,
                    "max_one_way_travel_minutes": 600,
                    "preferences": {"interest_tags": ["beach"]},
                },
            ],
        }
    )


def test_workflow_returns_valid_deterministic_ranked_response() -> None:
    service = RecommendationService(clock=lambda: datetime(2026, 9, 19, tzinfo=UTC))
    response = service.get_recommendations(request())
    assert response == service.get_recommendations(request())
    assert (
        RecommendationResponse.model_validate_json(response.model_dump_json())
        == response
    )
    assert response.status == "success"
    assert response.metadata.data_mode == "fixture"
    assert response.metadata.eligible_destination_count == 3
    assert {r.destination.destination_id for r in response.recommendations} == {
        "chicago_il",
        "miami_fl",
        "seattle_wa",
    }
    assert [r.rank for r in response.recommendations] == [1, 2, 3]
    assert [r.score for r in response.recommendations] == sorted(
        [r.score for r in response.recommendations],
        reverse=True,
    )
    assert {
        e.traveler_id for e in response.exclusions if e.destination_id == "denver_co"
    } == {"alice", "bob"}
    for result in response.recommendations:
        assert {g.traveler_id for g in result.flight_options_by_traveler} == {
            "alice",
            "bob",
        }
        for group in result.flight_options_by_traveler:
            assert 1 <= len(group.options) <= 4
            assert "recommended_pair" in group.options[0].labels
            assert sum("lowest_price" in o.labels for o in group.options) == 1
            assert sum("shortest_travel" in o.labels for o in group.options) == 1
            assert sum("fewest_connections" in o.labels for o in group.options) == 1
            assert all(o.round_trip_price_usd <= 500 for o in group.options)


@pytest.mark.parametrize("change", ["budget", "dates"])
def test_workflow_returns_no_match(change: str) -> None:
    trip = request()
    if change == "budget":
        trip.travelers[0].budget_usd = Decimal("1")
    else:
        trip = TripRequest.model_validate(
            {**trip.model_dump(), "start_date": "2099-07-10", "end_date": "2099-07-14"}
        )
    response = RecommendationService().get_recommendations(trip)
    assert response.status == "no_match"
    assert response.recommendations == []
    assert response.metadata.eligible_destination_count == 0
    assert response.exclusions


def test_fixture_results_do_not_depend_on_traveler_order_or_previous_request() -> None:
    service = RecommendationService(clock=lambda: datetime(2026, 9, 19, tzinfo=UTC))
    trip = request()
    original = service.get_recommendations(trip)
    trip.travelers.reverse()
    reversed_result = service.get_recommendations(trip)
    assert [
        (r.destination.destination_id, r.score) for r in original.recommendations
    ] == [
        (r.destination.destination_id, r.score) for r in reversed_result.recommendations
    ]
    assert service.get_recommendations(request()) == original


class DifferentAirportProvider(FixtureFlightOfferProvider):
    def search(self, query):
        offers = super().search(query)
        if query.destination_id != "chicago_il":
            return []
        if query.origin_id == "new_york_ny":
            for offer in offers:
                offer.outbound_slice.destination_airport_code = "MDW"
                offer.outbound_slice.segments[-1].destination_airport_code = "MDW"
                offer.return_slice.origin_airport_code = "MDW"
                offer.return_slice.segments[0].origin_airport_code = "MDW"
        return offers


def test_eligible_offers_without_pair_have_pair_level_exclusion() -> None:
    response = RecommendationService(
        flight_provider=DifferentAirportProvider()
    ).get_recommendations(request())
    assert response.status == "no_match"
    exclusions = [e for e in response.exclusions if e.destination_id == "chicago_il"]
    assert len(exclusions) == 1
    assert exclusions[0].reason_code == "no_compatible_flight_pair"
    assert exclusions[0].traveler_id is None


class FourthCityProvider(FixtureFlightOfferProvider):
    def search(self, query):
        if query.destination_id != "denver_co":
            return super().search(query)
        alternate = query.model_copy(
            update={
                "destination_id": "chicago_il",
                "destination_airport_codes": ["ORD"],
            }
        )
        offers = super().search(alternate)
        for offer in offers:
            offer.destination_id = "denver_co"
            offer.offer_id += "_denver"
            offer.outbound_slice.destination_airport_code = "DEN"
            offer.outbound_slice.segments[-1].destination_airport_code = "DEN"
            offer.return_slice.origin_airport_code = "DEN"
            offer.return_slice.segments[0].origin_airport_code = "DEN"
        return offers


def test_top_three_limit_preserves_total_eligible_count() -> None:
    response = RecommendationService(
        flight_provider=FourthCityProvider()
    ).get_recommendations(request())
    assert response.metadata.eligible_destination_count == 4
    assert len(response.recommendations) == 3
    assert not any(
        e.destination_id in {"chicago_il", "denver_co", "miami_fl", "seattle_wa"}
        for e in response.exclusions
    )


def test_workflow_logs_offer_rejection_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO", logger="travel_ai.services.recommendation_service"):
        response = RecommendationService().get_recommendations(request())
    records = [
        r for r in caplog.records if r.message == "recommendation_offer_rejected"
    ]
    assert [
        (r.traveler_id, r.destination_id, r.offer_id, r.reason_codes) for r in records
    ] == [
        ("alice", "denver_co", "fixture_a_denver_over_budget", ["budget_exceeded"]),
        (
            "bob",
            "denver_co",
            "fixture_b_denver_excessive_time",
            ["max_travel_time_exceeded"],
        ),
    ]
    assert all(
        not hasattr(r, "trip_request") and not hasattr(r, "offers") for r in records
    )
    assert {e.reason_code for e in response.exclusions} == {"no_eligible_flight"}


@pytest.mark.parametrize("return_offers", [False, True])
def test_live_provider_is_rejected_before_search(return_offers: bool) -> None:
    class LiveProvider(FixtureFlightOfferProvider):
        calls = 0

        @property
        def data_mode(self):
            return "live"

        def search(self, query):
            self.calls += 1
            return super().search(query) if return_offers else []

    provider = LiveProvider()
    with pytest.raises(ValueError, match="fixture providers only"):
        RecommendationService(flight_provider=provider)
    assert provider.calls == 0
    # The guard also applies if a caller replaces a previously valid provider.
    service = RecommendationService()
    service.flight_provider = provider
    with pytest.raises(ValueError, match="fixture providers only"):
        service.get_recommendations(request())
    assert provider.calls == 0


def test_fixture_provider_cannot_return_live_offers() -> None:
    class MisconfiguredProvider(FixtureFlightOfferProvider):
        def search(self, query):
            return [
                offer.model_copy(update={"is_fixture": False})
                for offer in super().search(query)
            ]

    with pytest.raises(ValueError, match="fixture offers only"):
        RecommendationService(
            flight_provider=MisconfiguredProvider()
        ).get_recommendations(request())
