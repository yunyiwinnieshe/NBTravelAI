"""Pure deterministic filtering rules for normalized flight offers."""

from collections.abc import Collection, Sequence
from datetime import date

from travel_ai.schemas.constraints import (
    CityExclusion,
    ConstraintEvaluationResult,
    OfferExclusionReason,
    OfferRejection,
)
from travel_ai.schemas.destinations import City
from travel_ai.schemas.flights import FlightOffer
from travel_ai.schemas.trip import TravelerRequest


def evaluate_offer(
    offer: FlightOffer,
    traveler: TravelerRequest,
    city: City,
    origin_airport_codes: Collection[str],
    trip_start_date: date,
    trip_end_date: date,
) -> OfferRejection | None:
    """Return every rule violation for one offer, or None when it is eligible."""
    reasons: list[OfferExclusionReason] = []
    if offer.traveler_id != traveler.traveler_id:
        reasons.append(OfferExclusionReason.TRAVELER_MISMATCH)

    origin_codes = set(origin_airport_codes)
    if (
        offer.origin_id != traveler.origin_id
        or offer.outbound_slice.origin_airport_code not in origin_codes
        or offer.return_slice.destination_airport_code not in origin_codes
    ):
        reasons.append(OfferExclusionReason.ORIGIN_MISMATCH)

    destination_codes = set(city.metro_airport_codes)
    if (
        offer.destination_id != city.city_id
        or offer.outbound_slice.destination_airport_code not in destination_codes
        or offer.return_slice.origin_airport_code not in destination_codes
    ):
        reasons.append(OfferExclusionReason.DESTINATION_MISMATCH)

    outbound_date = offer.outbound_slice.segments[0].departure_at.date()
    return_date = offer.return_slice.segments[0].departure_at.date()
    if outbound_date != trip_start_date or return_date != trip_end_date:
        reasons.append(OfferExclusionReason.DATE_MISMATCH)

    if offer.maximum_one_way_travel_minutes > traveler.max_one_way_travel_minutes:
        reasons.append(OfferExclusionReason.MAX_TRAVEL_TIME_EXCEEDED)

    if offer.total_amount > traveler.budget_usd:
        reasons.append(OfferExclusionReason.BUDGET_EXCEEDED)

    if not offer.is_available:
        reasons.append(OfferExclusionReason.OFFER_UNAVAILABLE)

    if not reasons:
        return None
    return OfferRejection(
        traveler_id=traveler.traveler_id,
        city_id=city.city_id,
        offer_id=offer.offer_id,
        reason_codes=reasons,
    )


def evaluate_traveler_city_offers(
    traveler: TravelerRequest,
    city: City,
    origin_airport_codes: Collection[str],
    trip_start_date: date,
    trip_end_date: date,
    offers: Sequence[FlightOffer],
) -> ConstraintEvaluationResult:
    """Partition offers and exclude the city when no eligible offer remains."""
    eligible_offers: list[FlightOffer] = []
    rejected_offers: list[OfferRejection] = []

    for offer in offers:
        rejection = evaluate_offer(
            offer=offer,
            traveler=traveler,
            city=city,
            origin_airport_codes=origin_airport_codes,
            trip_start_date=trip_start_date,
            trip_end_date=trip_end_date,
        )
        if rejection is None:
            eligible_offers.append(offer)
        else:
            rejected_offers.append(rejection)

    city_exclusion = None
    if not eligible_offers:
        city_exclusion = CityExclusion(
            traveler_id=traveler.traveler_id,
            city_id=city.city_id,
        )

    return ConstraintEvaluationResult(
        traveler_id=traveler.traveler_id,
        city_id=city.city_id,
        eligible_offers=eligible_offers,
        rejected_offers=rejected_offers,
        city_exclusion=city_exclusion,
    )
