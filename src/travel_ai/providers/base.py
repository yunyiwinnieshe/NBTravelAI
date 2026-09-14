"""Interfaces implemented by flight-offer data sources."""

from abc import ABC, abstractmethod

from travel_ai.schemas.flights import FlightOffer, FlightSearchQuery


class FlightOfferProvider(ABC):
    """Load normalized flight offers without exposing provider-specific JSON."""

    @abstractmethod
    def search(self, query: FlightSearchQuery) -> list[FlightOffer]:
        """Search every approved airport pair and return normalized offers."""
