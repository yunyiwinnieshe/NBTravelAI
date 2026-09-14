"""Tests for deterministic destination scoring and ranking."""

from decimal import Decimal

import pytest
from pydantic import TypeAdapter

from travel_ai.providers.fixtures import DEFAULT_FLIGHT_OFFERS_PATH
from travel_ai.schemas.flights import FlightOffer
from travel_ai.schemas.preference_features import (
    CityPreferenceFeatures,
    TravelerPreferenceFeatures,
)
from travel_ai.schemas.ranking import DestinationRankingInput
from travel_ai.schemas.trip import TravelerRequest
from travel_ai.services.destination_ranking import (
    calculate_destination_score,
    rank_destinations,
)
from travel_ai.services.flight_offer_selection import (
    build_flight_offer_pairs,
    select_recommended_flight_pair,
)


def _chicago_offers() -> list[FlightOffer]:
    offers = TypeAdapter(list[FlightOffer]).validate_json(
        DEFAULT_FLIGHT_OFFERS_PATH.read_text(encoding="utf-8")
    )
    return [offer for offer in offers if offer.destination_id == "chicago_il"]


def _ranking_input(
    preference_score: float | None = 0.8,
) -> DestinationRankingInput:
    offers = _chicago_offers()
    offers_a = [offer for offer in offers if offer.traveler_id == "traveler_a"]
    offers_b = [offer for offer in offers if offer.traveler_id == "traveler_b"]
    selected_pair = select_recommended_flight_pair(
        build_flight_offer_pairs(offers_a, offers_b)
    )
    selected_ids = {
        selected_pair.pair.traveler_a_offer_id,
        selected_pair.pair.traveler_b_offer_id,
    }
    selected_offers = tuple(offer for offer in offers if offer.offer_id in selected_ids)
    travelers = (
        TravelerRequest(
            traveler_id="traveler_a",
            origin_id="boston_ma",
            budget_usd=Decimal("600"),
            max_one_way_travel_minutes=480,
        ),
        TravelerRequest(
            traveler_id="traveler_b",
            origin_id="new_york_ny",
            budget_usd=Decimal("800"),
            max_one_way_travel_minutes=600,
        ),
    )
    traveler_features = tuple(
        TravelerPreferenceFeatures(
            traveler_id=traveler.traveler_id,
            preference_score=preference_score,
        )
        for traveler in travelers
    )
    return DestinationRankingInput(
        destination_id="chicago_il",
        travelers=travelers,
        recommended_pair=selected_pair,
        recommended_offers=selected_offers,
        preference_features=CityPreferenceFeatures(
            city_id="chicago_il",
            trip_temperature_celsius=24,
            travelers=traveler_features,
            combined_preference_score=preference_score,
            preference_gap=0 if preference_score is not None else None,
            preference_fairness=1 if preference_score is not None else None,
        ),
    )


def _clone_for_destination(
    candidate: DestinationRankingInput,
    destination_id: str,
    price_delta: Decimal = Decimal("0"),
) -> DestinationRankingInput:
    pair = candidate.recommended_pair.pair.model_copy(
        update={
            "destination_id": destination_id,
            "combined_price_usd": (
                candidate.recommended_pair.pair.combined_price_usd + price_delta
            ),
        }
    )
    offers = tuple(
        offer.model_copy(
            update={
                "destination_id": destination_id,
                "total_amount": offer.total_amount
                + (price_delta if index == 0 else Decimal("0")),
            }
        )
        for index, offer in enumerate(candidate.recommended_offers)
    )
    return candidate.model_copy(
        update={
            "destination_id": destination_id,
            "recommended_pair": candidate.recommended_pair.model_copy(
                update={"pair": pair}
            ),
            "recommended_offers": offers,
            "preference_features": candidate.preference_features.model_copy(
                update={"city_id": destination_id}
            ),
        }
    )


def test_score_uses_each_travelers_budget_and_one_way_time_limit() -> None:
    candidate = _ranking_input()
    result = calculate_destination_score(candidate)
    pair = candidate.recommended_pair.pair
    offers_by_id = {offer.offer_id: offer for offer in candidate.recommended_offers}
    references = (
        (pair.traveler_a_id, pair.traveler_a_offer_id),
        (pair.traveler_b_id, pair.traveler_b_offer_id),
    )
    travelers = {traveler.traveler_id: traveler for traveler in candidate.travelers}
    budget_burdens = [
        float(offers_by_id[offer_id].total_amount / travelers[traveler_id].budget_usd)
        for traveler_id, offer_id in references
    ]
    time_burdens = [
        (
            offers_by_id[offer_id].maximum_one_way_travel_minutes
            / travelers[traveler_id].max_one_way_travel_minutes
        )
        for traveler_id, offer_id in references
    ]

    breakdown = result.score_breakdown
    assert breakdown.affordability.value == pytest.approx(
        sum(1 - burden for burden in budget_burdens) / 2,
        abs=1e-6,
    )
    assert breakdown.travel_time.value == pytest.approx(
        sum(1 - burden for burden in time_burdens) / 2,
        abs=1e-6,
    )
    assert breakdown.travel_fairness_details.duration_balance == pytest.approx(
        1 - abs(time_burdens[0] - time_burdens[1]),
        abs=1e-6,
    )
    assert breakdown.travel_fairness_details.budget_burden_balance == pytest.approx(
        1 - abs(budget_burdens[0] - budget_burdens[1]), abs=1e-6
    )


def test_preference_score_uses_its_documented_weight() -> None:
    result = calculate_destination_score(_ranking_input(preference_score=0.8))

    assert result.score_breakdown.preference_match.value == pytest.approx(0.8)
    assert result.score_breakdown.preference_match.weight == pytest.approx(0.2)
    assert result.score_breakdown.preference_match.contribution == pytest.approx(0.16)


def test_no_preferences_redistributes_the_preference_weight() -> None:
    result = calculate_destination_score(_ranking_input(preference_score=None))
    breakdown = result.score_breakdown

    assert breakdown.preference_match.weight == 0
    assert breakdown.preference_match.contribution == 0
    assert breakdown.affordability.weight == pytest.approx(0.4375)
    assert breakdown.travel_fairness.weight == pytest.approx(0.375)
    assert breakdown.travel_time.weight == pytest.approx(0.1875)


def test_ranking_uses_score_then_cost_then_stable_destination_id() -> None:
    base = _ranking_input()
    alphabetically_first = _clone_for_destination(base, "austin_tx")
    alphabetically_second = _clone_for_destination(base, "boston_ma")
    more_expensive = _clone_for_destination(
        base,
        "denver_co",
        price_delta=Decimal("10"),
    )

    ranked = rank_destinations(
        [more_expensive, alphabetically_second, alphabetically_first]
    )

    assert [result.destination_id for result in ranked] == [
        "austin_tx",
        "boston_ma",
        "denver_co",
    ]


def test_ranking_rejects_an_offer_that_bypassed_constraints() -> None:
    candidate = _ranking_input()
    too_expensive = candidate.recommended_offers[0].model_copy(
        update={"total_amount": Decimal("99999")}
    )
    invalid = candidate.model_copy(
        update={
            "recommended_offers": (
                too_expensive,
                candidate.recommended_offers[1],
            )
        }
    )

    with pytest.raises(ValueError, match="budget burden"):
        calculate_destination_score(invalid)
