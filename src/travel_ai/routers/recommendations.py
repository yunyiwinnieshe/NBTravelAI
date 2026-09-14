"""Recommendation HTTP routes."""

from fastapi import APIRouter, HTTPException, status

from travel_ai.schemas.recommendations import RecommendationResponse
from travel_ai.schemas.trip import TripRequest
from travel_ai.services.recommendation_service import (
    RecommendationNotImplementedError,
    RecommendationService,
)

router = APIRouter(tags=["recommendations"])
recommendation_service = RecommendationService()


@router.post("/recommendations", response_model=RecommendationResponse)
def create_recommendations(trip_request: TripRequest) -> RecommendationResponse:
    """Return recommendations for a complete, validated trip request."""
    try:
        return recommendation_service.get_recommendations(trip_request)
    except RecommendationNotImplementedError as error:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(error),
        ) from error
