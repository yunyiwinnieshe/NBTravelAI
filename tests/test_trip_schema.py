"""Unit tests for the confirmed trip-request contracts."""

from decimal import Decimal

from travel_ai.schemas.trip import TravelerRequest, TripPreferences


def test_preferences_remove_duplicate_interests_without_reordering() -> None:
    """Canonical preferences contain unique tags in the user's original order."""
    preferences = TripPreferences(interest_tags=["food", "nature", "food", "museums"])

    assert preferences.interest_tags == ["food", "nature", "museums"]


def test_traveler_budget_uses_decimal_safe_money() -> None:
    """Airfare budgets avoid binary floating-point arithmetic."""
    traveler = TravelerRequest(
        traveler_id="traveler_a",
        origin_id="boston_ma",
        budget_usd="1200.50",
        max_one_way_travel_minutes=480,
    )

    assert traveler.budget_usd == Decimal("1200.50")
