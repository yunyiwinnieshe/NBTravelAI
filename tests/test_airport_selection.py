"""Tests for deterministic commercial-airport filtering and ranking."""

from datetime import date
from pathlib import Path

from travel_ai.providers.fixtures import load_airport_reference_dataset
from travel_ai.schemas.locations import AirportCandidate, AirportReference
from travel_ai.scripts.build_airport_reference import build_reference
from travel_ai.services.airport_selection import select_major_commercial_airports


def boston_candidates() -> list[AirportCandidate]:
    """Represent the airport records observed in Duffel's Boston suggestions."""
    return [
        AirportCandidate(
            provider_place_id="arp_bnh_us",
            iata_code="BNH",
            name="Boston Harbor Seaplane Base",
            city_name="Boston",
            country_code="US",
            latitude=42.352509,
            longitude=-71.025732,
            time_zone="America/New_York",
            associated_with_selected_city=True,
        ),
        AirportCandidate(
            provider_place_id="arp_bos_us",
            iata_code="BOS",
            name="General Edward Lawrence Logan International Airport",
            city_name="Boston",
            country_code="US",
            latitude=42.364956,
            longitude=-71.007381,
            time_zone="America/New_York",
            associated_with_selected_city=True,
        ),
        AirportCandidate(
            provider_place_id="arp_psm_us",
            iata_code="PSM",
            name="Portsmouth International Airport",
            city_name="Portsmouth",
            country_code="US",
            latitude=43.079053,
            longitude=-70.822681,
            time_zone="America/New_York",
            associated_with_selected_city=True,
        ),
        AirportCandidate(
            provider_place_id="arp_mht_us",
            iata_code="MHT",
            name="Manchester-Boston Regional Airport",
            city_name="Manchester",
            country_code="US",
            latitude=42.930885,
            longitude=-71.436649,
            time_zone="America/New_York",
        ),
    ]


def airport_references() -> list[AirportReference]:
    """Provide the commercial facts that Duffel Places does not expose."""
    return [
        AirportReference(
            iata_code="BNH",
            airport_type="seaplane_base",
            scheduled_service=False,
        ),
        AirportReference(
            iata_code="BOS",
            airport_type="large_airport",
            scheduled_service=True,
        ),
        AirportReference(
            iata_code="PSM",
            airport_type="medium_airport",
            scheduled_service=True,
        ),
        AirportReference(
            iata_code="MHT",
            airport_type="medium_airport",
            scheduled_service=True,
        ),
    ]


def test_bundled_reference_is_a_versioned_ourairports_subset() -> None:
    """The generated fixture contains known U.S. commercial airports."""
    dataset = load_airport_reference_dataset()
    references = {airport.iata_code: airport for airport in dataset.airports}

    assert dataset.source == "OurAirports"
    assert dataset.schema_version == "v2"
    assert len(references) == 502
    assert references["BOS"].iso_region == "US-MA"
    assert references["PDX"].iso_region == "US-OR"
    assert references["PWM"].iso_region == "US-ME"
    assert references["PDX"].municipality == "Portland"
    assert references["BOS"].airport_type == "large_airport"
    assert all(airport.scheduled_service for airport in dataset.airports)
    assert all(
        airport.iso_region and airport.municipality for airport in dataset.airports
    )


def test_reference_builder_keeps_only_eligible_us_airports(tmp_path: Path) -> None:
    csv_file = tmp_path / "airports.csv"
    csv_file.write_text(
        "iata_code,type,scheduled_service,iso_country,iso_region,municipality\n"
        "PDX,large_airport,yes,US,US-OR,Portland\n"
        "PWM,medium_airport,yes,US,US-ME,Portland\n"
        "YYZ,large_airport,yes,CA,CA-ON,Toronto\n"
        "BNH,seaplane_base,yes,US,US-MA,Boston\n"
        "AAA,medium_airport,no,US,US-CA,Somewhere\n",
        encoding="utf-8",
    )

    result = build_reference(csv_file, date(2026, 10, 18))
    assert result["schema_version"] == "v2"
    assert result["source_date"] == "2026-10-18"
    assert result["airports"] == [
        {
            "iata_code": "PDX",
            "airport_type": "large_airport",
            "scheduled_service": True,
            "iso_region": "US-OR",
            "municipality": "Portland",
        },
        {
            "iata_code": "PWM",
            "airport_type": "medium_airport",
            "scheduled_service": True,
            "iso_region": "US-ME",
            "municipality": "Portland",
        },
    ]


def test_filters_noncommercial_airports_and_ranks_by_size_then_distance() -> None:
    """A nearby seaplane base is removed before the three-airport cap is applied."""
    selected = select_major_commercial_airports(
        boston_candidates(),
        airport_references(),
        reference_latitude=42.3601,
        reference_longitude=-71.0589,
    )

    assert [airport.iata_code for airport in selected] == ["BOS", "MHT", "PSM"]
    assert all(airport.distance_km is not None for airport in selected)


def test_exact_commercial_airport_choice_has_highest_priority() -> None:
    """An explicit traveler airport remains first even when another is larger."""
    selected = select_major_commercial_airports(
        boston_candidates(),
        airport_references(),
        exact_airport_code="MHT",
        reference_latitude=42.3601,
        reference_longitude=-71.0589,
    )

    assert selected[0].iata_code == "MHT"


def test_requires_complete_reference_coordinates() -> None:
    """Distance ranking cannot accept only half of a geographic position."""
    try:
        select_major_commercial_airports(
            boston_candidates(),
            airport_references(),
            reference_latitude=42.3601,
        )
    except ValueError as error:
        assert str(error) == (
            "reference latitude and longitude must be provided together"
        )
    else:
        raise AssertionError("incomplete reference coordinates should fail")
