"""Contracts for extracting a partial trip request from natural language."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from travel_ai.schemas.sessions import TripRequestDraft


class PreferenceExtractionStatus(StrEnum):
    """Whether a draft needs more information before human review."""

    NEEDS_CLARIFICATION = "needs_clarification"
    READY_FOR_REVIEW = "ready_for_review"


class MissingFieldReason(StrEnum):
    """Why the system cannot safely complete one canonical field."""

    MISSING = "missing"
    AMBIGUOUS = "ambiguous"


class MissingField(BaseModel):
    """One unresolved canonical field and the question needed to resolve it."""

    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1, max_length=200)
    reason: MissingFieldReason
    clarification_question: str = Field(min_length=1, max_length=500)


class PreferenceExtractionResult(BaseModel):
    """Structured result from one extraction attempt; not a confirmed request."""

    model_config = ConfigDict(extra="forbid")

    draft: TripRequestDraft
    status: PreferenceExtractionStatus
    missing_fields: list[MissingField] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_status_and_missing_fields(self) -> "PreferenceExtractionResult":
        """Keep clarification state consistent with the unresolved field list."""
        if (
            self.status == PreferenceExtractionStatus.NEEDS_CLARIFICATION
            and not self.missing_fields
        ):
            raise ValueError(
                "needs_clarification results must identify at least one missing field"
            )
        if (
            self.status == PreferenceExtractionStatus.READY_FOR_REVIEW
            and self.missing_fields
        ):
            raise ValueError("ready_for_review results must not contain missing fields")
        return self
