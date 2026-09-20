"""Recommendation HTTP routes."""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from travel_ai.schemas.recommendations import RecommendationResponse
from travel_ai.schemas.trip import TripRequest
from travel_ai.services.recommendation_service import (
    RecommendationService,
    UnsupportedOriginError,
)

router = APIRouter(tags=["recommendations"])


@lru_cache
def get_recommendation_service() -> RecommendationService:
    """Load offline fixtures once; expose a dependency for API tests."""
    return RecommendationService()


@router.post("/recommendations", response_model=RecommendationResponse)
def create_recommendations(
    trip_request: TripRequest,
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
) -> RecommendationResponse:
    """Return fixture-backed recommendations for a validated trip request."""
    try:
        return service.get_recommendations(trip_request)
    except UnsupportedOriginError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
