"""Unit tests for the recommendation workflow service."""

from datetime import date

from travel_ai.schemas.trip import TravelerPreferences, TripRequest
from travel_ai.services.recommendation_service import RecommendationService


def test_recommendation_service_returns_placeholder_before_week_two() -> None:
    """The service owns the temporary response, not the HTTP router."""
    trip_request = TripRequest(
        travelers=[
            TravelerPreferences(
                origin="Boston, MA", budget_usd=2000, max_travel_time_hours=8
            ),
            TravelerPreferences(
                origin="San Francisco, CA", budget_usd=2000, max_travel_time_hours=8
            ),
        ],
        start_date=date(2026, 10, 9),
        end_date=date(2026, 10, 13),
    )

    response = RecommendationService().get_recommendations(trip_request)

    assert response.status == "not_implemented"
    assert response.recommendations == []
