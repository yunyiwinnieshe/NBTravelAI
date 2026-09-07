"""Contracts for the controlled destination catalog and climate fixtures."""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from travel_ai.schemas.trip import InterestTag


class City(BaseModel):
    """Stable metadata for one supported U.S. metro-area destination."""

    model_config = ConfigDict(extra="forbid")

    city_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    name: str = Field(min_length=1, max_length=120)
    state_code: str = Field(pattern=r"^[A-Z]{2}$")
    country_code: str = Field(default="US", pattern=r"^US$")
    metro_airport_codes: list[str] = Field(min_length=1, max_length=3)
    interest_tags: list[InterestTag] = Field(default_factory=list)
    data_version: str = Field(pattern=r"^v[1-9][0-9]*$")

    @field_validator("metro_airport_codes")
    @classmethod
    def validate_airport_codes(cls, codes: list[str]) -> list[str]:
        """Require unique three-letter uppercase IATA airport codes."""
        invalid = any(
            len(code) != 3 or not code.isascii() or not code.isalpha() for code in codes
        )
        if invalid:
            raise ValueError("airport codes must contain exactly three ASCII letters")
        if any(code != code.upper() for code in codes):
            raise ValueError("airport codes must be uppercase")
        if len(codes) != len(set(codes)):
            raise ValueError("airport codes must not contain duplicates")
        return codes

    @field_validator("interest_tags")
    @classmethod
    def validate_unique_interests(cls, tags: list[InterestTag]) -> list[InterestTag]:
        """Reject duplicate catalog tags as a fixture-data error."""
        if len(tags) != len(set(tags)):
            raise ValueError("interest tags must not contain duplicates")
        return tags


class MonthlyClimate(BaseModel):
    """Historical monthly daytime temperature for one destination."""

    model_config = ConfigDict(extra="forbid")

    city_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    month: int = Field(ge=1, le=12)
    average_daytime_temperature_celsius: float = Field(ge=-40, le=60)
    source: str = Field(min_length=1, max_length=200)
    source_url: HttpUrl
    reference_period: str = Field(min_length=1, max_length=50)
    retrieved_at: date
    data_version: str = Field(pattern=r"^v[1-9][0-9]*$")

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieval_date(cls, retrieved_at: date) -> date:
        """Reject provenance dates that are in the future."""
        if retrieved_at > date.today():
            raise ValueError("retrieved_at cannot be in the future")
        return retrieved_at
