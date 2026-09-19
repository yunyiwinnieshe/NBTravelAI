"""Internal contracts for deterministic destination ranking."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from travel_ai.schemas.flights import FlightOffer, ScoredFlightOfferPair
from travel_ai.schemas.preference_features import CityPreferenceFeatures
from travel_ai.schemas.recommendations import ScoreBreakdown
from travel_ai.schemas.trip import TravelerRequest


class DestinationRankingInput(BaseModel):
    """One eligible destination; the scorer checks cross-field consistency."""

    model_config = ConfigDict(extra="forbid")

    destination_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    travelers: tuple[TravelerRequest, TravelerRequest]
    recommended_pair: ScoredFlightOfferPair
    recommended_offers: tuple[FlightOffer, FlightOffer]
    preference_features: CityPreferenceFeatures


class RankedDestinationScore(BaseModel):
    """Auditable score and stable tie-break values for one destination."""

    model_config = ConfigDict(extra="forbid")

    destination_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    score: float = Field(ge=0, le=1)
    score_breakdown: ScoreBreakdown
    combined_airfare_usd: Decimal = Field(gt=0)
    combined_travel_minutes: int = Field(gt=0)
