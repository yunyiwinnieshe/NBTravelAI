"""Unit tests for the recommendation workflow service."""

from datetime import date

import pytest

from travel_ai.schemas.trip import TravelerRequest, TripPreferences, TripRequest
from travel_ai.services.recommendation_service import (
    RecommendationNotImplementedError,
    RecommendationService,
)


def test_recommendation_service_reports_pending_integration() -> None:
    """The service cannot claim a successful response before ranking is connected."""
    trip_request = TripRequest(
        travelers=[
            TravelerRequest(
                traveler_id="traveler_a",
                origin_id="boston_ma",
                budget_usd=2000,
                max_one_way_travel_minutes=480,
                preferences=TripPreferences(interest_tags=["food", "museums"]),
            ),
            TravelerRequest(
                traveler_id="traveler_b",
                origin_id="san_francisco_ca",
                budget_usd=2000,
                max_one_way_travel_minutes=480,
                preferences=TripPreferences(
                    interest_tags=["mountain", "outdoor_activities"]
                ),
            ),
        ],
        start_date=date(2026, 10, 9),
        end_date=date(2026, 10, 13),
    )

    with pytest.raises(
        RecommendationNotImplementedError,
        match="enabled after service integration",
    ):
        RecommendationService().get_recommendations(trip_request)
