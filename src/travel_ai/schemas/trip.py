"""Canonical trip-request contracts."""

from datetime import date
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class InterestTag(StrEnum):
    """Interests supported by the initial controlled vocabulary."""

    BEACH = "beach"
    MOUNTAIN = "mountain"
    FOOD = "food"
    MUSEUMS = "museums"
    NIGHTLIFE = "nightlife"
    NATURE = "nature"
    OUTDOOR_ACTIVITIES = "outdoor_activities"
    SHOPPING = "shopping"


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


class TripPreferences(BaseModel):
    """Soft preferences supported for one traveler in v1."""

    model_config = ConfigDict(extra="forbid")

    temperature_range: TemperatureRange | None = None
    interest_tags: list[InterestTag] = Field(default_factory=list)

    @field_validator("interest_tags")
    @classmethod
    def remove_duplicate_interests(
        cls, interest_tags: list[InterestTag]
    ) -> list[InterestTag]:
        """Preserve user order while removing duplicate controlled tags."""
        return list(dict.fromkeys(interest_tags))


class TravelerRequest(BaseModel):
    """Confirmed constraints and preferences for one traveler."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    origin_id: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9_]+$")
    budget_usd: Decimal = Field(gt=0, le=100_000)
    max_one_way_travel_minutes: int = Field(gt=0, le=2_880)
    preferences: TripPreferences = Field(default_factory=TripPreferences)


class TripRequest(BaseModel):
    """Canonical request used by the deterministic recommendation pipeline."""

    model_config = ConfigDict(extra="forbid")

    travelers: list[TravelerRequest] = Field(min_length=2, max_length=2)
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def validate_request(self) -> "TripRequest":
        """Enforce confirmed V1 date, traveler, and origin invariants."""
        if self.start_date < date.today():
            raise ValueError("start_date must not be in the past")

        trip_days = (self.end_date - self.start_date).days + 1
        if not 3 <= trip_days <= 7:
            raise ValueError("Travel AI v1 supports trips lasting from 3 to 7 days")

        traveler_ids = [traveler.traveler_id for traveler in self.travelers]
        if len(set(traveler_ids)) != len(traveler_ids):
            raise ValueError("traveler_id values must be unique")

        origin_ids = [traveler.origin_id for traveler in self.travelers]
        if len(set(origin_ids)) != len(origin_ids):
            raise ValueError("Travel AI v1 requires two distinct resolved origins")

        return self
