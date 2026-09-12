"""Public contracts for deterministic destination recommendations."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from travel_ai.schemas.flights import FlightPairScoreBreakdown


class RecommendationStatus(StrEnum):
    """Terminal outcomes for a completed recommendation request."""

    SUCCESS = "success"
    NO_MATCH = "no_match"


class RecommendationDataMode(StrEnum):
    """Sources used to produce a recommendation response."""

    FIXTURE = "fixture"
    LIVE = "live"


class FlightOptionLabel(StrEnum):
    """Customer-facing reasons that a flight option was selected."""

    RECOMMENDED_PAIR = "recommended_pair"
    LOWEST_PRICE = "lowest_price"
    SHORTEST_TRAVEL = "shortest_travel"
    FEWEST_CONNECTIONS = "fewest_connections"


class DestinationExclusionReason(StrEnum):
    """Stable public reason codes for excluding a candidate city."""

    NO_ELIGIBLE_FLIGHT = "no_eligible_flight"


class DestinationSummary(BaseModel):
    """Stable destination details needed by a recommendation client."""

    model_config = ConfigDict(extra="forbid")

    destination_id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=120)
    state_code: str = Field(pattern=r"^[A-Z]{2}$")
    metro_airport_codes: list[str] = Field(min_length=1, max_length=3)

    @field_validator("metro_airport_codes")
    @classmethod
    def validate_airport_codes(cls, codes: list[str]) -> list[str]:
        """Require unique uppercase IATA codes in provider-search order."""
        if any(
            len(code) != 3
            or not code.isascii()
            or not code.isalpha()
            or code != code.upper()
            for code in codes
        ):
            raise ValueError("airport codes must contain three uppercase ASCII letters")
        if len(codes) != len(set(codes)):
            raise ValueError("airport codes must not contain duplicates")
        return codes


class ScoreComponent(BaseModel):
    """One normalized component of a destination's final score."""

    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=0, le=1)
    weight: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_contribution(self) -> "ScoreComponent":
        """Keep the published contribution consistent with value times weight."""
        if abs(self.contribution - (self.value * self.weight)) > 0.0005:
            raise ValueError("contribution must equal value multiplied by weight")
        return self


class ScoreBreakdown(BaseModel):
    """Fixed V1 scoring dimensions used for every destination."""

    model_config = ConfigDict(extra="forbid")

    affordability: ScoreComponent
    travel_fairness: ScoreComponent
    preference_match: ScoreComponent
    travel_time: ScoreComponent
    travel_fairness_details: "TravelFairnessDetails"

    @model_validator(mode="after")
    def validate_weights(self) -> "ScoreBreakdown":
        """Require the four scoring weights to form one complete score."""
        components = (
            self.affordability,
            self.travel_fairness,
            self.preference_match,
            self.travel_time,
        )
        if abs(sum(component.weight for component in components) - 1.0) > 0.0005:
            raise ValueError("score component weights must add up to 1")
        if (
            abs(
                self.travel_fairness.value
                - self.travel_fairness_details.calculated_value
            )
            > 0.0005
        ):
            raise ValueError(
                "travel fairness value must match its detailed calculation"
            )
        return self


class TravelFairnessDetails(BaseModel):
    """Auditable subcomponents of the destination travel-fairness feature."""

    model_config = ConfigDict(extra="forbid")

    duration_balance: float = Field(ge=0, le=1)
    budget_burden_balance: float = Field(ge=0, le=1)
    arrival_alignment: float = Field(ge=0, le=1)

    @property
    def calculated_value(self) -> float:
        """Combine duration, budget burden, and arrival alignment for V1."""
        return (
            0.50 * self.duration_balance
            + 0.30 * self.budget_burden_balance
            + 0.20 * self.arrival_alignment
        )


class FlightJourneySummary(BaseModel):
    """Compact public view of one direction of a round trip."""

    model_config = ConfigDict(extra="forbid")

    origin_airport_code: str = Field(pattern=r"^[A-Z]{3}$")
    destination_airport_code: str = Field(pattern=r"^[A-Z]{3}$")
    departure_at: datetime
    arrival_at: datetime
    duration_minutes: int = Field(gt=0, le=2_880)
    connection_count: int = Field(ge=0)
    carrier_codes: list[str] = Field(min_length=1)

    @field_validator("carrier_codes")
    @classmethod
    def validate_carrier_codes(cls, codes: list[str]) -> list[str]:
        """Require unique uppercase two-character airline codes."""
        if any(
            len(code) != 2
            or not code.isascii()
            or not code.isalnum()
            or code != code.upper()
            for code in codes
        ):
            raise ValueError("carrier codes must be uppercase two-character codes")
        if len(codes) != len(set(codes)):
            raise ValueError("carrier codes must not contain duplicates")
        return codes

    @model_validator(mode="after")
    def validate_timestamps(self) -> "FlightJourneySummary":
        """Require timezone-aware chronological journey timestamps."""
        if self.departure_at.tzinfo is None or self.arrival_at.tzinfo is None:
            raise ValueError("journey timestamps must include a timezone")
        if self.arrival_at <= self.departure_at:
            raise ValueError("arrival_at must be after departure_at")
        return self


class FlightOption(BaseModel):
    """Customer-facing round-trip flight option with selection labels."""

    model_config = ConfigDict(extra="forbid")

    offer_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    traveler_id: str = Field(pattern=r"^[a-z0-9_]+$")
    labels: list[FlightOptionLabel] = Field(min_length=1)
    round_trip_price_usd: Decimal = Field(gt=0)
    outbound: FlightJourneySummary
    return_flight: FlightJourneySummary
    total_travel_minutes: int = Field(gt=0)
    total_connections: int = Field(ge=0)
    is_round_trip_nonstop: bool
    expires_at: datetime | None = None

    @field_validator("labels")
    @classmethod
    def validate_labels(
        cls, labels: list[FlightOptionLabel]
    ) -> list[FlightOptionLabel]:
        """Prevent duplicate explanation labels on one option."""
        if len(labels) != len(set(labels)):
            raise ValueError("flight option labels must not contain duplicates")
        return labels

    @field_validator("round_trip_price_usd")
    @classmethod
    def limit_money_precision(cls, amount: Decimal) -> Decimal:
        """Keep customer-facing USD prices precise to cents."""
        if amount.as_tuple().exponent < -2:
            raise ValueError("round_trip_price_usd must contain at most two decimals")
        return amount

    @model_validator(mode="after")
    def validate_round_trip(self) -> "FlightOption":
        """Keep public totals, route direction, and timestamps consistent."""
        if self.outbound.destination_airport_code != (
            self.return_flight.origin_airport_code
        ):
            raise ValueError("return flight must depart from the outbound destination")
        if self.return_flight.destination_airport_code != (
            self.outbound.origin_airport_code
        ):
            raise ValueError("return flight must arrive at the outbound origin")
        if self.return_flight.departure_at <= self.outbound.arrival_at:
            raise ValueError("return flight must depart after outbound arrival")

        calculated_minutes = (
            self.outbound.duration_minutes + self.return_flight.duration_minutes
        )
        if self.total_travel_minutes != calculated_minutes:
            raise ValueError("total_travel_minutes must equal both journey durations")

        calculated_connections = (
            self.outbound.connection_count + self.return_flight.connection_count
        )
        if self.total_connections != calculated_connections:
            raise ValueError("total_connections must equal both journey connections")
        if self.is_round_trip_nonstop != (calculated_connections == 0):
            raise ValueError("is_round_trip_nonstop must match the journey connections")

        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must include a timezone")
        return self


class TravelerOfferReference(BaseModel):
    """Reference to one selected offer for one traveler."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(pattern=r"^[a-z0-9_]+$")
    offer_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")


class PairPriceComparison(BaseModel):
    """Comparison of the recommended pair with the cheapest valid pair."""

    model_config = ConfigDict(extra="forbid")

    lowest_valid_combined_price_usd: Decimal = Field(gt=0)
    premium_usd: Decimal = Field(ge=0)
    premium_percentage: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_percentage(self) -> "PairPriceComparison":
        """Keep the published percentage consistent with its dollar premium."""
        calculated = float(
            self.premium_usd / self.lowest_valid_combined_price_usd * Decimal("100")
        )
        if abs(self.premium_percentage - calculated) > 0.01:
            raise ValueError("premium_percentage must match the published prices")
        return self


class RecommendedFlightPair(BaseModel):
    """The compatible pair used for city scoring and the primary suggestion."""

    model_config = ConfigDict(extra="forbid")

    offers: list[TravelerOfferReference] = Field(min_length=2, max_length=2)
    combined_price_usd: Decimal = Field(gt=0)
    arrival_gap_minutes: int = Field(ge=0)
    return_departure_gap_minutes: int = Field(ge=0)
    shared_trip_minutes: int = Field(gt=0)
    total_connections: int = Field(ge=0)
    combined_travel_minutes: int = Field(gt=0)
    selection_score: float = Field(ge=0, le=1)
    selection_score_breakdown: FlightPairScoreBreakdown
    price_comparison: PairPriceComparison

    @model_validator(mode="after")
    def validate_pair(self) -> "RecommendedFlightPair":
        """Require two distinct travelers and a consistent price comparison."""
        traveler_ids = [offer.traveler_id for offer in self.offers]
        offer_ids = [offer.offer_id for offer in self.offers]
        if len(set(traveler_ids)) != 2:
            raise ValueError("recommended pair must contain two distinct travelers")
        if len(set(offer_ids)) != 2:
            raise ValueError("recommended pair must contain two distinct offers")
        if self.combined_price_usd != (
            self.price_comparison.lowest_valid_combined_price_usd
            + self.price_comparison.premium_usd
        ):
            raise ValueError("combined price must equal baseline price plus premium")
        return self


class TravelerFlightOptions(BaseModel):
    """Up to four distinct round-trip choices for one traveler."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(pattern=r"^[a-z0-9_]+$")
    options: list[FlightOption] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_options(self) -> "TravelerFlightOptions":
        """Require unique offers owned by the enclosing traveler."""
        if any(option.traveler_id != self.traveler_id for option in self.options):
            raise ValueError("all flight options must belong to the traveler")
        offer_ids = [option.offer_id for option in self.options]
        if len(offer_ids) != len(set(offer_ids)):
            raise ValueError("traveler flight option IDs must be unique")
        recommended_count = sum(
            FlightOptionLabel.RECOMMENDED_PAIR in option.labels
            for option in self.options
        )
        if recommended_count > 1:
            raise ValueError("only one option may be labeled recommended_pair")
        return self


class DestinationRecommendation(BaseModel):
    """One ranked city, its score, and selectable flights for both travelers."""

    model_config = ConfigDict(extra="forbid")

    rank: int = Field(ge=1, le=3)
    destination: DestinationSummary
    score: float = Field(ge=0, le=1)
    score_breakdown: ScoreBreakdown
    recommended_pair: RecommendedFlightPair
    flight_options_by_traveler: list[TravelerFlightOptions] = Field(
        min_length=2,
        max_length=2,
    )

    @model_validator(mode="after")
    def validate_recommendation(self) -> "DestinationRecommendation":
        """Ensure the score and recommended offer references are self-consistent."""
        components = (
            self.score_breakdown.affordability,
            self.score_breakdown.travel_fairness,
            self.score_breakdown.preference_match,
            self.score_breakdown.travel_time,
        )
        calculated_score = sum(component.contribution for component in components)
        if abs(self.score - calculated_score) > 0.0005:
            raise ValueError("score must equal the sum of score contributions")

        groups_by_traveler = {
            group.traveler_id: group for group in self.flight_options_by_traveler
        }
        if len(groups_by_traveler) != 2:
            raise ValueError("flight options must contain two distinct travelers")

        selected_options: list[FlightOption] = []
        for reference in self.recommended_pair.offers:
            group = groups_by_traveler.get(reference.traveler_id)
            if group is None:
                raise ValueError("recommended traveler must have a flight option list")
            selected = next(
                (
                    option
                    for option in group.options
                    if option.offer_id == reference.offer_id
                ),
                None,
            )
            if selected is None:
                raise ValueError(
                    "recommended offer must appear in its traveler option list"
                )
            if FlightOptionLabel.RECOMMENDED_PAIR not in selected.labels:
                raise ValueError(
                    "recommended offer must carry the recommended_pair label"
                )
            selected_options.append(selected)

        if (
            sum(
                (option.round_trip_price_usd for option in selected_options),
                start=Decimal("0"),
            )
            != self.recommended_pair.combined_price_usd
        ):
            raise ValueError("recommended pair price must equal its two offer prices")
        if sum(option.total_connections for option in selected_options) != (
            self.recommended_pair.total_connections
        ):
            raise ValueError("recommended pair connections must equal its offer totals")
        if sum(option.total_travel_minutes for option in selected_options) != (
            self.recommended_pair.combined_travel_minutes
        ):
            raise ValueError("recommended pair travel time must equal its offer totals")

        arrivals = [option.outbound.arrival_at for option in selected_options]
        returns = [option.return_flight.departure_at for option in selected_options]
        arrival_gap = int(abs((arrivals[0] - arrivals[1]).total_seconds()) // 60)
        return_departure_gap = int(
            abs((returns[0] - returns[1]).total_seconds()) // 60
        )
        shared_trip = int((min(returns) - max(arrivals)).total_seconds() // 60)
        if arrival_gap != self.recommended_pair.arrival_gap_minutes:
            raise ValueError("recommended pair arrival gap must match its offers")
        if return_departure_gap != (
            self.recommended_pair.return_departure_gap_minutes
        ):
            raise ValueError(
                "recommended pair return departure gap must match its offers"
            )
        if shared_trip != self.recommended_pair.shared_trip_minutes:
            raise ValueError("recommended pair shared trip time must match its offers")
        return self


class DestinationExclusion(BaseModel):
    """Public city-level explanation for a destination that could not qualify."""

    model_config = ConfigDict(extra="forbid")

    destination_id: str = Field(pattern=r"^[a-z0-9_]+$")
    traveler_id: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$")
    reason_code: DestinationExclusionReason


class RecommendationMetadata(BaseModel):
    """Reproducibility metadata for one completed evaluation."""

    model_config = ConfigDict(extra="forbid")

    evaluated_at: datetime
    candidate_pool_version: str = Field(pattern=r"^v[0-9]+(?:\.[0-9]+)*$")
    data_mode: RecommendationDataMode
    eligible_destination_count: int = Field(ge=0)

    @field_validator("evaluated_at")
    @classmethod
    def validate_evaluated_at(cls, evaluated_at: datetime) -> datetime:
        """Require an unambiguous evaluation timestamp."""
        if evaluated_at.tzinfo is None:
            raise ValueError("evaluated_at must include a timezone")
        return evaluated_at


class RecommendationResponse(BaseModel):
    """Final API response after deterministic destination evaluation."""

    model_config = ConfigDict(extra="forbid")

    status: RecommendationStatus
    recommendations: list[DestinationRecommendation] = Field(
        default_factory=list,
        max_length=3,
    )
    exclusions: list[DestinationExclusion] = Field(default_factory=list)
    metadata: RecommendationMetadata

    @model_validator(mode="after")
    def validate_result(self) -> "RecommendationResponse":
        """Keep status, ranks, destination IDs, and metadata consistent."""
        if self.status == RecommendationStatus.SUCCESS and not self.recommendations:
            raise ValueError("success responses must contain a recommendation")
        if self.status == RecommendationStatus.NO_MATCH and self.recommendations:
            raise ValueError("no_match responses cannot contain recommendations")

        ranks = [recommendation.rank for recommendation in self.recommendations]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("recommendation ranks must be consecutive starting at 1")
        destination_ids = [
            recommendation.destination.destination_id
            for recommendation in self.recommendations
        ]
        if len(destination_ids) != len(set(destination_ids)):
            raise ValueError("recommended destination IDs must be unique")
        if self.metadata.eligible_destination_count < len(self.recommendations):
            raise ValueError(
                "eligible destination count cannot be smaller than results"
            )
        return self
