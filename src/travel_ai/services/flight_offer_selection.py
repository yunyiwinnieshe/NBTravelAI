"""Deterministic policies for selecting among eligible round-trip offers."""

from travel_ai.schemas.flights import (
    FlightOffer,
    FlightOfferPair,
    FlightPairScoreBreakdown,
    PairScoreComponent,
    ScoredFlightOfferPair,
)

PAIR_PRICE_WEIGHT = 0.35
PAIR_ARRIVAL_ALIGNMENT_WEIGHT = 0.25
PAIR_TRAVEL_TIME_WEIGHT = 0.20
PAIR_CONNECTIONS_WEIGHT = 0.10
PAIR_TIME_TOGETHER_WEIGHT = 0.10

FULL_ARRIVAL_ALIGNMENT_MINUTES = 120
ZERO_ARRIVAL_ALIGNMENT_MINUTES = 360


def build_flight_offer_pairs(
    traveler_a_offers: list[FlightOffer],
    traveler_b_offers: list[FlightOffer],
) -> list[FlightOfferPair]:
    """Build every valid pair and derive schedule-compatibility metrics."""
    if not traveler_a_offers or not traveler_b_offers:
        return []

    traveler_a_id = traveler_a_offers[0].traveler_id
    traveler_b_id = traveler_b_offers[0].traveler_id
    destination_id = traveler_a_offers[0].destination_id

    if traveler_a_id == traveler_b_id:
        raise ValueError("flight pairs require two distinct travelers")
    if any(offer.traveler_id != traveler_a_id for offer in traveler_a_offers):
        raise ValueError("traveler_a_offers must belong to one traveler")
    if any(offer.traveler_id != traveler_b_id for offer in traveler_b_offers):
        raise ValueError("traveler_b_offers must belong to one traveler")
    if any(
        offer.destination_id != destination_id
        for offer in traveler_a_offers + traveler_b_offers
    ):
        raise ValueError("flight pairs must share one destination")

    pairs: list[FlightOfferPair] = []
    for offer_a in traveler_a_offers:
        for offer_b in traveler_b_offers:
            if (
                offer_a.outbound_slice.destination_airport_code
                != offer_b.outbound_slice.destination_airport_code
            ):
                continue
            arrival_a = offer_a.outbound_slice.segments[-1].arrival_at
            arrival_b = offer_b.outbound_slice.segments[-1].arrival_at
            return_a = offer_a.return_slice.segments[0].departure_at
            return_b = offer_b.return_slice.segments[0].departure_at

            time_together_start = max(arrival_a, arrival_b)
            time_together_end = min(return_a, return_b)
            time_together_minutes = int(
                (time_together_end - time_together_start).total_seconds() // 60
            )
            if time_together_minutes <= 0:
                continue

            arrival_gap_minutes = int(
                abs((arrival_a - arrival_b).total_seconds()) // 60
            )
            return_departure_gap_minutes = int(
                abs((return_a - return_b).total_seconds()) // 60
            )
            pairs.append(
                FlightOfferPair(
                    traveler_a_id=traveler_a_id,
                    traveler_a_offer_id=offer_a.offer_id,
                    traveler_b_id=traveler_b_id,
                    traveler_b_offer_id=offer_b.offer_id,
                    destination_id=destination_id,
                    combined_price_usd=(offer_a.total_amount + offer_b.total_amount),
                    arrival_gap_minutes=arrival_gap_minutes,
                    return_departure_gap_minutes=return_departure_gap_minutes,
                    time_together_minutes=time_together_minutes,
                    traveler_a_connections=offer_a.total_connections,
                    traveler_b_connections=offer_b.total_connections,
                    total_connections=(
                        offer_a.total_connections + offer_b.total_connections
                    ),
                    combined_travel_minutes=(
                        offer_a.total_travel_minutes + offer_b.total_travel_minutes
                    ),
                )
            )
    return pairs


def _score_component(value: float, weight: float) -> PairScoreComponent:
    """Build one consistently rounded pair-score component."""
    normalized_value = round(value, 6)
    return PairScoreComponent(
        value=normalized_value,
        weight=weight,
        contribution=round(normalized_value * weight, 6),
    )


def calculate_arrival_alignment_score(arrival_gap_minutes: int) -> float:
    """Give full credit within two hours and decline to zero at six hours."""
    if arrival_gap_minutes <= FULL_ARRIVAL_ALIGNMENT_MINUTES:
        return 1.0
    if arrival_gap_minutes >= ZERO_ARRIVAL_ALIGNMENT_MINUTES:
        return 0.0
    return (ZERO_ARRIVAL_ALIGNMENT_MINUTES - arrival_gap_minutes) / (
        ZERO_ARRIVAL_ALIGNMENT_MINUTES - FULL_ARRIVAL_ALIGNMENT_MINUTES
    )


def score_flight_offer_pairs(
    valid_pairs: list[FlightOfferPair],
) -> list[ScoredFlightOfferPair]:
    """Score every valid pair without discarding pairs behind a price guardrail."""
    if not valid_pairs:
        return []

    lowest_price = min(pair.combined_price_usd for pair in valid_pairs)
    shortest_travel = min(pair.combined_travel_minutes for pair in valid_pairs)
    longest_time_together = max(pair.time_together_minutes for pair in valid_pairs)

    scored_pairs: list[ScoredFlightOfferPair] = []
    for pair in valid_pairs:
        price_value = float(lowest_price / pair.combined_price_usd)
        travel_time_value = shortest_travel / pair.combined_travel_minutes
        connection_value = (
            (1 / (1 + pair.traveler_a_connections))
            + (1 / (1 + pair.traveler_b_connections))
        ) / 2
        time_together_value = pair.time_together_minutes / longest_time_together

        breakdown = FlightPairScoreBreakdown(
            price=_score_component(price_value, PAIR_PRICE_WEIGHT),
            arrival_alignment=_score_component(
                calculate_arrival_alignment_score(pair.arrival_gap_minutes),
                PAIR_ARRIVAL_ALIGNMENT_WEIGHT,
            ),
            travel_time=_score_component(
                travel_time_value,
                PAIR_TRAVEL_TIME_WEIGHT,
            ),
            connections=_score_component(
                connection_value,
                PAIR_CONNECTIONS_WEIGHT,
            ),
            time_together=_score_component(
                time_together_value,
                PAIR_TIME_TOGETHER_WEIGHT,
            ),
        )
        selection_score = round(
            sum(
                component.contribution
                for component in (
                    breakdown.price,
                    breakdown.arrival_alignment,
                    breakdown.travel_time,
                    breakdown.connections,
                    breakdown.time_together,
                )
            ),
            6,
        )
        scored_pairs.append(
            ScoredFlightOfferPair(
                pair=pair,
                selection_score=selection_score,
                score_breakdown=breakdown,
            )
        )
    return scored_pairs


def select_recommended_flight_pair(
    valid_pairs: list[FlightOfferPair],
) -> ScoredFlightOfferPair:
    """Choose the highest-scoring pair, then apply stable business tie-breaks."""
    if not valid_pairs:
        raise ValueError("at least one valid flight pair is required")
    return min(
        score_flight_offer_pairs(valid_pairs),
        key=lambda scored: (
            -scored.selection_score,
            scored.pair.combined_price_usd,
            scored.pair.combined_travel_minutes,
            scored.pair.arrival_gap_minutes,
            scored.pair.total_connections,
            -scored.pair.time_together_minutes,
            scored.pair.traveler_a_offer_id,
            scored.pair.traveler_b_offer_id,
        ),
    )


def select_display_flight_offers(
    eligible_offers: list[FlightOffer],
    recommended_offer_id: str,
    maximum_options: int = 4,
) -> list[FlightOffer]:
    """Return the recommended offer and truthful distinct category winners."""
    if not 1 <= maximum_options <= 4:
        raise ValueError("maximum_options must be between 1 and 4")
    if not eligible_offers:
        return []

    offers_by_id = {offer.offer_id: offer for offer in eligible_offers}
    if len(offers_by_id) != len(eligible_offers):
        raise ValueError("eligible flight offer IDs must be unique")
    if recommended_offer_id not in offers_by_id:
        raise ValueError("recommended offer must be eligible")

    lowest_price = min(
        eligible_offers,
        key=lambda offer: (
            offer.total_amount,
            offer.total_travel_minutes,
            offer.total_connections,
            offer.offer_id,
        ),
    )
    shortest_travel = min(
        eligible_offers,
        key=lambda offer: (
            offer.total_travel_minutes,
            offer.total_amount,
            offer.total_connections,
            offer.offer_id,
        ),
    )
    fewest_connections = min(
        eligible_offers,
        key=lambda offer: (
            offer.total_connections,
            offer.total_amount,
            offer.total_travel_minutes,
            offer.offer_id,
        ),
    )

    ordered_candidates = [
        offers_by_id[recommended_offer_id],
        lowest_price,
        shortest_travel,
        fewest_connections,
    ]
    selected: list[FlightOffer] = []
    selected_ids: set[str] = set()
    for offer in ordered_candidates:
        if offer.offer_id in selected_ids:
            continue
        selected.append(offer)
        selected_ids.add(offer.offer_id)
        if len(selected) == maximum_options:
            break
    return selected
