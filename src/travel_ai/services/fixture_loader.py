"""Load and validate the versioned destination fixture dataset."""

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from travel_ai.schemas.destinations import City, MonthlyClimate

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CITIES_PATH = PROJECT_ROOT / "data" / "fixtures" / "cities.json"
DEFAULT_CLIMATE_PATH = PROJECT_ROOT / "data" / "fixtures" / "monthly_climate.json"

ModelT = TypeVar("ModelT", bound=BaseModel)


class FixtureValidationError(ValueError):
    """Raised when fixture files or their relationships are invalid."""


@dataclass(frozen=True)
class DestinationFixtures:
    """Validated destination records used by deterministic recommendation code."""

    cities: tuple[City, ...]
    monthly_climate: tuple[MonthlyClimate, ...]


def _load_records(path: Path, model: type[ModelT]) -> tuple[ModelT, ...]:
    """Read one JSON array and validate every item with the requested model."""
    try:
        raw_data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise FixtureValidationError(f"fixture file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise FixtureValidationError(
            f"fixture file contains invalid JSON: {path}"
        ) from error

    if not isinstance(raw_data, list):
        raise FixtureValidationError(f"fixture file must contain a JSON array: {path}")

    try:
        return tuple(model.model_validate(record) for record in raw_data)
    except ValidationError as error:
        raise FixtureValidationError(
            f"invalid record in fixture file: {path}"
        ) from error


def _duplicates(values: list[object]) -> set[object]:
    """Return values that occur more than once."""
    return {value for value, count in Counter(values).items() if count > 1}


def _validate_relationships(
    cities: tuple[City, ...],
    climate_records: tuple[MonthlyClimate, ...],
) -> None:
    """Validate uniqueness, references, coverage, and versions across files."""
    duplicate_city_ids = _duplicates([city.city_id for city in cities])
    if duplicate_city_ids:
        raise FixtureValidationError(
            f"duplicate city IDs: {sorted(duplicate_city_ids)}"
        )

    cities_by_id = {city.city_id: city for city in cities}
    unknown_city_ids = {
        record.city_id
        for record in climate_records
        if record.city_id not in cities_by_id
    }
    if unknown_city_ids:
        raise FixtureValidationError(
            f"climate records reference unknown city IDs: {sorted(unknown_city_ids)}"
        )

    duplicate_climate_keys = _duplicates(
        [(record.city_id, record.month) for record in climate_records]
    )
    if duplicate_climate_keys:
        raise FixtureValidationError(
            f"duplicate city/month climate records: {sorted(duplicate_climate_keys)}"
        )

    expected_months = set(range(1, 13))
    for city in cities:
        actual_months = {
            record.month for record in climate_records if record.city_id == city.city_id
        }
        if actual_months != expected_months:
            missing_months = sorted(expected_months - actual_months)
            raise FixtureValidationError(
                f"city {city.city_id} is missing climate months: {missing_months}"
            )

    mismatched_versions = [
        (record.city_id, record.month)
        for record in climate_records
        if record.data_version != cities_by_id[record.city_id].data_version
    ]
    if mismatched_versions:
        raise FixtureValidationError(
            "climate data versions do not match their city records: "
            f"{mismatched_versions}"
        )


def load_destination_fixtures(
    cities_path: Path = DEFAULT_CITIES_PATH,
    climate_path: Path = DEFAULT_CLIMATE_PATH,
) -> DestinationFixtures:
    """Load a complete, internally consistent destination fixture dataset."""
    cities = _load_records(cities_path, City)
    climate_records = _load_records(climate_path, MonthlyClimate)
    _validate_relationships(cities, climate_records)
    return DestinationFixtures(cities=cities, monthly_climate=climate_records)
