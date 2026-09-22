"""Tests for deterministic fixture-mode origin airport resolution."""

import json
from pathlib import Path

import pytest

from travel_ai.providers.fixtures import (
    FixtureDataError,
    FixtureOriginAirportProvider,
    load_origin_airport_mappings,
)


def test_fixture_origin_provider_resolves_the_supported_test_origins() -> None:
    """Fixture searches use a stable local mapping instead of a live place API."""
    provider = FixtureOriginAirportProvider()

    assert provider.resolve("boston_ma").airport_codes == ["BOS"]
    assert provider.resolve("new_york_ny").airport_codes == ["JFK"]


def test_fixture_origin_provider_rejects_an_unknown_origin() -> None:
    provider = FixtureOriginAirportProvider()

    with pytest.raises(FixtureDataError, match="origin ID is not configured"):
        provider.resolve("unknown_city")


def test_origin_airport_loader_rejects_duplicate_origin_ids(tmp_path: Path) -> None:
    fixture_path = tmp_path / "origin_airports.json"
    fixture_path.write_text(
        json.dumps(
            [
                {"origin_id": "boston_ma", "airport_codes": ["BOS"]},
                {"origin_id": "boston_ma", "airport_codes": ["PVD"]},
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(FixtureDataError, match="duplicate origin IDs"):
        load_origin_airport_mappings(fixture_path)


def test_origin_airport_loader_rejects_unusable_airport_codes(tmp_path: Path) -> None:
    fixture_path = tmp_path / "origin_airports.json"
    fixture_path.write_text(
        json.dumps([{"origin_id": "boston_ma", "airport_codes": ["bos"]}]),
        encoding="utf-8",
    )

    with pytest.raises(FixtureDataError, match="Invalid origin airport fixture"):
        load_origin_airport_mappings(fixture_path)
