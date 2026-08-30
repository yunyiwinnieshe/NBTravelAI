"""Validation tests for destination and climate fixture contracts."""

from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from travel_ai.schemas.destinations import City, MonthlyClimate


def valid_city_data() -> dict[str, object]:
    """Return a valid metro-area destination record."""
    return {
        "city_id": "new_york_ny",
        "name": "New York City",
        "state_code": "NY",
        "country_code": "US",
        "metro_airport_codes": ["JFK", "LGA", "EWR"],
        "interest_tags": ["food", "museums", "nightlife", "shopping"],
        "data_version": "v1",
    }


def valid_climate_data() -> dict[str, object]:
    """Return a valid monthly climate record."""
    return {
        "city_id": "new_york_ny",
        "month": 10,
        "average_daytime_temperature_celsius": 18.2,
        "source": "Example climate normals",
        "source_url": "https://example.com/climate/new-york",
        "reference_period": "1991-2020",
        "retrieved_at": date.today().isoformat(),
        "data_version": "v1",
    }


def test_city_accepts_multiple_airports_and_controlled_interests() -> None:
    city = City.model_validate(valid_city_data())

    assert city.metro_airport_codes == ["JFK", "LGA", "EWR"]
    assert [tag.value for tag in city.interest_tags] == [
        "food",
        "museums",
        "nightlife",
        "shopping",
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("city_id", "New York"),
        ("state_code", "New York"),
        ("country_code", "CA"),
        ("metro_airport_codes", []),
        ("metro_airport_codes", ["jfk"]),
        ("metro_airport_codes", ["JFK", "JFK"]),
        ("interest_tags", ["food", "food"]),
        ("interest_tags", ["music"]),
        ("data_version", "one"),
    ],
)
def test_city_rejects_invalid_fixture_fields(field: str, value: object) -> None:
    city_data = valid_city_data()
    city_data[field] = value

    with pytest.raises(ValidationError):
        City.model_validate(city_data)


def test_city_rejects_unknown_fields() -> None:
    city_data = valid_city_data()
    city_data["ranking_score"] = 0.9

    with pytest.raises(ValidationError):
        City.model_validate(city_data)


def test_monthly_climate_accepts_valid_provenance() -> None:
    climate = MonthlyClimate.model_validate(valid_climate_data())

    assert climate.month == 10
    assert climate.average_daytime_temperature_celsius == 18.2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("month", 0),
        ("month", 13),
        ("average_daytime_temperature_celsius", -41),
        ("average_daytime_temperature_celsius", 61),
        ("source", ""),
        ("source_url", "not-a-url"),
        ("reference_period", ""),
        ("retrieved_at", (date.today() + timedelta(days=1)).isoformat()),
    ],
)
def test_monthly_climate_rejects_invalid_fields(field: str, value: object) -> None:
    climate_data = valid_climate_data()
    climate_data[field] = value

    with pytest.raises(ValidationError):
        MonthlyClimate.model_validate(climate_data)
