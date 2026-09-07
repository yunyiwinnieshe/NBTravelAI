"""Fixture-backed implementations of provider interfaces."""

from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from travel_ai.providers.base import FlightOfferProvider
from travel_ai.schemas.flights import FlightOffer, FlightSearchQuery

DEFAULT_FLIGHT_OFFERS_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "flight_offers.json"
)


class FixtureDataError(ValueError):
    """Raised when a fixture file cannot be read or validated."""


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
            offer
            for offer in self._offers
            if offer.destination_id == query.destination_id
            and offer.traveler_id == query.traveler_id
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
