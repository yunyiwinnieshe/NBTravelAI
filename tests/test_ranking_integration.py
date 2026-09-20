"""Exercise real fixture data through constraints, preferences, pairs, and ranking."""

from datetime import date

import pytest

from travel_ai.providers.fixtures import FixtureFlightOfferProvider
from travel_ai.schemas.flights import FlightSearchQuery
from travel_ai.schemas.ranking import DestinationRankingInput
from travel_ai.schemas.trip import TravelerRequest, TripPreferences
from travel_ai.services.constraint_engine import evaluate_traveler_city_offers
from travel_ai.services.destination_ranking import rank_destinations
from travel_ai.services.fixture_loader import load_destination_fixtures
from travel_ai.services.flight_offer_selection import (
    build_flight_offer_pairs,
    select_recommended_flight_pair,
)
from travel_ai.services.preference_features import calculate_city_preference_features


@pytest.mark.parametrize("traveler_ids", [("alice", "bob"), ("alice__1", "bob_2")])
def test_fixture_pipeline_preserves_request_identity_and_excludes_denver(
    traveler_ids: tuple[str, str],
) -> None:
    fixtures = load_destination_fixtures()
    provider = FixtureFlightOfferProvider()
    start, end = date(2099, 6, 10), date(2099, 6, 14)
    travelers = tuple(
        TravelerRequest(
            traveler_id=traveler_id,
            origin_id=origin_id,
            budget_usd=500,
            max_one_way_travel_minutes=600,
            preferences=TripPreferences(interest_tags=["food"]),
        )
        for traveler_id, origin_id in zip(
            traveler_ids, ("boston_ma", "new_york_ny"), strict=True
        )
    )
    candidates = []
    excluded = {}
    for city in fixtures.cities:
        if city.city_id not in {"chicago_il", "miami_fl", "seattle_wa", "denver_co"}:
            continue
        evaluations = []
        for traveler, fixture_id, airport in zip(
            travelers, ("traveler_a", "traveler_b"), ("BOS", "JFK"), strict=True
        ):
            offers = provider.search(
                FlightSearchQuery(
                    traveler_id=fixture_id,
                    origin_id=traveler.origin_id,
                    destination_id=city.city_id,
                    origin_airport_codes=[airport],
                    destination_airport_codes=city.metro_airport_codes,
                    departure_date=start,
                    return_date=end,
                )
            )
            # Fixture records carry fixed test IDs; bind them to this request.
            offers = [
                offer.model_copy(update={"traveler_id": traveler.traveler_id})
                for offer in offers
            ]
            evaluations.append(
                evaluate_traveler_city_offers(
                    traveler,
                    city,
                    [airport],
                    start,
                    end,
                    offers,
                )
            )
        if any(result.city_exclusion for result in evaluations):
            excluded[city.city_id] = evaluations
            continue
        pair = select_recommended_flight_pair(
            build_flight_offer_pairs(
                evaluations[0].eligible_offers,
                evaluations[1].eligible_offers,
            )
        )
        selected_ids = {pair.pair.traveler_a_offer_id, pair.pair.traveler_b_offer_id}
        selected_offers = tuple(
            offer
            for result in evaluations
            for offer in result.eligible_offers
            if offer.offer_id in selected_ids
        )
        features = calculate_city_preference_features(
            city,
            [
                record
                for record in fixtures.monthly_climate
                if record.city_id == city.city_id
            ],
            start,
            end,
            tuple(traveler.preferences for traveler in travelers),
            traveler_ids=traveler_ids,
        )
        assert (
            tuple(feature.traveler_id for feature in features.travelers) == traveler_ids
        )
        candidates.append(
            DestinationRankingInput(
                destination_id=city.city_id,
                travelers=travelers,
                recommended_pair=pair,
                recommended_offers=selected_offers,
                preference_features=features,
            )
        )

    ranked = rank_destinations(candidates)
    assert {result.destination_id for result in ranked} == {
        "chicago_il",
        "miami_fl",
        "seattle_wa",
    }
    assert ranked == rank_destinations(list(reversed(candidates)))
    assert [result.score for result in ranked] == sorted(
        [result.score for result in ranked],
        reverse=True,
    )
    assert set(excluded) == {"denver_co"}
    assert [
        result.city_exclusion.traveler_id for result in excluded["denver_co"]
    ] == list(traveler_ids)
    assert [
        reason.value
        for result in excluded["denver_co"]
        for rejection in result.rejected_offers
        for reason in rejection.reason_codes
    ] == [
        "budget_exceeded",
        "max_travel_time_exceeded",
    ]
