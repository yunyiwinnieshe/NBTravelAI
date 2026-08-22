"""Contracts for the conversational trip-planning API."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from travel_ai.schemas.recommendations import DestinationRecommendation
from travel_ai.schemas.trip import TripPreferences


class ConversationState(StrEnum):
    """Possible outcomes of a conversational planning turn."""

    COLLECTING = "collecting"
    REVIEW = "review"
    RESULTS = "results"
    NO_MATCH = "no_match"


class TravelerPreferencesDraft(BaseModel):
    """A partial set of constraints extracted for one traveler."""

    model_config = ConfigDict(extra="forbid")

    origin: str | None = Field(default=None, min_length=2, max_length=120)
    budget_usd: float | None = Field(default=None, gt=0, le=100_000)
    max_travel_time_hours: float | None = Field(default=None, gt=0, le=48)


class TripRequestDraft(BaseModel):
    """A partial trip request collected across multiple conversation turns."""

    model_config = ConfigDict(extra="forbid")

    travelers: list[TravelerPreferencesDraft] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    preferences: TripPreferences = Field(default_factory=TripPreferences)


class CreateTripSessionRequest(BaseModel):
    """Optional first user message when starting a planning session."""

    model_config = ConfigDict(extra="forbid")

    initial_message: str | None = Field(default=None, min_length=1, max_length=10_000)


class TripSessionMessageRequest(BaseModel):
    """One user message added to an existing planning session."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=10_000)


class ConversationTurnResponse(BaseModel):
    """The next assistant turn and structured planning state."""

    session_id: str
    state: ConversationState
    assistant_message: str
    trip_request_draft: TripRequestDraft | None = None
    missing_fields: list[str] = Field(default_factory=list)
    recommendations: list[DestinationRecommendation] = Field(default_factory=list)
