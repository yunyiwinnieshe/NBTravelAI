"""Contracts for grounded recommendation explanations and their evidence."""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from travel_ai.schemas.recommendations import (
    DestinationExclusionReason,
    RecommendationDataMode,
    RecommendationStatus,
    ScoreBreakdown,
)
from travel_ai.schemas.trip import InterestTag, TemperatureRange


class DestinationExplanation(BaseModel):
    """Planned user-facing explanation for one ranked destination."""

    model_config = ConfigDict(extra="forbid")

    destination_id: str = Field(pattern=r"^[a-z0-9_]+$")
    summary: str = Field(min_length=1, max_length=600)
    tradeoffs: list[str] = Field(default_factory=list, max_length=4)
    fairness_note: str | None = Field(default=None, min_length=1, max_length=400)
    freshness_note: str = Field(min_length=1, max_length=400)

    @field_validator("tradeoffs")
    @classmethod
    def validate_tradeoffs(cls, tradeoffs: list[str]) -> list[str]:
        """Require concise, non-empty, unique tradeoff statements."""
        if any(not tradeoff.strip() for tradeoff in tradeoffs):
            raise ValueError("tradeoffs must not contain blank statements")
        if len(tradeoffs) != len(set(tradeoffs)):
            raise ValueError("tradeoffs must not contain duplicates")
        return tradeoffs


class NoMatchExplanation(BaseModel):
    """Planned user-facing guidance when no destination qualifies."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=600)
    guidance: list[str] = Field(min_length=1, max_length=4)
    freshness_note: str = Field(min_length=1, max_length=400)

    @field_validator("guidance")
    @classmethod
    def validate_guidance(cls, guidance: list[str]) -> list[str]:
        """Require useful, unique, non-empty next steps."""
        if any(not item.strip() for item in guidance):
            raise ValueError("guidance must not contain blank statements")
        if len(guidance) != len(set(guidance)):
            raise ValueError("guidance must not contain duplicates")
        return guidance


class RequestedPreferenceEvidence(BaseModel):
    """User-provided preferences, without claiming that a city satisfies them."""

    model_config = ConfigDict(extra="forbid")

    interest_tags: list[InterestTag] = Field(default_factory=list)
    temperature_range: TemperatureRange | None = None


class TravelerConstraintEvidence(BaseModel):
    """Verified request constraints available to the explanation step."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(pattern=r"^[a-z0-9_]+$")
    origin_id: str = Field(pattern=r"^[a-z0-9_]+$")
    budget_usd: Decimal = Field(gt=0)
    max_one_way_travel_minutes: int = Field(gt=0)
    requested_preferences: RequestedPreferenceEvidence


class SelectedFlightEvidence(BaseModel):
    """Verified facts for one traveler's flight in the recommended pair."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(pattern=r"^[a-z0-9_]+$")
    offer_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    round_trip_price_usd: Decimal = Field(gt=0)
    budget_usd: Decimal = Field(gt=0)
    budget_utilization: float = Field(gt=0, le=1)
    outbound_duration_minutes: int = Field(gt=0)
    return_duration_minutes: int = Field(gt=0)
    outbound_connections: int = Field(ge=0)
    return_connections: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_budget_utilization(self) -> "SelectedFlightEvidence":
        """Keep the derived budget burden tied to the published price and budget."""
        calculated = float(self.round_trip_price_usd / self.budget_usd)
        if abs(self.budget_utilization - calculated) > 0.000001:
            raise ValueError("budget_utilization must equal price divided by budget")
        return self


class RecommendedPairEvidence(BaseModel):
    """Verified cost, timing, and compatibility facts for the selected pair."""

    model_config = ConfigDict(extra="forbid")

    combined_price_usd: Decimal = Field(gt=0)
    lowest_valid_combined_price_usd: Decimal = Field(gt=0)
    premium_usd: Decimal = Field(ge=0)
    premium_percentage: float = Field(ge=0)
    combined_travel_minutes: int = Field(gt=0)
    total_connections: int = Field(ge=0)
    arrival_gap_minutes: int = Field(ge=0)
    return_departure_gap_minutes: int = Field(ge=0)
    time_together_minutes: int = Field(gt=0)
    travelers: list[SelectedFlightEvidence] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_travelers(self) -> "RecommendedPairEvidence":
        """Require one selected flight per distinct traveler."""
        traveler_ids = [traveler.traveler_id for traveler in self.travelers]
        if len(set(traveler_ids)) != 2:
            raise ValueError("pair evidence requires two distinct travelers")
        if (
            sum(traveler.round_trip_price_usd for traveler in self.travelers)
            != self.combined_price_usd
        ):
            raise ValueError("pair evidence price must equal both traveler prices")
        return self


class DestinationComparisonEvidence(BaseModel):
    """Signed facts comparing one ranked destination with another."""

    model_config = ConfigDict(extra="forbid")

    other_destination_id: str = Field(pattern=r"^[a-z0-9_]+$")
    score_difference: float
    combined_price_difference_usd: Decimal
    combined_travel_difference_minutes: int
    preference_match_difference: float
    travel_fairness_difference: float


class RankedDestinationEvidence(BaseModel):
    """Restricted verified evidence for explaining one ranked destination."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1, le=3)
    destination_id: str = Field(pattern=r"^[a-z0-9_]+$")
    destination_name: str = Field(min_length=1, max_length=120)
    score: float = Field(ge=0, le=1)
    score_breakdown: ScoreBreakdown
    recommended_pair: RecommendedPairEvidence
    comparisons: list[DestinationComparisonEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_comparisons(self) -> "RankedDestinationEvidence":
        """Prevent self-comparisons and duplicate comparison targets."""
        targets = [comparison.other_destination_id for comparison in self.comparisons]
        if self.destination_id in targets:
            raise ValueError("destination evidence cannot compare itself")
        if len(targets) != len(set(targets)):
            raise ValueError("comparison targets must be unique")
        return self


class ExclusionEvidence(BaseModel):
    """Verified reason a candidate destination could not qualify."""

    model_config = ConfigDict(extra="forbid")

    destination_id: str = Field(pattern=r"^[a-z0-9_]+$")
    traveler_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    reason_code: DestinationExclusionReason


class ExplanationFreshnessEvidence(BaseModel):
    """Source and timestamp metadata that bounds freshness claims."""

    model_config = ConfigDict(extra="forbid")

    evaluated_at: datetime
    candidate_pool_version: str = Field(pattern=r"^v[0-9]+(?:\.[0-9]+)*$")
    data_mode: RecommendationDataMode

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, evaluated_at: datetime) -> datetime:
        """Require an unambiguous evidence timestamp."""
        if evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must include a timezone")
        return evaluated_at


class RecommendationExplanationEvidence(BaseModel):
    """Complete allowlisted input for a future explanation generator."""

    model_config = ConfigDict(extra="forbid")

    status: RecommendationStatus
    trip_start_date: date
    trip_end_date: date
    travelers: list[TravelerConstraintEvidence] = Field(min_length=2, max_length=2)
    destinations: list[RankedDestinationEvidence] = Field(
        default_factory=list,
        max_length=3,
    )
    exclusions: list[ExclusionEvidence] = Field(default_factory=list)
    freshness: ExplanationFreshnessEvidence

    @model_validator(mode="after")
    def validate_result_shape(self) -> "RecommendationExplanationEvidence":
        """Keep the evidence shape consistent with the terminal result."""
        if self.trip_end_date < self.trip_start_date:
            raise ValueError("trip_end_date must not precede trip_start_date")
        traveler_ids = [traveler.traveler_id for traveler in self.travelers]
        if len(set(traveler_ids)) != 2:
            raise ValueError("explanation evidence requires two distinct travelers")
        if self.status == RecommendationStatus.SUCCESS and not self.destinations:
            raise ValueError("success evidence requires a ranked destination")
        if self.status == RecommendationStatus.NO_MATCH and self.destinations:
            raise ValueError("no_match evidence cannot contain destinations")
        ranks = [destination.rank for destination in self.destinations]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("evidence ranks must be consecutive starting at 1")
        return self
