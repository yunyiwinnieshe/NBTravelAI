"""Deterministic commercial-airport filtering and ranking."""

from math import asin, cos, radians, sin, sqrt

from travel_ai.schemas.locations import (
    AirportCandidate,
    AirportReference,
    AirportType,
    ResolvedAirport,
)

COMMERCIAL_AIRPORT_TYPES = {AirportType.LARGE, AirportType.MEDIUM}
AIRPORT_TYPE_PRIORITY = {
    AirportType.LARGE: 0,
    AirportType.MEDIUM: 1,
}


def _distance_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Calculate great-circle distance between two decimal-degree positions."""
    earth_radius_km = 6371.0088
    latitude_delta = radians(latitude_b - latitude_a)
    longitude_delta = radians(longitude_b - longitude_a)
    a = sin(latitude_delta / 2) ** 2 + (
        cos(radians(latitude_a))
        * cos(radians(latitude_b))
        * sin(longitude_delta / 2) ** 2
    )
    return earth_radius_km * 2 * asin(sqrt(a))


def select_major_commercial_airports(
    candidates: list[AirportCandidate],
    references: list[AirportReference],
    *,
    country_code: str = "US",
    exact_airport_code: str | None = None,
    reference_latitude: float | None = None,
    reference_longitude: float | None = None,
    maximum_airports: int = 3,
) -> list[ResolvedAirport]:
    """Return up to three scheduled large or medium airports deterministically."""
    if not 1 <= maximum_airports <= 3:
        raise ValueError("maximum_airports must be between 1 and 3")
    if (reference_latitude is None) != (reference_longitude is None):
        raise ValueError("reference latitude and longitude must be provided together")
    if exact_airport_code is not None and (
        len(exact_airport_code) != 3 or exact_airport_code != exact_airport_code.upper()
    ):
        raise ValueError("exact_airport_code must be an uppercase IATA code")

    references_by_code = {reference.iata_code: reference for reference in references}
    candidates_by_code: dict[str, AirportCandidate] = {}
    for candidate in candidates:
        if candidate.country_code != country_code:
            continue
        reference = references_by_code.get(candidate.iata_code)
        if (
            reference is None
            or not reference.scheduled_service
            or reference.airport_type not in COMMERCIAL_AIRPORT_TYPES
        ):
            continue
        existing = candidates_by_code.get(candidate.iata_code)
        if existing is None or (
            candidate.associated_with_selected_city
            and not existing.associated_with_selected_city
        ):
            candidates_by_code[candidate.iata_code] = candidate

    ranked: list[ResolvedAirport] = []
    for candidate in candidates_by_code.values():
        reference = references_by_code[candidate.iata_code]
        distance = None
        if (
            reference_latitude is not None
            and reference_longitude is not None
            and candidate.latitude is not None
            and candidate.longitude is not None
        ):
            distance = _distance_km(
                reference_latitude,
                reference_longitude,
                candidate.latitude,
                candidate.longitude,
            )
        ranked.append(
            ResolvedAirport(
                iata_code=candidate.iata_code,
                name=candidate.name,
                latitude=candidate.latitude,
                longitude=candidate.longitude,
                time_zone=candidate.time_zone,
                airport_type=reference.airport_type,
                distance_km=round(distance, 3) if distance is not None else None,
            )
        )

    ranked.sort(
        key=lambda airport: (
            airport.iata_code != exact_airport_code,
            AIRPORT_TYPE_PRIORITY[airport.airport_type],
            airport.distance_km is None,
            airport.distance_km if airport.distance_km is not None else float("inf"),
            not candidates_by_code[airport.iata_code].associated_with_selected_city,
            airport.iata_code,
        )
    )
    return ranked[:maximum_airports]
