"""Interfaces implemented by flight-offer data sources."""

from abc import ABC, abstractmethod

from travel_ai.schemas.flights import FlightOffer, FlightSearchQuery
from travel_ai.schemas.locations import AirportCandidate, LocationSearchQuery


class FlightOfferProvider(ABC):
    """Load normalized flight offers without exposing provider-specific JSON."""

    @abstractmethod
    def search(self, query: FlightSearchQuery) -> list[FlightOffer]:
        """Search every approved airport pair and return normalized offers."""


class AirportPlaceProvider(ABC):
    """Resolve text or coordinates into provider-independent airport candidates."""

    @abstractmethod
    def search_airports(self, query: LocationSearchQuery) -> list[AirportCandidate]:
        """Return airport candidates for deterministic commercial filtering."""
