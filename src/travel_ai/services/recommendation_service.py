"""Coordinate fixture-backed, deterministic recommendations for two travelers."""

import logging
from collections.abc import Callable
from datetime import UTC, datetime

from travel_ai.providers.base import FlightOfferProvider, OriginAirportProvider
from travel_ai.providers.fixtures import (
    FixtureDataError,
    FixtureFlightOfferProvider,
    FixtureOriginAirportProvider,
)
from travel_ai.schemas.flights import FlightOffer, FlightSearchQuery, FlightSlice
from travel_ai.schemas.ranking import DestinationRankingInput
from travel_ai.schemas.recommendations import (
    DestinationExclusion,
    DestinationRecommendation,
    DestinationSummary,
    FlightJourneySummary,
    FlightOption,
    PairPriceComparison,
    RecommendationMetadata,
    RecommendationResponse,
    RecommendedFlightPair,
    TravelerFlightOptions,
    TravelerOfferReference,
)
from travel_ai.schemas.trip import TripRequest
from travel_ai.services.constraint_engine import evaluate_traveler_city_offers
from travel_ai.services.destination_ranking import rank_destinations
from travel_ai.services.fixture_loader import (
    DestinationFixtures,
    load_destination_fixtures,
)
from travel_ai.services.flight_offer_selection import (
    build_flight_offer_pairs,
    flight_option_category_ids,
    select_display_flight_offers,
    select_recommended_flight_pair,
)
from travel_ai.services.preference_features import calculate_city_preference_features

logger = logging.getLogger(__name__)


class UnsupportedOriginError(ValueError):
    """A request origin is not present in the configured fixture mapping."""


def _journey(flight_slice: FlightSlice) -> FlightJourneySummary:
    return FlightJourneySummary(
        origin_airport_code=flight_slice.origin_airport_code,
        destination_airport_code=flight_slice.destination_airport_code,
        departure_at=flight_slice.segments[0].departure_at,
        arrival_at=flight_slice.segments[-1].arrival_at,
        duration_minutes=flight_slice.duration_minutes,
        connection_count=flight_slice.connection_count,
        carrier_codes=list(
            dict.fromkeys(
                segment.marketing_carrier_code for segment in flight_slice.segments
            )
        ),
    )


def _flight_options(
    traveler_id: str,
    offers: list[FlightOffer],
    recommended_id: str,
) -> TravelerFlightOptions:
    categories = flight_option_category_ids(offers, recommended_id)
    return TravelerFlightOptions(
        traveler_id=traveler_id,
        options=[
            FlightOption(
                offer_id=offer.offer_id,
                traveler_id=traveler_id,
                labels=[
                    label
                    for label, offer_id in categories.items()
                    if offer_id == offer.offer_id
                ],
                round_trip_price_usd=offer.total_amount,
                outbound=_journey(offer.outbound_slice),
                return_flight=_journey(offer.return_slice),
                total_travel_minutes=offer.total_travel_minutes,
                total_connections=offer.total_connections,
                is_round_trip_nonstop=offer.is_round_trip_nonstop,
                expires_at=offer.expires_at,
            )
            for offer in select_display_flight_offers(offers, recommended_id)
        ],
    )


class RecommendationService:
    """Search, filter, pair, rank, and serialize the offline candidate pool."""

    def __init__(
        self,
        flight_provider: FlightOfferProvider | None = None,
        origin_provider: OriginAirportProvider | None = None,
        destinations: DestinationFixtures | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.flight_provider = flight_provider or FixtureFlightOfferProvider()
        self._validate_provider_mode()
        self.origin_provider = origin_provider or FixtureOriginAirportProvider()
        self.destinations = destinations or load_destination_fixtures()
        self.clock = clock or (lambda: datetime.now(UTC))
        versions = {city.data_version for city in self.destinations.cities}
        if len(versions) != 1:
            raise ValueError("candidate pool must contain exactly one data version")
        self.candidate_pool_version = versions.pop()

    def _validate_provider_mode(self) -> None:
        """Reject unsupported providers before they can perform any search."""
        if self.flight_provider.data_mode != "fixture":
            raise ValueError("this workflow currently supports fixture providers only")

    def get_recommendations(self, trip_request: TripRequest) -> RecommendationResponse:
        """Return up to three eligible cities or an explained no-match result."""
        self._validate_provider_mode()
        evaluated_at = self.clock()
        if evaluated_at.utcoffset() is None:
            raise ValueError("recommendation clock must include a timezone")
        travelers = tuple(trip_request.travelers)
        origins = {}
        for traveler in travelers:
            try:
                origins[traveler.traveler_id] = self.origin_provider.resolve(
                    traveler.origin_id
                ).airport_codes
            except FixtureDataError as error:
                raise UnsupportedOriginError(str(error)) from error

        candidates = []
        exclusions = []
        presentation = {}
        for city in self.destinations.cities:
            eligible = []
            for traveler in travelers:
                query = FlightSearchQuery(
                    traveler_id=traveler.traveler_id,
                    origin_id=traveler.origin_id,
                    destination_id=city.city_id,
                    origin_airport_codes=origins[traveler.traveler_id],
                    destination_airport_codes=city.metro_airport_codes,
                    departure_date=trip_request.start_date,
                    return_date=trip_request.end_date,
                )
                offers = self.flight_provider.search(query)
                if any(not offer.is_fixture for offer in offers):
                    raise ValueError(
                        "this workflow currently supports fixture offers only"
                    )
                result = evaluate_traveler_city_offers(
                    traveler,
                    city,
                    query.origin_airport_codes,
                    trip_request.start_date,
                    trip_request.end_date,
                    offers,
                )
                for rejection in result.rejected_offers:
                    logger.info(
                        "recommendation_offer_rejected",
                        extra={
                            "traveler_id": rejection.traveler_id,
                            "destination_id": rejection.city_id,
                            "offer_id": rejection.offer_id,
                            "reason_codes": [
                                reason.value for reason in rejection.reason_codes
                            ],
                        },
                    )
                eligible.append(result.eligible_offers)
                if result.city_exclusion:
                    exclusions.append(
                        DestinationExclusion(
                            destination_id=city.city_id,
                            traveler_id=traveler.traveler_id,
                            reason_code="no_eligible_flight",
                        )
                    )
            if not all(eligible):
                continue
            pairs = build_flight_offer_pairs(eligible[0], eligible[1])
            if not pairs:
                exclusions.append(
                    DestinationExclusion(
                        destination_id=city.city_id,
                        reason_code="no_compatible_flight_pair",
                    )
                )
                continue
            selected = select_recommended_flight_pair(pairs)
            pair = selected.pair
            selected_ids = {pair.traveler_a_offer_id, pair.traveler_b_offer_id}
            features = calculate_city_preference_features(
                city,
                [
                    record
                    for record in self.destinations.monthly_climate
                    if record.city_id == city.city_id
                ],
                trip_request.start_date,
                trip_request.end_date,
                tuple(traveler.preferences for traveler in travelers),
                traveler_ids=tuple(traveler.traveler_id for traveler in travelers),
            )
            candidates.append(
                DestinationRankingInput(
                    destination_id=city.city_id,
                    travelers=travelers,
                    recommended_pair=selected,
                    recommended_offers=tuple(
                        offer
                        for offers in eligible
                        for offer in offers
                        if offer.offer_id in selected_ids
                    ),
                    preference_features=features,
                )
            )
            baseline = min(item.combined_price_usd for item in pairs)
            premium = pair.combined_price_usd - baseline
            public_pair = RecommendedFlightPair(
                offers=[
                    TravelerOfferReference(traveler_id=traveler_id, offer_id=offer_id)
                    for traveler_id, offer_id in (
                        (pair.traveler_a_id, pair.traveler_a_offer_id),
                        (pair.traveler_b_id, pair.traveler_b_offer_id),
                    )
                ],
                **pair.model_dump(
                    include={
                        "combined_price_usd",
                        "arrival_gap_minutes",
                        "return_departure_gap_minutes",
                        "time_together_minutes",
                        "total_connections",
                        "combined_travel_minutes",
                    }
                ),
                selection_score=selected.selection_score,
                selection_score_breakdown=selected.score_breakdown,
                price_comparison=PairPriceComparison(
                    lowest_valid_combined_price_usd=baseline,
                    premium_usd=premium,
                    premium_percentage=float(premium / baseline * 100),
                ),
            )
            presentation[city.city_id] = (
                city,
                public_pair,
                [
                    _flight_options(
                        travelers[0].traveler_id, eligible[0], pair.traveler_a_offer_id
                    ),
                    _flight_options(
                        travelers[1].traveler_id, eligible[1], pair.traveler_b_offer_id
                    ),
                ],
            )

        ranked = rank_destinations(candidates)
        recommendations = []
        for rank, result in enumerate(ranked[:3], start=1):
            city, pair, options = presentation[result.destination_id]
            recommendations.append(
                DestinationRecommendation(
                    rank=rank,
                    destination=DestinationSummary(
                        destination_id=city.city_id,
                        name=city.name,
                        state_code=city.state_code,
                        metro_airport_codes=city.metro_airport_codes,
                    ),
                    score=result.score,
                    score_breakdown=result.score_breakdown,
                    recommended_pair=pair,
                    flight_options_by_traveler=options,
                )
            )
        return RecommendationResponse(
            status="success" if recommendations else "no_match",
            recommendations=recommendations,
            exclusions=exclusions,
            metadata=RecommendationMetadata(
                evaluated_at=evaluated_at,
                candidate_pool_version=self.candidate_pool_version,
                data_mode="fixture",
                eligible_destination_count=len(ranked),
            ),
        )
