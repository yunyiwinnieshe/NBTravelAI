"""Contracts for deterministic recommendation results."""

from enum import StrEnum

from pydantic import BaseModel, Field


class RecommendationStatus(StrEnum):
    """States supported by the direct recommendation endpoint."""

    NOT_IMPLEMENTED = "not_implemented"


class DestinationRecommendation(BaseModel):
    """Reserved response contract for a ranked destination in the next milestone."""

    destination_id: str
    destination_name: str
    score: float = Field(ge=0, le=1)


class RecommendationResponse(BaseModel):
    """Stable outer response contract for a complete trip request."""

    status: RecommendationStatus
    recommendations: list[DestinationRecommendation]
    message: str
