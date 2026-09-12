"""Tests for deterministic commercial-airport filtering and ranking."""

from travel_ai.schemas.locations import AirportCandidate, AirportReference
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
