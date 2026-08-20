"""Typed HTTP contracts for Travel AI."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class InterestTag(StrEnum):
    """Interests supported by the initial controlled vocabulary."""

    BEACH = "beach"
    FOOD = "food"
    MUSEUMS = "museums"
    NIGHTLIFE = "nightlife"
    NATURE = "nature"
    SHOPPING = "shopping"


class VibeTag(StrEnum):
    """Travel styles supported by the initial controlled vocabulary."""

    LIVELY = "lively"
    RELAXED = "relaxed"
    OUTDOORS = "outdoors"
    LUXURY = "luxury"


class TemperatureRange(BaseModel):
    """A preferred temperature range in Celsius."""

    model_config = ConfigDict(extra="forbid")

    minimum_celsius: float = Field(ge=-40, le=60)
    maximum_celsius: float = Field(ge=-40, le=60)

    @model_validator(mode="after")
    def validate_bounds(self) -> "TemperatureRange":
        """Require the lower temperature bound to be no greater than the upper."""
        if self.minimum_celsius > self.maximum_celsius:
            raise ValueError(
                "minimum_celsius must be less than or equal to maximum_celsius"
            )
        return self


class TravelerPreferences(BaseModel):
    """Hard constraints supplied by one traveler."""

    model_config = ConfigDict(extra="forbid")

    origin: str = Field(min_length=2, max_length=120)
    budget_usd: float = Field(gt=0, le=100_000)
    max_travel_time_hours: float = Field(gt=0, le=48)


class TripPreferences(BaseModel):
    """Shared soft preferences normalized to the initial catalog vocabulary."""

    model_config = ConfigDict(extra="forbid")

    temperature_range: TemperatureRange | None = None
    interest_tags: list[InterestTag] = Field(default_factory=list)
    vibe_tags: list[VibeTag] = Field(default_factory=list)


class TripRequest(BaseModel):
    """Canonical request used by the recommendation pipeline."""

    model_config = ConfigDict(extra="forbid")

    travelers: list[TravelerPreferences] = Field(min_length=2, max_length=2)
    start_date: date
    end_date: date
    preferences: TripPreferences = Field(default_factory=TripPreferences)

    @model_validator(mode="after")
    def validate_trip_length(self) -> "TripRequest":
        """Require the initial v1 leisure-trip range of three through seven days."""
        trip_days = (self.end_date - self.start_date).days + 1
        if not 3 <= trip_days <= 7:
            raise ValueError("Travel AI v1 supports trips lasting from 3 to 7 days")
        return self


class HealthResponse(BaseModel):
    """Response returned by the liveness endpoint."""

    status: str


class RecommendationStatus(StrEnum):
    """States supported by the recommendation endpoint during early development."""

    NOT_IMPLEMENTED = "not_implemented"


class DestinationRecommendation(BaseModel):
    """Reserved response contract for a ranked destination in the next milestone."""

    destination_id: str
    destination_name: str
    score: float = Field(ge=0, le=1)


class RecommendationResponse(BaseModel):
    """Stable outer response contract for recommendation requests."""

    status: RecommendationStatus
    recommendations: list[DestinationRecommendation]
    message: str
