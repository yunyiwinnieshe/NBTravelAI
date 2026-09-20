"""Fixture-backed implementations of provider interfaces."""

from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from travel_ai.providers.base import FlightOfferProvider, OriginAirportProvider
from travel_ai.schemas.flights import FlightOffer, FlightSearchQuery
from travel_ai.schemas.locations import AirportReferenceDataset, OriginAirportMapping

DEFAULT_FLIGHT_OFFERS_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "flight_offers.json"
)
DEFAULT_AIRPORT_REFERENCE_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "airport_reference.json"
)
DEFAULT_ORIGIN_AIRPORTS_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "origin_airports.json"
)


class FixtureDataError(ValueError):
    """Raised when a fixture file cannot be read or validated."""


def load_airport_reference_dataset(
    fixture_path: Path = DEFAULT_AIRPORT_REFERENCE_PATH,
) -> AirportReferenceDataset:
    """Load and validate the versioned OurAirports reference subset."""
    try:
        fixture_json = fixture_path.read_text(encoding="utf-8")
    except OSError as error:
        raise FixtureDataError(
            f"Unable to read airport reference fixture: {fixture_path}"
        ) from error

    try:
        return AirportReferenceDataset.model_validate_json(fixture_json)
    except ValidationError as error:
        raise FixtureDataError(
            f"Invalid airport reference fixture: {fixture_path}"
        ) from error


def load_origin_airport_mappings(
    fixture_path: Path = DEFAULT_ORIGIN_AIRPORTS_PATH,
) -> list[OriginAirportMapping]:
    """Load and validate fixture-mode origin-to-airport mappings."""
    try:
        fixture_json = fixture_path.read_text(encoding="utf-8")
    except OSError as error:
        raise FixtureDataError(
            f"Unable to read origin airport fixture: {fixture_path}"
        ) from error

    try:
        airport_mappings = TypeAdapter(list[OriginAirportMapping]).validate_json(
            fixture_json
        )
    except ValidationError as error:
        raise FixtureDataError(
            f"Invalid origin airport fixture: {fixture_path}"
        ) from error

    origin_ids = [mapping.origin_id for mapping in airport_mappings]
    if len(origin_ids) != len(set(origin_ids)):
        raise FixtureDataError("origin airport fixture contains duplicate origin IDs")
    return airport_mappings


class FixtureFlightOfferProvider(FlightOfferProvider):
    """Load deterministic, normalized round-trip offers from versioned JSON."""

    def __init__(self, fixture_path: Path = DEFAULT_FLIGHT_OFFERS_PATH) -> None:
        self._fixture_path = fixture_path
        self._offers = self._load_offers()

    def _load_offers(self) -> list[FlightOffer]:
        try:
            fixture_json = self._fixture_path.read_text(encoding="utf-8")
        except OSError as error:
            raise FixtureDataError(
                f"Unable to read flight fixture: {self._fixture_path}"
            ) from error

        try:
            return TypeAdapter(list[FlightOffer]).validate_json(fixture_json)
        except ValidationError as error:
            raise FixtureDataError(
                f"Invalid flight fixture: {self._fixture_path}"
            ) from error

    def search(self, query: FlightSearchQuery) -> list[FlightOffer]:
        """Return airport-group/date matches; constraints remain service concerns."""
        return [
            offer.model_copy(update={"traveler_id": query.traveler_id}, deep=True)
            for offer in self._offers
            if offer.destination_id == query.destination_id
            and offer.origin_id == query.origin_id
            and offer.cabin_class == query.cabin_class
            and offer.outbound_slice.origin_airport_code in query.origin_airport_codes
            and offer.outbound_slice.destination_airport_code
            in query.destination_airport_codes
            and offer.return_slice.origin_airport_code
            in query.destination_airport_codes
            and offer.return_slice.destination_airport_code
            in query.origin_airport_codes
            and offer.outbound_slice.segments[0].departure_at.date()
            == query.departure_date
            and offer.return_slice.segments[0].departure_at.date() == query.return_date
        ]


class FixtureOriginAirportProvider(OriginAirportProvider):
    """Resolve fixture origins without calling live place or geocoding services."""

    def __init__(self, fixture_path: Path = DEFAULT_ORIGIN_AIRPORTS_PATH) -> None:
        airport_mappings = load_origin_airport_mappings(fixture_path)
        self._airport_mappings_by_origin_id = {
            mapping.origin_id: mapping for mapping in airport_mappings
        }

    def resolve(self, origin_id: str) -> OriginAirportMapping:
        """Return the configured airport mapping or raise a clear fixture error."""
        try:
            return self._airport_mappings_by_origin_id[origin_id]
        except KeyError as error:
            raise FixtureDataError(
                f"origin ID is not configured in fixture airports: {origin_id}"
            ) from error
