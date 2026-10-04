"""Contracts for the conversational trip-planning API."""

from datetime import date
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from travel_ai.schemas.recommendations import DestinationRecommendation
from travel_ai.schemas.trip import TripPreferences


class ConversationState(StrEnum):
    """Possible outcomes of a conversational planning turn."""

    COLLECTING = "collecting"
    REVIEW = "review"
    RESULTS = "results"
    NO_MATCH = "no_match"


class TravelerPreferencesDraft(BaseModel):
    """Partial constraints and preferences extracted for one traveler."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[a-z0-9_]+$",
    )
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    origin: str | None = Field(default=None, min_length=2, max_length=120)
    origin_id: str | None = None
    budget_usd: float | None = Field(default=None, gt=0, le=100_000)
    max_travel_time_hours: float | None = Field(default=None, gt=0, le=48)
    preferences: TripPreferences = Field(default_factory=TripPreferences)

    @field_validator("display_name", mode="before")
    @classmethod
    def trim_display_name(cls, value: object) -> object:
        """Trim user-facing names; reject blank names through field validation."""
        return value.strip() if isinstance(value, str) else value

    @property
    def display_label(self) -> str:
        """Use a friendly fallback without making a name mandatory."""
        return self.display_name or {
            "traveler_a": "Traveler A",
            "traveler_b": "Traveler B",
        }.get(self.traveler_id, self.traveler_id)


class TripRequestDraft(BaseModel):
    """A partial trip request collected across multiple conversation turns."""

    model_config = ConfigDict(extra="forbid")

    travelers: list[TravelerPreferencesDraft] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None


class PendingQuestion(BaseModel):
    """The question actually shown, including its canonical target."""

    field_path: str
    question: str
    source_message: str | None = None


class UnsupportedRequestNotice(BaseModel):
    """A session-owned request that must be explicitly deferred."""

    request_id: str
    user_text: str
    explanation: str
    field_path: str | None = None


class ExtractionContext(BaseModel):
    """Trusted application context for interpreting short conversational replies."""

    pending_questions: list[PendingQuestion] = Field(default_factory=list)
    unsupported_requests: list[UnsupportedRequestNotice] = Field(default_factory=list)


class CreateTripSessionRequest(BaseModel):
    """Optional first user message when starting a planning session."""

    model_config = ConfigDict(extra="forbid")

    initial_message: str | None = Field(default=None, min_length=1, max_length=10_000)


class TripSessionMessageRequest(BaseModel):
    """One user message added to an existing planning session."""

    model_config = ConfigDict(extra="forbid")

    message: str | None = Field(default=None, min_length=1, max_length=10_000)
    action: Literal["confirm", "continue_without_unsupported"] | None = None

    @model_validator(mode="after")
    def validate_action(self) -> "TripSessionMessageRequest":
        """Accept exactly one text message or structured confirmation."""
        if (self.message is None) == (self.action is None):
            raise ValueError("provide exactly one of message or action")
        return self


class ConversationTurnResponse(BaseModel):
    """The next assistant turn and structured planning state."""

    session_id: str
    state: ConversationState
    assistant_message: str
    trip_request_draft: TripRequestDraft | None = None
    missing_fields: list[str] = Field(default_factory=list)
    pending_questions: list[PendingQuestion] = Field(default_factory=list)
    unsupported_requests: list[UnsupportedRequestNotice] = Field(default_factory=list)
    deferred_requests: list[str] = Field(default_factory=list)
    recommendations: list[DestinationRecommendation] = Field(default_factory=list)
