"""Pure deterministic calculations for destination preference features."""

from collections import Counter
from collections.abc import Collection, Sequence
from datetime import date, timedelta

from travel_ai.schemas.destinations import City, MonthlyClimate
from travel_ai.schemas.preference_features import (
    CityPreferenceFeatures,
    TravelerPreferenceFeatures,
)
from travel_ai.schemas.trip import InterestTag, TemperatureRange, TripPreferences

TEMPERATURE_WEIGHT = 0.5
INTEREST_WEIGHT = 0.5
TEMPERATURE_ZERO_MATCH_DISTANCE_CELSIUS = 10.0


def calculate_interest_match(
    requested_tags: Collection[InterestTag],
    city_tags: Collection[InterestTag],
) -> float | None:
    """Return the share of distinct requested interests supported by a city."""
    requested = set(requested_tags)
    if not requested:
        return None
    return len(requested.intersection(city_tags)) / len(requested)


def calculate_trip_temperature(
    start_date: date,
    end_date: date,
    climate_records: Sequence[MonthlyClimate],
) -> float:
    """Return a day-weighted historical temperature across the trip dates."""
    if end_date < start_date:
        raise ValueError("end_date must be greater than or equal to start_date")

    records_by_month = {record.month: record for record in climate_records}
    if len(records_by_month) != len(climate_records):
        raise ValueError("climate records must contain at most one record per month")

    trip_day_counts: Counter[int] = Counter()
    current_date = start_date
    while current_date <= end_date:
        trip_day_counts[current_date.month] += 1
        current_date += timedelta(days=1)

    missing_months = sorted(set(trip_day_counts).difference(records_by_month))
    if missing_months:
        raise ValueError(f"missing climate records for months: {missing_months}")

    total_days = sum(trip_day_counts.values())
    weighted_total = sum(
        records_by_month[month].average_daytime_temperature_celsius * day_count
        for month, day_count in trip_day_counts.items()
    )
    return weighted_total / total_days


def calculate_temperature_match(
    trip_temperature_celsius: float,
    preferred_range: TemperatureRange | None,
) -> float | None:
    """Score temperature, reaching zero ten degrees outside the preferred range."""
    if preferred_range is None:
        return None

    if trip_temperature_celsius < preferred_range.minimum_celsius:
        distance = preferred_range.minimum_celsius - trip_temperature_celsius
    elif trip_temperature_celsius > preferred_range.maximum_celsius:
        distance = trip_temperature_celsius - preferred_range.maximum_celsius
    else:
        distance = 0.0

    return max(0.0, 1.0 - distance / TEMPERATURE_ZERO_MATCH_DISTANCE_CELSIUS)


def calculate_traveler_preference_features(
    traveler_id: str,
    preferences: TripPreferences,
    city_tags: Collection[InterestTag],
    trip_temperature_celsius: float,
) -> TravelerPreferenceFeatures:
    """Calculate available preference categories and their equal-weight score."""
    interest_match = calculate_interest_match(preferences.interest_tags, city_tags)
    temperature_match = calculate_temperature_match(
        trip_temperature_celsius,
        preferences.temperature_range,
    )

    weighted_total = 0.0
    active_weight = 0.0
    if interest_match is not None:
        weighted_total += interest_match * INTEREST_WEIGHT
        active_weight += INTEREST_WEIGHT
    if temperature_match is not None:
        weighted_total += temperature_match * TEMPERATURE_WEIGHT
        active_weight += TEMPERATURE_WEIGHT

    preference_score = weighted_total / active_weight if active_weight else None
    return TravelerPreferenceFeatures(
        traveler_id=traveler_id,
        interest_match=interest_match,
        temperature_match=temperature_match,
        preference_score=preference_score,
    )


def calculate_city_preference_features(
    city: City,
    climate_records: Sequence[MonthlyClimate],
    start_date: date,
    end_date: date,
    traveler_preferences: tuple[TripPreferences, TripPreferences],
) -> CityPreferenceFeatures:
    """Calculate preference satisfaction and fairness for both travelers."""
    wrong_city_ids = {
        record.city_id for record in climate_records if record.city_id != city.city_id
    }
    if wrong_city_ids:
        raise ValueError(
            f"climate records do not belong to city {city.city_id}: "
            f"{sorted(wrong_city_ids)}"
        )

    trip_temperature = calculate_trip_temperature(
        start_date,
        end_date,
        climate_records,
    )
    travelers = tuple(
        calculate_traveler_preference_features(
            traveler_id=f"traveler_{suffix}",
            preferences=preferences,
            city_tags=city.interest_tags,
            trip_temperature_celsius=trip_temperature,
        )
        for suffix, preferences in zip(("a", "b"), traveler_preferences, strict=True)
    )
    scores = [
        traveler.preference_score
        for traveler in travelers
        if traveler.preference_score is not None
    ]

    combined_score = sum(scores) / len(scores) if scores else None
    if len(scores) == 2:
        preference_gap = abs(scores[0] - scores[1])
        preference_fairness = 1.0 - preference_gap
    else:
        preference_gap = None
        preference_fairness = None

    return CityPreferenceFeatures(
        city_id=city.city_id,
        trip_temperature_celsius=trip_temperature,
        travelers=travelers,
        combined_preference_score=combined_score,
        preference_gap=preference_gap,
        preference_fairness=preference_fairness,
    )
