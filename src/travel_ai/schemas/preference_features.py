"""Typed results produced by deterministic preference calculations."""

from pydantic import BaseModel, ConfigDict, Field


class TravelerPreferenceFeatures(BaseModel):
    """Preference feature values calculated for one traveler and city."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    interest_match: float | None = Field(default=None, ge=0, le=1)
    temperature_match: float | None = Field(default=None, ge=0, le=1)
    preference_score: float | None = Field(default=None, ge=0, le=1)


class CityPreferenceFeatures(BaseModel):
    """Preference and preference-fairness features for one candidate city."""

    model_config = ConfigDict(extra="forbid")

    city_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    trip_temperature_celsius: float
    travelers: tuple[TravelerPreferenceFeatures, TravelerPreferenceFeatures]
    combined_preference_score: float | None = Field(default=None, ge=0, le=1)
    preference_gap: float | None = Field(default=None, ge=0, le=1)
    preference_fairness: float | None = Field(default=None, ge=0, le=1)
