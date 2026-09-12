"""Provider-independent contracts for normalized round-trip flight offers."""

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class CabinClass(StrEnum):
    """Cabin classes supported by the normalized offer contract."""

    ECONOMY = "economy"


class FlightSearchQuery(BaseModel):
    """One traveler's round-trip search across two resolved airport groups."""

    model_config = ConfigDict(extra="forbid")

    traveler_id: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    origin_id: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9_]+$")
    destination_id: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9_]+$")
    origin_airport_codes: list[str] = Field(min_length=1, max_length=3)
    destination_airport_codes: list[str] = Field(min_length=1, max_length=3)
    departure_date: date
    return_date: date
    cabin_class: CabinClass = CabinClass.ECONOMY

    @field_validator("origin_airport_codes", "destination_airport_codes")
    @classmethod
    def validate_airport_codes(cls, codes: list[str]) -> list[str]:
        """Require unique uppercase IATA airport codes in deterministic order."""
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

    @model_validator(mode="after")
    def validate_dates(self) -> "FlightSearchQuery":
        """Require a return date after the outbound departure date."""
        if self.return_date <= self.departure_date:
            raise ValueError("return_date must be after departure_date")
        return self

    @property
    def airport_pairs(self) -> list[tuple[str, str]]:
        """Expand all approved origin-to-destination airport combinations."""
        return [
            (origin_code, destination_code)
            for origin_code in self.origin_airport_codes
            for destination_code in self.destination_airport_codes
        ]


class FlightSegment(BaseModel):
    """One operated flight within an outbound or return slice."""

    model_config = ConfigDict(extra="forbid")

    origin_airport_code: str = Field(pattern=r"^[A-Z]{3}$")
    destination_airport_code: str = Field(pattern=r"^[A-Z]{3}$")
    departure_at: datetime
    arrival_at: datetime
    marketing_carrier_code: str = Field(pattern=r"^[A-Z0-9]{2}$")
    operating_carrier_code: str = Field(pattern=r"^[A-Z0-9]{2}$")
    flight_number: str = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_timestamps(self) -> "FlightSegment":
        """Require timezone-aware timestamps in chronological order."""
        if self.departure_at.tzinfo is None or self.arrival_at.tzinfo is None:
            raise ValueError("flight timestamps must include a timezone")
        if self.arrival_at <= self.departure_at:
            raise ValueError("arrival_at must be after departure_at")
        return self


class FlightSlice(BaseModel):
    """One complete outbound or return journey, including connections."""

    model_config = ConfigDict(extra="forbid")

    origin_airport_code: str = Field(pattern=r"^[A-Z]{3}$")
    destination_airport_code: str = Field(pattern=r"^[A-Z]{3}$")
    duration_minutes: int = Field(gt=0, le=2_880)
    segments: list[FlightSegment] = Field(min_length=1)

    @property
    def connection_count(self) -> int:
        """Return the number of connections represented by the segments."""
        return len(self.segments) - 1

    @model_validator(mode="after")
    def validate_segment_path(self) -> "FlightSlice":
        """Require segments to form one continuous path between slice airports."""
        if self.segments[0].origin_airport_code != self.origin_airport_code:
            raise ValueError("first segment must depart from the slice origin")
        if self.segments[-1].destination_airport_code != self.destination_airport_code:
            raise ValueError("last segment must arrive at the slice destination")

        for current, following in zip(self.segments, self.segments[1:], strict=False):
            if current.destination_airport_code != following.origin_airport_code:
                raise ValueError("flight segments must form a continuous airport path")
            if following.departure_at <= current.arrival_at:
                raise ValueError("a connecting segment must depart after arrival")
        return self


class FlightOffer(BaseModel):
    """One priced round-trip offer for one traveler and destination."""

    model_config = ConfigDict(extra="forbid")

    offer_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    provider: str = Field(min_length=1, max_length=50)
    provider_offer_id: str | None = Field(default=None, max_length=200)
    traveler_id: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9_]+$")
    origin_id: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9_]+$")
    destination_id: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9_]+$")
    cabin_class: CabinClass = CabinClass.ECONOMY
    total_amount: Decimal = Field(gt=0)
    currency: str = Field(default="USD", pattern=r"^USD$")
    outbound_slice: FlightSlice
    return_slice: FlightSlice
    retrieved_at: datetime
    expires_at: datetime | None = None
    is_available: bool = True
    is_fixture: bool = False

    @field_validator("total_amount")
    @classmethod
    def limit_money_precision(cls, amount: Decimal) -> Decimal:
        """Reject provider prices with fractions smaller than one cent."""
        if amount.as_tuple().exponent < -2:
            raise ValueError("total_amount must contain at most two decimal places")
        return amount

    @model_validator(mode="after")
    def validate_round_trip(self) -> "FlightOffer":
        """Validate chronology, route direction, and live-offer freshness data."""
        outbound_arrival = self.outbound_slice.segments[-1].arrival_at
        return_departure = self.return_slice.segments[0].departure_at
        if return_departure <= outbound_arrival:
            raise ValueError("return flight must depart after outbound arrival")

        if self.outbound_slice.destination_airport_code != (
            self.return_slice.origin_airport_code
        ):
            raise ValueError("return slice must depart from the outbound destination")
        if self.return_slice.destination_airport_code != (
            self.outbound_slice.origin_airport_code
        ):
            raise ValueError("return slice must arrive at the outbound origin")

        if self.retrieved_at.tzinfo is None:
            raise ValueError("retrieved_at must include a timezone")
        if self.expires_at is not None:
            if self.expires_at.tzinfo is None:
                raise ValueError("expires_at must include a timezone")
            if self.expires_at <= self.retrieved_at:
                raise ValueError("expires_at must be after retrieved_at")
        return self

    @property
    def total_travel_minutes(self) -> int:
        """Return total in-air and connection time across both slices."""
        return self.outbound_slice.duration_minutes + self.return_slice.duration_minutes

    @property
    def maximum_one_way_travel_minutes(self) -> int:
        """Return the longer of the two one-way slice durations."""
        return max(
            self.outbound_slice.duration_minutes,
            self.return_slice.duration_minutes,
        )

    @property
    def total_connections(self) -> int:
        """Return total connections across outbound and return slices."""
        return self.outbound_slice.connection_count + self.return_slice.connection_count

    @property
    def is_round_trip_nonstop(self) -> bool:
        """Return whether both directions contain exactly one segment."""
        return self.total_connections == 0


class FlightOfferPair(BaseModel):
    """Derived compatibility metrics for one offer from each traveler."""

    model_config = ConfigDict(extra="forbid")

    traveler_a_id: str = Field(pattern=r"^[a-z0-9_]+$")
    traveler_a_offer_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    traveler_b_id: str = Field(pattern=r"^[a-z0-9_]+$")
    traveler_b_offer_id: str = Field(pattern=r"^[a-z0-9]+(?:_[a-z0-9]+)*$")
    destination_id: str = Field(pattern=r"^[a-z0-9_]+$")
    combined_price_usd: Decimal = Field(gt=0)
    arrival_gap_minutes: int = Field(ge=0)
    return_departure_gap_minutes: int = Field(ge=0)
    shared_trip_minutes: int = Field(gt=0)
    total_connections: int = Field(ge=0)
    combined_travel_minutes: int = Field(gt=0)


class PairScoreComponent(BaseModel):
    """One normalized and weighted flight-pair selection component."""

    model_config = ConfigDict(extra="forbid")

    value: float = Field(ge=0, le=1)
    weight: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_contribution(self) -> "PairScoreComponent":
        """Keep the contribution consistent with its value and weight."""
        if abs(self.contribution - (self.value * self.weight)) > 0.000001:
            raise ValueError("contribution must equal value multiplied by weight")
        return self


class FlightPairScoreBreakdown(BaseModel):
    """Explain how one valid pair compares with every pair for a city."""

    model_config = ConfigDict(extra="forbid")

    price: PairScoreComponent
    arrival_alignment: PairScoreComponent
    travel_time: PairScoreComponent
    connections: PairScoreComponent
    shared_trip: PairScoreComponent

    @model_validator(mode="after")
    def validate_weights(self) -> "FlightPairScoreBreakdown":
        """Require pair-selection weights to form one complete score."""
        if abs(
            sum(
                component.weight
                for component in (
                    self.price,
                    self.arrival_alignment,
                    self.travel_time,
                    self.connections,
                    self.shared_trip,
                )
            )
            - 1.0
        ) > 0.000001:
            raise ValueError("pair score component weights must add up to 1")
        return self


class ScoredFlightOfferPair(BaseModel):
    """A valid flight pair plus its auditable selection score."""

    model_config = ConfigDict(extra="forbid")

    pair: FlightOfferPair
    selection_score: float = Field(ge=0, le=1)
    score_breakdown: FlightPairScoreBreakdown

    @model_validator(mode="after")
    def validate_selection_score(self) -> "ScoredFlightOfferPair":
        """Keep the published total equal to the component contributions."""
        calculated = sum(
            component.contribution
            for component in (
                self.score_breakdown.price,
                self.score_breakdown.arrival_alignment,
                self.score_breakdown.travel_time,
                self.score_breakdown.connections,
                self.score_breakdown.shared_trip,
            )
        )
        if abs(self.selection_score - calculated) > 0.000001:
            raise ValueError("selection_score must equal the score contributions")
        return self
