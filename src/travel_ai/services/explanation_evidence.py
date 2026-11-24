"""Build the restricted verified evidence used by recommendation explanations."""

from travel_ai.schemas.explanations import (
    DestinationComparisonEvidence,
    ExclusionEvidence,
    ExplanationFreshnessEvidence,
    RankedDestinationEvidence,
    RecommendationExplanationEvidence,
    RecommendedPairEvidence,
    RequestedPreferenceEvidence,
    SelectedFlightEvidence,
    TravelerConstraintEvidence,
)
from travel_ai.schemas.recommendations import (
    DestinationRecommendation,
    FlightOption,
    RecommendationResponse,
)
from travel_ai.schemas.trip import TravelerRequest, TripRequest


def _selected_option(
    recommendation: DestinationRecommendation,
    traveler_id: str,
    offer_id: str,
) -> FlightOption:
    group = next(
        (
            item
            for item in recommendation.flight_options_by_traveler
            if item.traveler_id == traveler_id
        ),
        None,
    )
    if group is None:
        raise ValueError(f"recommendation has no flight options for {traveler_id}")
    option = next((item for item in group.options if item.offer_id == offer_id), None)
    if option is None:
        raise ValueError(
            f"recommended offer {offer_id} is unavailable for {traveler_id}"
        )
    return option


def _selected_flight_evidence(
    traveler: TravelerRequest,
    option: FlightOption,
) -> SelectedFlightEvidence:
    return SelectedFlightEvidence(
        traveler_id=traveler.traveler_id,
        offer_id=option.offer_id,
        round_trip_price_usd=option.round_trip_price_usd,
        budget_usd=traveler.budget_usd,
        budget_utilization=float(option.round_trip_price_usd / traveler.budget_usd),
        outbound_duration_minutes=option.outbound.duration_minutes,
        return_duration_minutes=option.return_flight.duration_minutes,
        outbound_connections=option.outbound.connection_count,
        return_connections=option.return_flight.connection_count,
    )


def _pair_evidence(
    recommendation: DestinationRecommendation,
    travelers_by_id: dict[str, TravelerRequest],
) -> RecommendedPairEvidence:
    selected_flights = []
    for reference in recommendation.recommended_pair.offers:
        traveler = travelers_by_id.get(reference.traveler_id)
        if traveler is None:
            raise ValueError(
                "recommendation traveler is absent from the confirmed request: "
                f"{reference.traveler_id}"
            )
        option = _selected_option(
            recommendation,
            reference.traveler_id,
            reference.offer_id,
        )
        selected_flights.append(_selected_flight_evidence(traveler, option))

    pair = recommendation.recommended_pair
    comparison = pair.price_comparison
    return RecommendedPairEvidence(
        combined_price_usd=pair.combined_price_usd,
        lowest_valid_combined_price_usd=(comparison.lowest_valid_combined_price_usd),
        premium_usd=comparison.premium_usd,
        premium_percentage=comparison.premium_percentage,
        combined_travel_minutes=pair.combined_travel_minutes,
        total_connections=pair.total_connections,
        arrival_gap_minutes=pair.arrival_gap_minutes,
        return_departure_gap_minutes=pair.return_departure_gap_minutes,
        time_together_minutes=pair.time_together_minutes,
        travelers=selected_flights,
    )


def _comparisons(
    recommendation: DestinationRecommendation,
    recommendations: list[DestinationRecommendation],
) -> list[DestinationComparisonEvidence]:
    return [
        DestinationComparisonEvidence(
            other_destination_id=other.destination.destination_id,
            score_difference=round(recommendation.score - other.score, 6),
            combined_price_difference_usd=(
                recommendation.recommended_pair.combined_price_usd
                - other.recommended_pair.combined_price_usd
            ),
            combined_travel_difference_minutes=(
                recommendation.recommended_pair.combined_travel_minutes
                - other.recommended_pair.combined_travel_minutes
            ),
            preference_match_difference=round(
                recommendation.score_breakdown.preference_match.value
                - other.score_breakdown.preference_match.value,
                6,
            ),
            travel_fairness_difference=round(
                recommendation.score_breakdown.travel_fairness.value
                - other.score_breakdown.travel_fairness.value,
                6,
            ),
        )
        for other in recommendations
        if other.destination.destination_id != recommendation.destination.destination_id
    ]


def build_explanation_evidence(
    trip_request: TripRequest,
    response: RecommendationResponse,
) -> RecommendationExplanationEvidence:
    """Create an allowlisted evidence bundle from validated request and response."""
    travelers_by_id = {
        traveler.traveler_id: traveler for traveler in trip_request.travelers
    }
    destinations = [
        RankedDestinationEvidence(
            rank=recommendation.rank,
            destination_id=recommendation.destination.destination_id,
            destination_name=recommendation.destination.name,
            score=recommendation.score,
            score_breakdown=recommendation.score_breakdown,
            recommended_pair=_pair_evidence(recommendation, travelers_by_id),
            comparisons=_comparisons(recommendation, response.recommendations),
        )
        for recommendation in response.recommendations
    ]
    return RecommendationExplanationEvidence(
        status=response.status,
        trip_start_date=trip_request.start_date,
        trip_end_date=trip_request.end_date,
        travelers=[
            TravelerConstraintEvidence(
                traveler_id=traveler.traveler_id,
                origin_id=traveler.origin_id,
                budget_usd=traveler.budget_usd,
                max_one_way_travel_minutes=traveler.max_one_way_travel_minutes,
                requested_preferences=RequestedPreferenceEvidence(
                    interest_tags=traveler.preferences.interest_tags,
                    temperature_range=traveler.preferences.temperature_range,
                ),
            )
            for traveler in trip_request.travelers
        ],
        destinations=destinations,
        exclusions=[
            ExclusionEvidence(
                destination_id=exclusion.destination_id,
                traveler_id=exclusion.traveler_id,
                reason_code=exclusion.reason_code,
            )
            for exclusion in response.exclusions
        ],
        freshness=ExplanationFreshnessEvidence(
            evaluated_at=response.metadata.evaluated_at,
            candidate_pool_version=response.metadata.candidate_pool_version,
            data_mode=response.metadata.data_mode,
        ),
    )
