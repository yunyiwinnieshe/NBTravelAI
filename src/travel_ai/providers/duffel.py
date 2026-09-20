"""Duffel-backed normalized round-trip flight offer provider."""

import hashlib
import re
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from math import ceil
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from travel_ai.clients.duffel import DuffelClient, DuffelResponseError
from travel_ai.providers.base import AirportPlaceProvider, FlightOfferProvider
from travel_ai.schemas.flights import (
    FlightOffer,
    FlightSearchQuery,
    FlightSegment,
    FlightSlice,
)
from travel_ai.schemas.locations import (
    AirportCandidate,
    LocationSearchQuery,
)

ISO_DURATION_PATTERN = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


class _DuffelPlace(BaseModel):
    model_config = ConfigDict(extra="ignore")

    iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    time_zone: str = Field(min_length=1)


class _DuffelCarrier(BaseModel):
    model_config = ConfigDict(extra="ignore")

    iata_code: str = Field(pattern=r"^[A-Z0-9]{2}$")


class _DuffelSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    origin: _DuffelPlace
    destination: _DuffelPlace
    departing_at: datetime
    arriving_at: datetime
    marketing_carrier: _DuffelCarrier
    operating_carrier: _DuffelCarrier
    marketing_carrier_flight_number: str = Field(min_length=1, max_length=8)


class _DuffelSlice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    duration: str
    segments: list[_DuffelSegment] = Field(min_length=1)


class _DuffelOffer(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=200)
    total_amount: Decimal = Field(gt=0)
    total_currency: str
    expires_at: datetime | None = None
    slices: list[_DuffelSlice] = Field(min_length=2, max_length=2)


class _DuffelOfferRequestData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    offers: list[_DuffelOffer] = Field(default_factory=list)


class _DuffelEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: _DuffelOfferRequestData


class _DuffelAirportSuggestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=100)
    type: str = "airport"
    iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=200)
    city_name: str | None = Field(default=None, max_length=120)
    iata_country_code: str = Field(pattern=r"^[A-Z]{2}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    time_zone: str | None = Field(default=None, max_length=100)


class _DuffelPlaceSuggestion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=100)
    type: str
    iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=200)
    city_name: str | None = Field(default=None, max_length=120)
    iata_country_code: str = Field(pattern=r"^[A-Z]{2}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    time_zone: str | None = Field(default=None, max_length=100)
    airports: list[_DuffelAirportSuggestion] | None = None


class _DuffelPlacesEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: list[_DuffelPlaceSuggestion]


def _duration_minutes(duration: str) -> int:
    """Convert an ISO-8601 Duffel duration to whole minutes, rounding up."""
    match = ISO_DURATION_PATTERN.fullmatch(duration)
    if match is None or not any(match.groupdict().values()):
        raise DuffelResponseError(f"Invalid Duffel duration: {duration}")

    total_seconds = (
        int(match.group("days") or 0) * 86_400
        + int(match.group("hours") or 0) * 3_600
        + int(match.group("minutes") or 0) * 60
        + float(match.group("seconds") or 0)
    )
    if total_seconds <= 0:
        raise DuffelResponseError("Duffel duration must be positive")
    return ceil(total_seconds / 60)


def _internal_offer_id(provider_offer_id: str) -> str:
    """Create a stable, schema-safe internal ID without leaking provider format."""
    digest = hashlib.sha256(provider_offer_id.encode("utf-8")).hexdigest()[:20]
    return f"duffel_{digest}"


def _airport_local_datetime(value: datetime, time_zone: str) -> datetime:
    """Attach an airport's IANA timezone to Duffel's local datetime."""
    try:
        airport_time_zone = ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as error:
        raise DuffelResponseError(
            f"Duffel returned an unknown airport timezone: {time_zone}"
        ) from error

    if value.tzinfo is None:
        return value.replace(tzinfo=airport_time_zone)
    return value.astimezone(airport_time_zone)


class DuffelAirportPlaceProvider(AirportPlaceProvider):
    """Normalize Duffel Place Suggestions into airport candidates."""

    def __init__(self, client: DuffelClient) -> None:
        self._client = client

    def search_airports(self, query: LocationSearchQuery) -> list[AirportCandidate]:
        """Expand city results, include airport results, and deduplicate by code."""
        response = self._client.get_place_suggestions(
            query=query.query,
            latitude=query.latitude,
            longitude=query.longitude,
            radius_metres=query.radius_metres,
        )
        try:
            places = _DuffelPlacesEnvelope.model_validate(response).data
        except ValidationError as error:
            raise DuffelResponseError(
                "Duffel place response did not match the expected schema"
            ) from error

        candidates_by_code: dict[str, AirportCandidate] = {}
        for place in places:
            raw_airports: list[tuple[_DuffelAirportSuggestion, bool]] = []
            if place.type == "city":
                raw_airports.extend(
                    (airport, True) for airport in (place.airports or [])
                )
            elif place.type == "airport":
                raw_airports.append(
                    (
                        _DuffelAirportSuggestion.model_validate(place.model_dump()),
                        False,
                    )
                )

            for airport, associated_with_city in raw_airports:
                if airport.iata_country_code != query.country_code:
                    continue
                candidate = AirportCandidate(
                    provider_place_id=airport.id,
                    iata_code=airport.iata_code,
                    name=airport.name,
                    city_name=airport.city_name,
                    country_code=airport.iata_country_code,
                    latitude=airport.latitude,
                    longitude=airport.longitude,
                    time_zone=airport.time_zone,
                    associated_with_selected_city=associated_with_city,
                )
                existing = candidates_by_code.get(candidate.iata_code)
                if existing is None or (
                    candidate.associated_with_selected_city
                    and not existing.associated_with_selected_city
                ):
                    candidates_by_code[candidate.iata_code] = candidate

        return sorted(candidates_by_code.values(), key=lambda item: item.iata_code)


class DuffelFlightOfferProvider(FlightOfferProvider):
    """Search approved airport pairs and normalize Duffel sandbox offers."""

    @property
    def data_mode(self) -> Literal["fixture", "live"]:
        """Identify this provider's source without executing a search."""
        return "live"

    def __init__(
        self,
        client: DuffelClient,
        *,
        clock: Callable[[], datetime] | None = None,
        maximum_offers: int = 20,
    ) -> None:
        if maximum_offers <= 0:
            raise ValueError("maximum_offers must be positive")
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))
        self._maximum_offers = maximum_offers

    def search(self, query: FlightSearchQuery) -> list[FlightOffer]:
        """Search every explicit airport pair and return deterministic offers."""
        retrieved_at = self._clock()
        if retrieved_at.tzinfo is None:
            raise ValueError("provider clock must return a timezone-aware datetime")

        normalized_by_provider_id: dict[str, FlightOffer] = {}
        for origin_code, destination_code in query.airport_pairs:
            raw_response = self._client.create_offer_request(
                origin_airport_code=origin_code,
                destination_airport_code=destination_code,
                departure_date=query.departure_date,
                return_date=query.return_date,
                cabin_class=query.cabin_class,
            )
            for raw_offer in self._parse_offers(raw_response):
                normalized_by_provider_id.setdefault(
                    raw_offer.id,
                    self._normalize_offer(raw_offer, query, retrieved_at),
                )

        return self._select_bounded_offers(list(normalized_by_provider_id.values()))

    def _select_bounded_offers(
        self,
        offers: list[FlightOffer],
    ) -> list[FlightOffer]:
        """Retain a deterministic mix of price, time, and connection winners."""
        rankings = (
            sorted(
                offers,
                key=lambda offer: (
                    offer.total_amount,
                    offer.total_travel_minutes,
                    offer.total_connections,
                    offer.offer_id,
                ),
            ),
            sorted(
                offers,
                key=lambda offer: (
                    offer.total_travel_minutes,
                    offer.total_amount,
                    offer.total_connections,
                    offer.offer_id,
                ),
            ),
            sorted(
                offers,
                key=lambda offer: (
                    offer.total_connections,
                    offer.total_amount,
                    offer.total_travel_minutes,
                    offer.offer_id,
                ),
            ),
        )
        selected: list[FlightOffer] = []
        selected_ids: set[str] = set()
        for rank_index in range(len(offers)):
            for ranking in rankings:
                candidate = ranking[rank_index]
                if candidate.offer_id in selected_ids:
                    continue
                selected.append(candidate)
                selected_ids.add(candidate.offer_id)
                if len(selected) == self._maximum_offers:
                    return selected
        return selected

    @staticmethod
    def _parse_offers(raw_response: dict[str, object]) -> list[_DuffelOffer]:
        try:
            return _DuffelEnvelope.model_validate(raw_response).data.offers
        except ValidationError as error:
            raise DuffelResponseError(
                "Duffel offer response did not match the expected schema"
            ) from error

    @staticmethod
    def _normalize_offer(
        raw_offer: _DuffelOffer,
        query: FlightSearchQuery,
        retrieved_at: datetime,
    ) -> FlightOffer:
        if raw_offer.total_currency != "USD":
            raise DuffelResponseError(
                f"Unsupported Duffel offer currency: {raw_offer.total_currency}"
            )

        try:
            outbound_slice = DuffelFlightOfferProvider._normalize_slice(
                raw_offer.slices[0]
            )
            return_slice = DuffelFlightOfferProvider._normalize_slice(
                raw_offer.slices[1]
            )
            return FlightOffer(
                offer_id=_internal_offer_id(raw_offer.id),
                provider="duffel",
                provider_offer_id=raw_offer.id,
                traveler_id=query.traveler_id,
                origin_id=query.origin_id,
                destination_id=query.destination_id,
                cabin_class=query.cabin_class,
                total_amount=raw_offer.total_amount,
                currency=raw_offer.total_currency,
                outbound_slice=outbound_slice,
                return_slice=return_slice,
                retrieved_at=retrieved_at,
                expires_at=raw_offer.expires_at,
                is_available=True,
                is_fixture=False,
            )
        except ValidationError as error:
            raise DuffelResponseError(
                "Duffel offer could not be normalized into the flight contract"
            ) from error

    @staticmethod
    def _normalize_slice(raw_slice: _DuffelSlice) -> FlightSlice:
        segments = [
            FlightSegment(
                origin_airport_code=segment.origin.iata_code,
                destination_airport_code=segment.destination.iata_code,
                departure_at=_airport_local_datetime(
                    segment.departing_at,
                    segment.origin.time_zone,
                ),
                arrival_at=_airport_local_datetime(
                    segment.arriving_at,
                    segment.destination.time_zone,
                ),
                marketing_carrier_code=segment.marketing_carrier.iata_code,
                operating_carrier_code=segment.operating_carrier.iata_code,
                flight_number=segment.marketing_carrier_flight_number,
            )
            for segment in raw_slice.segments
        ]
        return FlightSlice(
            origin_airport_code=segments[0].origin_airport_code,
            destination_airport_code=segments[-1].destination_airport_code,
            duration_minutes=_duration_minutes(raw_slice.duration),
            segments=segments,
        )
