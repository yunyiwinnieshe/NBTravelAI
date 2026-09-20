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


@pytest.mark.parametrize(
    "traveler_ids", [("other_a", "other_b"), ("traveler_a", "traveler_a")]
)
def test_ranking_rejects_mismatched_preference_travelers(traveler_ids) -> None:
    payload = _ranking_input().model_dump()
    for feature, traveler_id in zip(
        payload["preference_features"]["travelers"], traveler_ids, strict=True
    ):
        feature["traveler_id"] = traveler_id
    candidate = DestinationRankingInput.model_validate(payload)
    with pytest.raises(ValueError, match="preference features must belong"):
        calculate_destination_score(candidate)


@pytest.mark.parametrize(
    "metric",
    [
        "combined_price_usd",
        "combined_travel_minutes",
        "arrival_gap_minutes",
        "return_departure_gap_minutes",
        "time_together_minutes",
    ],
)
def test_ranking_rejects_stale_pair_metrics(metric: str) -> None:
    payload = _ranking_input().model_dump()
    payload["recommended_pair"]["pair"][metric] += 1
    candidate = DestinationRankingInput.model_validate(payload)
    with pytest.raises(ValueError, match="pair metrics must match"):
        calculate_destination_score(candidate)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("origin_id", "wrong_origin", "match its traveler's origin"),
        ("is_available", False, "must be available"),
    ],
)
def test_ranking_rejects_ineligible_offer_context(field, value, message) -> None:
    payload = _ranking_input().model_dump()
    payload["recommended_offers"][0][field] = value
    candidate = DestinationRankingInput.model_validate(payload)
    with pytest.raises(ValueError, match=message):
        calculate_destination_score(candidate)


def test_ranking_accepts_reordered_travelers_offers_and_preferences() -> None:
    candidate = _ranking_input()
    payload = candidate.model_dump()
    payload["travelers"] = tuple(reversed(payload["travelers"]))
    payload["recommended_offers"] = tuple(reversed(payload["recommended_offers"]))
    payload["preference_features"]["travelers"] = tuple(
        reversed(payload["preference_features"]["travelers"])
    )
    assert calculate_destination_score(
        DestinationRankingInput.model_validate(payload)
    ) == (calculate_destination_score(candidate))


def test_ranking_handles_empty_and_duplicate_candidates() -> None:
    assert rank_destinations([]) == []
    candidate = _ranking_input()
    with pytest.raises(ValueError, match="destination IDs must be unique"):
        rank_destinations([candidate, candidate])


def test_ranking_tie_breaks_use_price_then_duration_then_id(monkeypatch) -> None:
    """Isolate sorting from scoring so every candidate has an exactly tied score."""
    base = _ranking_input()
    base_score = calculate_destination_score(base)
    candidates = [
        _clone_for_destination(base, name)
        for name in ["a_expensive", "b_longer", "d_equal", "c_equal"]
    ]
    results = {
        name: base_score.model_copy(
            update={
                "destination_id": name,
                "combined_airfare_usd": Decimal(price),
                "combined_travel_minutes": minutes,
            }
        )
        for name, price, minutes in [
            ("a_expensive", "600", 200),
            ("b_longer", "500", 400),
            ("d_equal", "500", 300),
            ("c_equal", "500", 300),
        ]
    }
    monkeypatch.setattr(
        "travel_ai.services.destination_ranking.calculate_destination_score",
        lambda candidate: results[candidate.destination_id],
    )
    assert [item.destination_id for item in rank_destinations(candidates)] == [
        "c_equal",
        "d_equal",
        "b_longer",
        "a_expensive",
    ]
