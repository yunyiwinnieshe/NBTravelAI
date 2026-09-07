"""Deterministic policies for selecting among eligible round-trip offers."""

from decimal import Decimal

from travel_ai.schemas.flights import FlightOffer, FlightOfferPair

DEFAULT_NONSTOP_PRICE_TOLERANCE = Decimal("0.50")
DEFAULT_PAIR_PRICE_TOLERANCE = Decimal("0.50")


def select_preferred_flight_offer(
    eligible_offers: list[FlightOffer],
    nonstop_price_tolerance: Decimal = DEFAULT_NONSTOP_PRICE_TOLERANCE,
) -> FlightOffer:
    """Prefer nonstop travel when it is within the configured price tolerance."""
    if not eligible_offers:
        raise ValueError("at least one eligible flight offer is required")
    if not Decimal("0") <= nonstop_price_tolerance <= Decimal("1"):
        raise ValueError("nonstop_price_tolerance must be between 0 and 1")

    cheapest = min(
        eligible_offers,
        key=lambda offer: (
            offer.total_amount,
            offer.total_travel_minutes,
            offer.total_connections,
            offer.offer_id,
        ),
    )
    maximum_preferred_nonstop_price = cheapest.total_amount * (
        Decimal("1") + nonstop_price_tolerance
    )
    comparable_nonstop_offers = [
        offer
        for offer in eligible_offers
        if offer.is_round_trip_nonstop
        and offer.total_amount <= maximum_preferred_nonstop_price
    ]

    if comparable_nonstop_offers:
        return min(
            comparable_nonstop_offers,
            key=lambda offer: (
                offer.total_amount,
                offer.total_travel_minutes,
                offer.offer_id,
            ),
        )
    return cheapest


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
            arrival_a = offer_a.outbound_slice.segments[-1].arrival_at
            arrival_b = offer_b.outbound_slice.segments[-1].arrival_at
            return_a = offer_a.return_slice.segments[0].departure_at
            return_b = offer_b.return_slice.segments[0].departure_at

            shared_trip_start = max(arrival_a, arrival_b)
            shared_trip_end = min(return_a, return_b)
            shared_trip_minutes = int(
                (shared_trip_end - shared_trip_start).total_seconds() // 60
            )
            if shared_trip_minutes <= 0:
                continue

            arrival_gap_minutes = int(
                abs((arrival_a - arrival_b).total_seconds()) // 60
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
                    shared_trip_minutes=shared_trip_minutes,
                    total_connections=(
                        offer_a.total_connections + offer_b.total_connections
                    ),
                    combined_travel_minutes=(
                        offer_a.total_travel_minutes + offer_b.total_travel_minutes
                    ),
                )
            )
    return pairs


def select_recommended_flight_pair(
    valid_pairs: list[FlightOfferPair],
    pair_price_tolerance: Decimal = DEFAULT_PAIR_PRICE_TOLERANCE,
) -> FlightOfferPair:
    """Prefer synchronized arrival within a protected combined-price range."""
    if not valid_pairs:
        raise ValueError("at least one valid flight pair is required")
    if not Decimal("0") <= pair_price_tolerance <= Decimal("1"):
        raise ValueError("pair_price_tolerance must be between 0 and 1")

    cheapest = min(
        valid_pairs,
        key=lambda pair: (
            pair.combined_price_usd,
            pair.arrival_gap_minutes,
            pair.total_connections,
            pair.traveler_a_offer_id,
            pair.traveler_b_offer_id,
        ),
    )
    maximum_recommended_price = cheapest.combined_price_usd * (
        Decimal("1") + pair_price_tolerance
    )
    price_protected_pairs = [
        pair
        for pair in valid_pairs
        if pair.combined_price_usd <= maximum_recommended_price
    ]
    return min(
        price_protected_pairs,
        key=lambda pair: (
            pair.arrival_gap_minutes,
            pair.total_connections,
            -pair.shared_trip_minutes,
            pair.combined_travel_minutes,
            pair.combined_price_usd,
            pair.traveler_a_offer_id,
            pair.traveler_b_offer_id,
        ),
    )


def select_display_flight_offers(
    eligible_offers: list[FlightOffer],
    recommended_offer_id: str,
    maximum_options: int = 3,
) -> list[FlightOffer]:
    """Return a distinct bounded list containing the recommended offer."""
    if not 1 <= maximum_options <= 3:
        raise ValueError("maximum_options must be between 1 and 3")
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
            offer.total_travel_minutes,
            offer.total_amount,
            offer.offer_id,
        ),
    )

    ordered_candidates = [
        offers_by_id[recommended_offer_id],
        lowest_price,
        shortest_travel,
        fewest_connections,
        *sorted(
            eligible_offers,
            key=lambda offer: (
                offer.total_amount,
                offer.total_travel_minutes,
                offer.total_connections,
                offer.offer_id,
            ),
        ),
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
