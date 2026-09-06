"""Contracts for deterministic offer and city exclusions."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExclusionReason(StrEnum):
    """Stable codes explaining why an offer or city cannot continue."""

    ORIGIN_MISMATCH = "origin_mismatch"
    DESTINATION_MISMATCH = "destination_mismatch"
    DATE_MISMATCH = "date_mismatch"
    MAX_TRAVEL_TIME_EXCEEDED = "max_travel_time_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    OFFER_EXPIRED = "offer_expired"
    INVALID_PRICE = "invalid_price"
    UNSUPPORTED_CURRENCY = "unsupported_currency"
    NO_ELIGIBLE_FLIGHT = "no_eligible_flight"


class OfferRejection(BaseModel):
    """Attach one or more deterministic exclusion reasons to a flight offer."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
    )
    city_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
    )
    offer_id: str = Field(min_length=1, max_length=200, pattern=r".*\S.*")
    reason_codes: list[ExclusionReason] = Field(min_length=1)

    @field_validator("reason_codes")
    @classmethod
    def validate_unique_reasons(
        cls, reasons: list[ExclusionReason]
    ) -> list[ExclusionReason]:
        """Reject duplicate reasons while preserving the engine's check order."""
        if len(reasons) != len(set(reasons)):
            raise ValueError("reason codes must not contain duplicates")
        return reasons

    @model_validator(mode="after")
    def validate_offer_reason_scope(self) -> "OfferRejection":
        """Reserve the aggregate no-flight reason for city-level exclusions."""
        if ExclusionReason.NO_ELIGIBLE_FLIGHT in self.reason_codes:
            raise ValueError(
                "no_eligible_flight is a city-level reason, not an offer reason"
            )
        return self


class CityExclusion(BaseModel):
    """Record that one traveler has no eligible flight to a candidate city."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
    )
    city_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
    )
    reason_code: ExclusionReason = ExclusionReason.NO_ELIGIBLE_FLIGHT

    @field_validator("reason_code")
    @classmethod
    def validate_city_reason(cls, reason: ExclusionReason) -> ExclusionReason:
        """Allow only aggregate city-level reasons in this initial contract."""
        if reason is not ExclusionReason.NO_ELIGIBLE_FLIGHT:
            raise ValueError("city exclusions must use no_eligible_flight")
        return reason
