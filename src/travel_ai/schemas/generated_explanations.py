"""Validated claims and response contracts for grounded explanations."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from travel_ai.schemas.explanations import DestinationExplanation, NoMatchExplanation
from travel_ai.schemas.recommendations import (
    DestinationExclusionReason,
    RecommendationResponse,
    RecommendationStatus,
)


class RecommendationExplanationSet(BaseModel):
    """User-facing explanations for one terminal recommendation result."""

    model_config = ConfigDict(extra="forbid")

    status: RecommendationStatus
    destinations: list[DestinationExplanation] = Field(
        default_factory=list, max_length=3
    )
    no_match: NoMatchExplanation | None = None

    @model_validator(mode="after")
    def validate_result_shape(self) -> "RecommendationExplanationSet":
        """Keep explanation output aligned with its terminal status."""
        if self.status == RecommendationStatus.SUCCESS:
            if not self.destinations or self.no_match is not None:
                raise ValueError("success explanations require destination text only")
        elif self.destinations or self.no_match is None:
            raise ValueError("no_match explanations require no-match guidance only")
        return self


class ExplainedRecommendationResponse(RecommendationResponse):
    """Recommendation response with grounded user-facing explanations."""

    explanations: RecommendationExplanationSet


class DestinationFactClaim(BaseModel):
    """Request a rendered rank or score fact for one destination."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["destination_fact"] = "destination_fact"
    destination_id: str = Field(pattern=r"^[a-z0-9_]+$")
    fact: Literal["rank", "score"]


class DestinationComparisonClaim(BaseModel):
    """Request a comparison whose value must exist in the evidence matrix."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["destination_comparison"] = "destination_comparison"
    destination_id: str = Field(pattern=r"^[a-z0-9_]+$")
    other_destination_id: str = Field(pattern=r"^[a-z0-9_]+$")
    metric: Literal[
        "score",
        "combined_price",
        "combined_travel",
        "preference_match",
        "travel_fairness",
    ]


class FairnessClaim(BaseModel):
    """Request the narrowly defined ranking-fairness explanation."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["fairness"] = "fairness"
    destination_id: str = Field(pattern=r"^[a-z0-9_]+$")


class FreshnessClaim(BaseModel):
    """Request a freshness statement drawn from response metadata."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["freshness"] = "freshness"


class ExclusionClaim(BaseModel):
    """Request no-match guidance for an exact recorded exclusion."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["exclusion"] = "exclusion"
    destination_id: str = Field(pattern=r"^[a-z0-9_]+$")
    traveler_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    reason_code: DestinationExclusionReason


ExplanationClaim = Annotated[
    DestinationFactClaim
    | DestinationComparisonClaim
    | FairnessClaim
    | FreshnessClaim
    | ExclusionClaim,
    Field(discriminator="kind"),
]
