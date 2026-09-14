"""Contracts for deterministic offer and city exclusions."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class OfferExclusionReason(StrEnum):
    """Stable codes explaining why a flight offer cannot continue."""

    ORIGIN_MISMATCH = "origin_mismatch"
    DESTINATION_MISMATCH = "destination_mismatch"
    DATE_MISMATCH = "date_mismatch"
    MAX_TRAVEL_TIME_EXCEEDED = "max_travel_time_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    OFFER_EXPIRED = "offer_expired"
    INVALID_PRICE = "invalid_price"
    UNSUPPORTED_CURRENCY = "unsupported_currency"


class CityExclusionReason(StrEnum):
    """Stable codes explaining why a candidate city cannot continue."""

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
    reason_codes: list[OfferExclusionReason] = Field(min_length=1)

    @field_validator("reason_codes")
    @classmethod
    def validate_unique_reasons(
        cls, reasons: list[OfferExclusionReason]
    ) -> list[OfferExclusionReason]:
        """Reject duplicate reasons while preserving the engine's check order."""
        if len(reasons) != len(set(reasons)):
            raise ValueError("reason codes must not contain duplicates")
        return reasons


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
    reason_code: CityExclusionReason = CityExclusionReason.NO_ELIGIBLE_FLIGHT
