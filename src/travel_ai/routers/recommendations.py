"""Recommendation HTTP routes."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from travel_ai.clients.duffel import (
    DuffelClient,
    DuffelConfigurationError,
    DuffelSettings,
)
from travel_ai.providers.duffel import DuffelFlightOfferProvider
from travel_ai.schemas.recommendations import RecommendationResponse
from travel_ai.schemas.trip import TripRequest
from travel_ai.services.live_origin_resolution import (
    SQLiteLocationStore,
    StoredOriginAirportProvider,
)
from travel_ai.services.recommendation_service import (
    RecommendationService,
    UnsupportedOriginError,
)

router = APIRouter(tags=["recommendations"])


@lru_cache
def get_recommendation_service() -> RecommendationService:
    """Choose test-mode Duffel offers when configured; keep examples opt-in."""
    mode = os.getenv("FLIGHT_PROVIDER", "fixture").strip().lower()
    if mode == "fixture":
        return RecommendationService()
    if mode != "duffel":
        raise DuffelConfigurationError("FLIGHT_PROVIDER must be fixture or duffel")
    origin_provider = None
    if os.getenv("ORIGIN_RESOLUTION_PROVIDER", "fixture").strip().lower() == "duffel":
        database_path = os.getenv("ORIGIN_LOCATION_DB_PATH")
        if not database_path or database_path == ":memory:":
            raise DuffelConfigurationError(
                "ORIGIN_LOCATION_DB_PATH must name a durable SQLite file"
            )
        origin_provider = StoredOriginAirportProvider(
            SQLiteLocationStore(Path(database_path))
        )
    return RecommendationService(
        flight_provider=DuffelFlightOfferProvider(
            DuffelClient(DuffelSettings.from_environment())
        ),
        origin_provider=origin_provider,
    )


@router.post("/recommendations", response_model=RecommendationResponse)
def create_recommendations(
    trip_request: TripRequest,
    service: Annotated[RecommendationService, Depends(get_recommendation_service)],
) -> RecommendationResponse:
    """Return recommendations from the configured flight data source."""
    try:
        return service.get_recommendations(trip_request)
    except UnsupportedOriginError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
