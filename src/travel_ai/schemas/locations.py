"""Provider-independent contracts for resolving locations to usable airports."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AirportType(StrEnum):
    """Airport size and facility categories used by the reference dataset."""

    LARGE = "large_airport"
    MEDIUM = "medium_airport"
    SMALL = "small_airport"
    SEAPLANE_BASE = "seaplane_base"
    HELIPORT = "heliport"
    CLOSED = "closed_airport"


class AirportCandidate(BaseModel):
    """One airport returned by a place provider such as Duffel Places."""

    model_config = ConfigDict(extra="forbid")

    provider_place_id: str = Field(min_length=1, max_length=100)
    iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=200)
    city_name: str | None = Field(default=None, max_length=120)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    time_zone: str | None = Field(default=None, max_length=100)
    associated_with_selected_city: bool = False


class AirportReference(BaseModel):
    """Stable commercial-service facts loaded independently of place search."""

    model_config = ConfigDict(extra="forbid")

    iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    airport_type: AirportType
    scheduled_service: bool


class AirportReferenceDataset(BaseModel):
    """Versioned subset generated from the public OurAirports dataset."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(pattern=r"^v\d+$")
    source: str = Field(min_length=1, max_length=50)
    source_url: str = Field(min_length=1, max_length=500)
    source_date: date
    airports: list[AirportReference] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_unique_codes(self) -> "AirportReferenceDataset":
        """Require one stable record per IATA airport code."""
        codes = [airport.iata_code for airport in self.airports]
        if len(codes) != len(set(codes)):
            raise ValueError("airport reference IATA codes must be unique")
        return self


class ResolvedAirport(BaseModel):
    """A selected commercial airport safe to use in a flight search."""

    model_config = ConfigDict(extra="forbid")

    iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    name: str = Field(min_length=1, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    time_zone: str | None = Field(default=None, max_length=100)
    airport_type: AirportType
    distance_km: float | None = Field(default=None, ge=0)


class ResolvedLocation(BaseModel):
    """A confirmed place and its bounded deterministic airport group."""

    model_config = ConfigDict(extra="forbid")

    location_id: str = Field(pattern=r"^[a-z0-9_]+$")
    display_name: str = Field(min_length=1, max_length=200)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")
    iata_city_code: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    airports: list[ResolvedAirport] = Field(min_length=1, max_length=3)
    source: str = Field(min_length=1, max_length=50)
