"""Recommendation workflow orchestration."""

from travel_ai.schemas.recommendations import (
    RecommendationResponse,
    RecommendationStatus,
)
from travel_ai.schemas.trip import TripRequest


class RecommendationService:
    """Coordinate deterministic recommendation work as the project grows."""

    def get_recommendations(self, _trip_request: TripRequest) -> RecommendationResponse:
        """Return a placeholder until fixture providers and ranking are implemented."""
        return RecommendationResponse(
            status=RecommendationStatus.NOT_IMPLEMENTED,
            recommendations=[],
            message=(
                "Trip request is valid. Deterministic destination ranking "
                "will be added in Week 2."
            ),
        )
