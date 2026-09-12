"""Provider-independent contracts for resolving locations to usable airports."""

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


class LocationSearchQuery(BaseModel):
    """A city/airport text search or a coordinate-radius airport search."""

    model_config = ConfigDict(extra="forbid")

    query: str | None = Field(default=None, min_length=2, max_length=200)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_metres: int | None = Field(default=None, gt=0, le=500_000)
    country_code: str = Field(default="US", pattern=r"^[A-Z]{2}$")

    @model_validator(mode="after")
    def validate_search_mode(self) -> "LocationSearchQuery":
        """Require text or a complete coordinate-radius search."""
        coordinates = (self.latitude, self.longitude, self.radius_metres)
        if self.query is None and all(value is None for value in coordinates):
            raise ValueError("location search requires text or coordinates")
        if any(value is not None for value in coordinates) and any(
            value is None for value in coordinates
        ):
            raise ValueError(
                "latitude, longitude, and radius_metres must be provided together"
            )
        return self


class AirportReference(BaseModel):
    """Stable commercial-service facts loaded independently of place search."""

    model_config = ConfigDict(extra="forbid")

    iata_code: str = Field(pattern=r"^[A-Z]{3}$")
    airport_type: AirportType
    scheduled_service: bool


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
