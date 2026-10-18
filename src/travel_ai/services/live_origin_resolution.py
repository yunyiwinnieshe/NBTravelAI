"""Resolve US origins through Duffel Places and a durable location registry."""

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from travel_ai.providers.duffel import DuffelAirportPlaceProvider
from travel_ai.providers.fixtures import load_airport_reference_dataset
from travel_ai.schemas.locations import (
    AirportReference,
    LocationSearchQuery,
    PlaceSuggestion,
    ResolvedLocation,
)
from travel_ai.services.airport_selection import select_major_commercial_airports

_CITY_STATE = re.compile(r"^\s*(?P<city>[^,]+),\s*(?P<state>[A-Za-z ]+)\s*$")
_AIRPORT_CODE = re.compile(r"^\s*(?:airport\s+)?(?P<code>[A-Za-z]{3})\s*$", re.I)
_US_REGIONS = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
}
_STATE_NAMES = dict(
    zip(
        (
            "Alabama",
            "Alaska",
            "Arizona",
            "Arkansas",
            "California",
            "Colorado",
            "Connecticut",
            "Delaware",
            "Florida",
            "Georgia",
            "Hawaii",
            "Idaho",
            "Illinois",
            "Indiana",
            "Iowa",
            "Kansas",
            "Kentucky",
            "Louisiana",
            "Maine",
            "Maryland",
            "Massachusetts",
            "Michigan",
            "Minnesota",
            "Mississippi",
            "Missouri",
            "Montana",
            "Nebraska",
            "Nevada",
            "New Hampshire",
            "New Jersey",
            "New Mexico",
            "New York",
            "North Carolina",
            "North Dakota",
            "Ohio",
            "Oklahoma",
            "Oregon",
            "Pennsylvania",
            "Rhode Island",
            "South Carolina",
            "South Dakota",
            "Tennessee",
            "Texas",
            "Utah",
            "Vermont",
            "Virginia",
            "Washington",
            "West Virginia",
            "Wisconsin",
            "Wyoming",
            "District of Columbia",
        ),
        (
            "AL",
            "AK",
            "AZ",
            "AR",
            "CA",
            "CO",
            "CT",
            "DE",
            "FL",
            "GA",
            "HI",
            "ID",
            "IL",
            "IN",
            "IA",
            "KS",
            "KY",
            "LA",
            "ME",
            "MD",
            "MA",
            "MI",
            "MN",
            "MS",
            "MO",
            "MT",
            "NE",
            "NV",
            "NH",
            "NJ",
            "NM",
            "NY",
            "NC",
            "ND",
            "OH",
            "OK",
            "OR",
            "PA",
            "RI",
            "SC",
            "SD",
            "TN",
            "TX",
            "UT",
            "VT",
            "VA",
            "WA",
            "WV",
            "WI",
            "WY",
            "DC",
        ),
        strict=True,
    )
)
_STATE_NAMES = {name.casefold(): code for name, code in _STATE_NAMES.items()}


class OriginResolutionError(ValueError):
    """A place is unsupported, ambiguous, or not yet precise enough."""


class SQLiteLocationStore:
    """Reuse opaque location IDs across processes without storing credentials."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with closing(self._connect()) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS locations (
                    location_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    provider_place_id TEXT NOT NULL,
                    country_code TEXT NOT NULL,
                    airport_choice TEXT NOT NULL,
                    display_name TEXT NOT NULL,
                    iata_city_code TEXT,
                    airport_codes TEXT NOT NULL,
                    UNIQUE(provider, provider_place_id, country_code, airport_choice)
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.execute("PRAGMA busy_timeout = 10000")
        return db

    def save(
        self,
        *,
        provider_place_id: str,
        display_name: str,
        iata_city_code: str | None,
        airport_choice: str,
        airport_codes: list[str],
    ) -> str:
        """Insert once under a cross-process unique key and return its saved ID."""
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """INSERT OR IGNORE INTO locations
                   VALUES (?, 'duffel', ?, 'US', ?, ?, ?, ?)""",
                (
                    f"loc_{uuid4().hex}",
                    provider_place_id,
                    airport_choice,
                    display_name,
                    iata_city_code,
                    json.dumps(airport_codes),
                ),
            )
            row = db.execute(
                """SELECT location_id FROM locations WHERE provider = 'duffel'
                   AND provider_place_id = ? AND country_code = 'US'
                   AND airport_choice = ?""",
                (provider_place_id, airport_choice),
            ).fetchone()
            assert row is not None
            return str(row[0])

    def get_airports(self, location_id: str) -> list[str] | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT airport_codes FROM locations WHERE location_id = ?",
                (location_id,),
            ).fetchone()
        return json.loads(row[0]) if row else None


class DuffelOriginResolver:
    """Keep model-extracted text separate from verified location selection."""

    def __init__(
        self,
        place_provider: DuffelAirportPlaceProvider,
        location_store: SQLiteLocationStore,
        references: list[AirportReference] | None = None,
    ) -> None:
        self.place_provider = place_provider
        self.location_store = location_store
        self.references = references or load_airport_reference_dataset().airports
        self.references_by_code = {item.iata_code: item for item in self.references}

    def close(self) -> None:
        self.place_provider.close()

    def resolve(self, origin: str) -> str:
        """Return a stored ID only after an exact US airport or city/state match."""
        airport_match = _AIRPORT_CODE.fullmatch(origin)
        city_match = _CITY_STATE.fullmatch(origin)
        if airport_match:
            code = airport_match.group("code").upper()
            places = self.place_provider.search_places(LocationSearchQuery(query=code))
            choices = [
                place
                for place in places
                if place.place_type == "airport" and place.iata_code == code
            ]
            if not choices:
                choices = [
                    PlaceSuggestion(
                        provider_place_id=airport.provider_place_id,
                        place_type="airport",
                        name=airport.name,
                        iata_code=airport.iata_code,
                        country_code=airport.country_code,
                        latitude=airport.latitude,
                        longitude=airport.longitude,
                        airports=[airport],
                    )
                    for place in places
                    if place.place_type == "city"
                    for airport in place.airports
                    if airport.iata_code == code
                ]
            if not choices:
                raise OriginResolutionError(
                    f"I couldn't verify {code} as an eligible US commercial airport."
                )
            return self._save_choice(choices, airport_choice=code)

        if not city_match:
            places = self.place_provider.search_places(
                LocationSearchQuery(query=origin)
            )
            choices = [
                place
                for place in places
                if place.place_type == "airport"
                and place.name.casefold() == origin.strip().casefold()
            ]
            if choices:
                return self._save_choice(
                    choices,
                    airport_choice=choices[0].iata_code if len(choices) == 1 else "",
                )
            raise OriginResolutionError(
                "Which US city and state, or exact airport name or IATA code, "
                "do you mean?"
            )
        city = city_match.group("city").strip()
        state_text = city_match.group("state").strip()
        state = _STATE_NAMES.get(state_text.casefold(), state_text.upper())
        if state not in _US_REGIONS:
            raise OriginResolutionError("Which US state do you mean?")
        places = self.place_provider.search_places(LocationSearchQuery(query=city))
        choices = [
            place
            for place in places
            if place.place_type == "city"
            and place.name.casefold() == city.casefold()
            and any(
                self.references_by_code.get(airport.iata_code) is not None
                and self.references_by_code[airport.iata_code].iso_region
                == f"US-{state}"
                and (
                    self.references_by_code[airport.iata_code].municipality or ""
                ).casefold()
                == city.casefold()
                for airport in place.airports
            )
        ]
        if not choices:
            matching_airports = [
                place
                for place in places
                if place.place_type == "airport"
                and (place.city_name or "").casefold() == city.casefold()
                and (reference := self.references_by_code.get(place.iata_code))
                is not None
                and reference.iso_region == f"US-{state}"
            ]
            if matching_airports:
                first = matching_airports[0]
                choices = [
                    PlaceSuggestion(
                        provider_place_id=f"city-group:US-{state}:{city.casefold()}",
                        place_type="city",
                        name=city,
                        iata_code=first.iata_code,
                        country_code="US",
                        latitude=first.latitude,
                        longitude=first.longitude,
                        airports=[
                            airport
                            for place in matching_airports
                            for airport in place.airports
                        ],
                    )
                ]
        if not choices:
            raise OriginResolutionError(
                f"I couldn't verify {city}, {state} with an eligible US "
                "commercial airport."
            )
        return self._save_choice(
            choices,
            airport_choice="",
            location_key=f"city-group:US-{state}:{city.casefold()}",
        )

    def _save_choice(
        self,
        choices: list[PlaceSuggestion],
        *,
        airport_choice: str,
        location_key: str | None = None,
    ) -> str:
        eligible = []
        for place in choices:
            airports = select_major_commercial_airports(
                place.airports,
                self.references,
                exact_airport_code=airport_choice or None,
                reference_latitude=place.latitude
                if place.longitude is not None
                else None,
                reference_longitude=place.longitude
                if place.latitude is not None
                else None,
            )
            if airport_choice:
                airports = [
                    airport
                    for airport in airports
                    if airport.iata_code == airport_choice
                ]
            if airports:
                eligible.append((place, airports))
        if len(eligible) != 1:
            if eligible:
                options = ", ".join(
                    f"{place.name} ({place.iata_code})" for place, _ in eligible[:5]
                )
                raise OriginResolutionError(f"Which location do you mean: {options}?")
            raise OriginResolutionError(
                "That place has no eligible scheduled commercial airport."
            )
        place, airports = eligible[0]
        iata_city_code = (
            place.iata_code
            if place.place_type == "city"
            and not place.provider_place_id.startswith("city-group:")
            else None
        )
        location_id = self.location_store.save(
            provider_place_id=location_key or place.provider_place_id,
            display_name=place.name,
            iata_city_code=iata_city_code,
            airport_choice=airport_choice,
            airport_codes=[airport.iata_code for airport in airports],
        )
        ResolvedLocation(
            location_id=location_id,
            display_name=place.name,
            country_code="US",
            iata_city_code=iata_city_code,
            airports=airports,
            source="Duffel Places + OurAirports",
        )
        return location_id
