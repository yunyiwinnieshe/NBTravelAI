"""Pure deterministic scoring and ranking for eligible destinations."""

from collections.abc import Sequence
from decimal import Decimal

from travel_ai.schemas.ranking import (
    DestinationRankingInput,
    RankedDestinationScore,
)
from travel_ai.schemas.recommendations import (
    ScoreBreakdown,
    ScoreComponent,
    TravelFairnessDetails,
)
from travel_ai.services.flight_offer_selection import (
    build_flight_offer_pairs,
    calculate_arrival_alignment_score,
)

AFFORDABILITY_WEIGHT = 0.35
TRAVEL_FAIRNESS_WEIGHT = 0.30
PREFERENCE_MATCH_WEIGHT = 0.20
TRAVEL_TIME_WEIGHT = 0.15


def _validate_burden(value: Decimal, label: str) -> float:
    """Convert an already constrained ratio to a normalized float."""
    burden = float(value)
    if not 0 <= burden <= 1:
        raise ValueError(f"{label} must be between 0 and 1 after constraints")
    return burden


def _score_component(value: float, weight: float) -> ScoreComponent:
    """Build a consistently rounded public score component."""
    normalized_value = round(value, 6)
    normalized_weight = round(weight, 6)
    return ScoreComponent(
        value=normalized_value,
        weight=normalized_weight,
        contribution=round(normalized_value * normalized_weight, 6),
    )


def calculate_destination_score(
    ranking_input: DestinationRankingInput,
) -> RankedDestinationScore:
    """Score one eligible city from its selected reference flight pair."""
    pair = ranking_input.recommended_pair.pair
    if pair.destination_id != ranking_input.destination_id:
        raise ValueError("recommended pair must belong to the destination")
    if ranking_input.preference_features.city_id != ranking_input.destination_id:
        raise ValueError("preference features must belong to the destination")

    travelers_by_id = {
        traveler.traveler_id: traveler for traveler in ranking_input.travelers
    }
    if len(travelers_by_id) != 2:
        raise ValueError("ranking requires two distinct travelers")

    feature_traveler_ids = [
        feature.traveler_id for feature in ranking_input.preference_features.travelers
    ]
    if len(set(feature_traveler_ids)) != 2 or set(feature_traveler_ids) != set(
        travelers_by_id
    ):
        raise ValueError("preference features must belong to both ranking travelers")

    offers_by_id = {offer.offer_id: offer for offer in ranking_input.recommended_offers}
    if len(offers_by_id) != 2:
        raise ValueError("ranking requires two distinct recommended offers")

    pair_references = (
        (pair.traveler_a_id, pair.traveler_a_offer_id),
        (pair.traveler_b_id, pair.traveler_b_offer_id),
    )
    if {pair.traveler_a_id, pair.traveler_b_id} != set(travelers_by_id):
        raise ValueError("recommended pair must reference both ranking travelers")
    if {pair.traveler_a_offer_id, pair.traveler_b_offer_id} != set(offers_by_id):
        raise ValueError("recommended pair must reference both recommended offers")

    budget_burdens: list[float] = []
    time_burdens: list[float] = []
    for traveler_id, offer_id in pair_references:
        traveler = travelers_by_id.get(traveler_id)
        offer = offers_by_id.get(offer_id)
        if traveler is None or offer is None:
            raise ValueError("recommended pair references unknown traveler or offer")
        if offer.traveler_id != traveler_id:
            raise ValueError("recommended offer must belong to its traveler")
        if offer.destination_id != ranking_input.destination_id:
            raise ValueError("recommended offer must belong to the destination")

        if offer.origin_id != traveler.origin_id:
            raise ValueError("recommended offer must match its traveler's origin")
        if not offer.is_available:
            raise ValueError("recommended offer must be available after constraints")

        budget_burdens.append(
            _validate_burden(
                offer.total_amount / traveler.budget_usd,
                "budget burden",
            )
        )
        time_burdens.append(
            _validate_burden(
                Decimal(offer.maximum_one_way_travel_minutes)
                / Decimal(traveler.max_one_way_travel_minutes),
                "travel-time burden",
            )
        )

    # Reuse pairing rules so cached metrics cannot disagree with the offers.
    derived_pairs = build_flight_offer_pairs(
        [offers_by_id[pair.traveler_a_offer_id]],
        [offers_by_id[pair.traveler_b_offer_id]],
    )
    if not derived_pairs:
        raise ValueError("recommended offers must form a compatible flight pair")
    if pair != derived_pairs[0]:
        raise ValueError("recommended pair metrics must match its offers")

    affordability = sum(1.0 - burden for burden in budget_burdens) / 2
    travel_time = sum(1.0 - burden for burden in time_burdens) / 2
    fairness_details = TravelFairnessDetails(
        duration_balance=round(1.0 - abs(time_burdens[0] - time_burdens[1]), 6),
        budget_burden_balance=round(
            1.0 - abs(budget_burdens[0] - budget_burdens[1]),
            6,
        ),
        arrival_alignment=round(
            calculate_arrival_alignment_score(pair.arrival_gap_minutes),
            6,
        ),
    )

    preference_match = ranking_input.preference_features.combined_preference_score
    if preference_match is None:
        active_weight = 1.0 - PREFERENCE_MATCH_WEIGHT
        affordability_weight = AFFORDABILITY_WEIGHT / active_weight
        fairness_weight = TRAVEL_FAIRNESS_WEIGHT / active_weight
        travel_time_weight = TRAVEL_TIME_WEIGHT / active_weight
        preference_weight = 0.0
        preference_value = 1.0
    else:
        affordability_weight = AFFORDABILITY_WEIGHT
        fairness_weight = TRAVEL_FAIRNESS_WEIGHT
        preference_weight = PREFERENCE_MATCH_WEIGHT
        travel_time_weight = TRAVEL_TIME_WEIGHT
        preference_value = preference_match

    breakdown = ScoreBreakdown(
        affordability=_score_component(affordability, affordability_weight),
        travel_fairness=_score_component(
            fairness_details.calculated_value,
            fairness_weight,
        ),
        preference_match=_score_component(preference_value, preference_weight),
        travel_time=_score_component(travel_time, travel_time_weight),
        travel_fairness_details=fairness_details,
    )
    score = round(
        sum(
            component.contribution
            for component in (
                breakdown.affordability,
                breakdown.travel_fairness,
                breakdown.preference_match,
                breakdown.travel_time,
            )
        ),
        6,
    )
    return RankedDestinationScore(
        destination_id=ranking_input.destination_id,
        score=score,
        score_breakdown=breakdown,
        combined_airfare_usd=pair.combined_price_usd,
        combined_travel_minutes=pair.combined_travel_minutes,
    )


def rank_destinations(
    candidates: Sequence[DestinationRankingInput],
) -> list[RankedDestinationScore]:
    """Return every eligible destination in deterministic best-first order."""
    destination_ids = [candidate.destination_id for candidate in candidates]
    if len(destination_ids) != len(set(destination_ids)):
        raise ValueError("ranking candidate destination IDs must be unique")

    scored = [calculate_destination_score(candidate) for candidate in candidates]
    return sorted(
        scored,
        key=lambda result: (
            -result.score,
            result.combined_airfare_usd,
            result.combined_travel_minutes,
            result.destination_id,
        ),
    )
