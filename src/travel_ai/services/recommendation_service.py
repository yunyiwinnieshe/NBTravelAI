"""Recommendation workflow orchestration."""

from travel_ai.schemas.recommendations import RecommendationResponse
from travel_ai.schemas.trip import TripRequest


class RecommendationNotImplementedError(RuntimeError):
    """Raised until the ranking workflow can produce the finalized contract."""


class RecommendationService:
    """Coordinate deterministic recommendation work as the project grows."""

    def get_recommendations(self, _trip_request: TripRequest) -> RecommendationResponse:
        """Reject execution until providers and ranking produce real results."""
        raise RecommendationNotImplementedError(
            "Recommendation generation will be enabled after service integration."
        )
