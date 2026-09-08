"""Tests for loading and validating destination fixtures."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from travel_ai.services.fixture_loader import (
    DEFAULT_CITIES_PATH,
    DEFAULT_CLIMATE_PATH,
    FixtureValidationError,
    load_destination_fixtures,
)


def _read_json(path: Path) -> list[dict[str, object]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_fixture_pair(
    tmp_path: Path,
    cities: list[dict[str, object]],
    climate: list[dict[str, object]],
) -> tuple[Path, Path]:
    cities_path = tmp_path / "cities.json"
    climate_path = tmp_path / "monthly_climate.json"
    cities_path.write_text(json.dumps(cities), encoding="utf-8")
    climate_path.write_text(json.dumps(climate), encoding="utf-8")
    return cities_path, climate_path


def test_loads_default_destination_fixtures() -> None:
    fixtures = load_destination_fixtures()

    assert len(fixtures.cities) == 10
    assert len(fixtures.monthly_climate) == 120


def test_rejects_duplicate_city_ids(tmp_path: Path) -> None:
    cities = _read_json(DEFAULT_CITIES_PATH)
    climate = _read_json(DEFAULT_CLIMATE_PATH)
    cities.append(deepcopy(cities[0]))
    paths = _write_fixture_pair(tmp_path, cities, climate)

    with pytest.raises(FixtureValidationError, match="duplicate city IDs"):
        load_destination_fixtures(*paths)


def test_rejects_unknown_climate_city(tmp_path: Path) -> None:
    cities = _read_json(DEFAULT_CITIES_PATH)
    climate = _read_json(DEFAULT_CLIMATE_PATH)
    climate[0]["city_id"] = "unknown_city"
    paths = _write_fixture_pair(tmp_path, cities, climate)

    with pytest.raises(FixtureValidationError, match="unknown city IDs"):
        load_destination_fixtures(*paths)


def test_rejects_duplicate_city_month(tmp_path: Path) -> None:
    cities = _read_json(DEFAULT_CITIES_PATH)
    climate = _read_json(DEFAULT_CLIMATE_PATH)
    climate.append(deepcopy(climate[0]))
    paths = _write_fixture_pair(tmp_path, cities, climate)

    with pytest.raises(FixtureValidationError, match="duplicate city/month"):
        load_destination_fixtures(*paths)


def test_rejects_incomplete_monthly_climate(tmp_path: Path) -> None:
    cities = _read_json(DEFAULT_CITIES_PATH)
    climate = _read_json(DEFAULT_CLIMATE_PATH)[1:]
    paths = _write_fixture_pair(tmp_path, cities, climate)

    with pytest.raises(FixtureValidationError, match="missing climate months"):
        load_destination_fixtures(*paths)


def test_rejects_mismatched_data_versions(tmp_path: Path) -> None:
    cities = _read_json(DEFAULT_CITIES_PATH)
    climate = _read_json(DEFAULT_CLIMATE_PATH)
    climate[0]["data_version"] = "v2"
    paths = _write_fixture_pair(tmp_path, cities, climate)

    with pytest.raises(FixtureValidationError, match="versions do not match"):
        load_destination_fixtures(*paths)


def test_rejects_invalid_json(tmp_path: Path) -> None:
    cities_path = tmp_path / "cities.json"
    cities_path.write_text("not JSON", encoding="utf-8")

    with pytest.raises(FixtureValidationError, match="invalid JSON"):
        load_destination_fixtures(cities_path, DEFAULT_CLIMATE_PATH)
