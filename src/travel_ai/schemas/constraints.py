"""Contracts for deterministic offer and city exclusions."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from travel_ai.schemas.flights import FlightOffer


class OfferExclusionReason(StrEnum):
    """Stable codes explaining why a flight offer cannot continue."""

    TRAVELER_MISMATCH = "traveler_mismatch"
    ORIGIN_MISMATCH = "origin_mismatch"
    DESTINATION_MISMATCH = "destination_mismatch"
    DATE_MISMATCH = "date_mismatch"
    MAX_TRAVEL_TIME_EXCEEDED = "max_travel_time_exceeded"
    BUDGET_EXCEEDED = "budget_exceeded"
    OFFER_UNAVAILABLE = "offer_unavailable"
    OFFER_EXPIRED = "offer_expired"
    INVALID_PRICE = "invalid_price"
    UNSUPPORTED_CURRENCY = "unsupported_currency"


class CityExclusionReason(StrEnum):
    """Stable codes explaining why a candidate city cannot continue."""

    NO_ELIGIBLE_FLIGHT = "no_eligible_flight"
    NO_COMPATIBLE_FLIGHT_PAIR = "no_compatible_flight_pair"


class OfferRejection(BaseModel):
    """Attach one or more deterministic exclusion reasons to a flight offer."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
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
    """Record why a candidate city cannot produce a recommended flight pair."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str | None = Field(
        default=None, min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$"
    )
    city_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
    )
    reason_code: CityExclusionReason = CityExclusionReason.NO_ELIGIBLE_FLIGHT

    @model_validator(mode="after")
    def validate_reason_context(self) -> "CityExclusion":
        """Attach traveler context only when a traveler lacks an eligible offer."""
        if (
            self.reason_code == CityExclusionReason.NO_ELIGIBLE_FLIGHT
            and self.traveler_id is None
        ):
            raise ValueError("no_eligible_flight requires a traveler_id")
        if (
            self.reason_code == CityExclusionReason.NO_COMPATIBLE_FLIGHT_PAIR
            and self.traveler_id is not None
        ):
            raise ValueError("no_compatible_flight_pair must not include a traveler_id")
        return self


class ConstraintEvaluationResult(BaseModel):
    """Eligible and rejected offers for one traveler and candidate city."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    city_id: str = Field(
        min_length=1,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$",
    )
    eligible_offers: list[FlightOffer] = Field(default_factory=list)
    rejected_offers: list[OfferRejection] = Field(default_factory=list)
    city_exclusion: CityExclusion | None = None
