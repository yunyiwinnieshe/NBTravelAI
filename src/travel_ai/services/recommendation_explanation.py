"""Plain-language explanations made only from validated recommendation fields."""

from travel_ai.schemas.recommendations import DestinationRecommendation


def build_explanation(
    recommendation: DestinationRecommendation, *, flight_source: str = "example data"
) -> str:
    """Describe the score and a real flight-pair tradeoff without new facts."""
    breakdown = recommendation.score_breakdown
    factors = sorted(
        (
            ("affordability", breakdown.affordability.contribution),
            ("travel fairness", breakdown.travel_fairness.contribution),
            ("preference match", breakdown.preference_match.contribution),
            ("travel time", breakdown.travel_time.contribution),
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    pair = recommendation.recommended_pair
    premium = pair.price_comparison.premium_usd
    comparison = (
        f"${premium:,.2f} above the cheapest valid pair for this destination"
        if premium
        else "the cheapest valid pair for this destination"
    )
    return (
        f"{recommendation.destination.name} ranks #{recommendation.rank} "
        f"with a score of {recommendation.score:.2f}. Its largest score "
        f"contributions are {factors[0][0]} and {factors[1][0]}. "
        f"The selected round-trip flights cost an estimated "
        f"${pair.combined_price_usd:,.2f} together in {flight_source}, "
        f"{comparison}. Their outbound arrivals are "
        f"{pair.arrival_gap_minutes} minutes apart."
    )
