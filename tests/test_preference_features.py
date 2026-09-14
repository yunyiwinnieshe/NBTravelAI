"""Tests for deterministic preference and climate feature calculations."""

from datetime import date

import pytest

from travel_ai.schemas.destinations import City, MonthlyClimate
from travel_ai.schemas.trip import TemperatureRange, TripPreferences
from travel_ai.services.preference_features import (
    calculate_city_preference_features,
    calculate_interest_match,
    calculate_temperature_match,
    calculate_traveler_preference_features,
    calculate_trip_temperature,
)


def city() -> City:
    return City(
        city_id="san_diego_ca",
        name="San Diego",
        state_code="CA",
        metro_airport_codes=["SAN"],
        interest_tags=["beach", "food", "nature"],
        data_version="v1",
    )


def climate(month: int, temperature: float) -> MonthlyClimate:
    return MonthlyClimate(
        city_id="san_diego_ca",
        month=month,
        average_daytime_temperature_celsius=temperature,
        source="Test climate data",
        source_url="https://example.com/climate",
        reference_period="1991-2020",
        retrieved_at=date(2026, 1, 1),
        data_version="v1",
    )


def test_interest_match_uses_distinct_requested_tags() -> None:
    assert calculate_interest_match(
        ["food", "museums", "food"],
        ["food", "museums", "nightlife"],
    ) == pytest.approx(1.0)


def test_interest_match_returns_none_without_requested_interests() -> None:
    assert calculate_interest_match([], ["food"]) is None


def test_trip_temperature_weights_days_across_months() -> None:
    result = calculate_trip_temperature(
        date(2026, 9, 29),
        date(2026, 10, 2),
        [climate(9, 24), climate(10, 18)],
    )

    assert result == pytest.approx(21.0)


def test_trip_temperature_requires_every_relevant_month() -> None:
    with pytest.raises(ValueError, match="missing climate records"):
        calculate_trip_temperature(
            date(2026, 9, 29),
            date(2026, 10, 2),
            [climate(9, 24)],
        )


@pytest.mark.parametrize(
    ("temperature", "expected"),
    [
        (20, 1.0),
        (25, 1.0),
        (30, 1.0),
        (18, 0.8),
        (35, 0.5),
        (10, 0.0),
        (41, 0.0),
    ],
)
def test_temperature_match_declines_outside_range(
    temperature: float,
    expected: float,
) -> None:
    preferred_range = TemperatureRange(minimum_celsius=20, maximum_celsius=30)

    assert calculate_temperature_match(
        temperature,
        preferred_range,
    ) == pytest.approx(expected)


def test_temperature_match_returns_none_without_preference() -> None:
    assert calculate_temperature_match(25, None) is None


def test_traveler_score_equally_weights_available_categories() -> None:
    result = calculate_traveler_preference_features(
        traveler_id="traveler_a",
        preferences=TripPreferences(
            temperature_range={"minimum_celsius": 20, "maximum_celsius": 30},
            interest_tags=["food", "museums"],
        ),
        city_tags=["food"],
        trip_temperature_celsius=25,
    )

    assert result.interest_match == pytest.approx(0.5)
    assert result.temperature_match == pytest.approx(1.0)
    assert result.preference_score == pytest.approx(0.75)


def test_traveler_score_renormalizes_when_one_category_is_missing() -> None:
    result = calculate_traveler_preference_features(
        traveler_id="traveler_a",
        preferences=TripPreferences(interest_tags=["food", "museums"]),
        city_tags=["food"],
        trip_temperature_celsius=25,
    )

    assert result.preference_score == pytest.approx(0.5)
    assert result.temperature_match is None


def test_traveler_without_preferences_has_no_score() -> None:
    result = calculate_traveler_preference_features(
        traveler_id="traveler_a",
        preferences=TripPreferences(),
        city_tags=["food"],
        trip_temperature_celsius=25,
    )

    assert result.preference_score is None


def test_city_features_calculate_combined_score_gap_and_fairness() -> None:
    result = calculate_city_preference_features(
        city=city(),
        climate_records=[climate(10, 25)],
        start_date=date(2026, 10, 9),
        end_date=date(2026, 10, 13),
        traveler_preferences=(
            TripPreferences(
                temperature_range={"minimum_celsius": 20, "maximum_celsius": 30},
                interest_tags=["food", "museums"],
            ),
            TripPreferences(interest_tags=["food", "nature"]),
        ),
    )

    assert result.travelers[0].preference_score == pytest.approx(0.75)
    assert result.travelers[1].preference_score == pytest.approx(1.0)
    assert result.combined_preference_score == pytest.approx(0.875)
    assert result.preference_gap == pytest.approx(0.25)
    assert result.preference_fairness == pytest.approx(0.75)


def test_city_features_omit_fairness_with_one_traveler_score() -> None:
    result = calculate_city_preference_features(
        city=city(),
        climate_records=[climate(10, 25)],
        start_date=date(2026, 10, 9),
        end_date=date(2026, 10, 13),
        traveler_preferences=(
            TripPreferences(interest_tags=["food"]),
            TripPreferences(),
        ),
    )

    assert result.combined_preference_score == pytest.approx(1.0)
    assert result.preference_gap is None
    assert result.preference_fairness is None


def test_city_features_have_no_combined_score_without_preferences() -> None:
    result = calculate_city_preference_features(
        city=city(),
        climate_records=[climate(10, 25)],
        start_date=date(2026, 10, 9),
        end_date=date(2026, 10, 13),
        traveler_preferences=(TripPreferences(), TripPreferences()),
    )

    assert result.combined_preference_score is None
    assert result.preference_gap is None
    assert result.preference_fairness is None
