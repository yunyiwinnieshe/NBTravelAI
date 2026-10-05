"""Grade fixed, fixture-backed recommendation examples without model calls."""

from collections import Counter
from datetime import date
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from travel_ai.evaluation.sessions import CountingRecommendations, frozen_dates
from travel_ai.schemas.trip import TripRequest


class RecommendationExpected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["success", "no_match", "validation_error"]
    destination_ids: list[str] = Field(default_factory=list)
    eligible_count: int = Field(ge=0, default=0)
    excluded_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self):
        if self.outcome != "success" and (self.destination_ids or self.eligible_count):
            raise ValueError("non-success outcomes cannot expect destinations")
        if len(set(self.destination_ids)) != len(self.destination_ids):
            raise ValueError("duplicate destination IDs")
        return self


class RecommendationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    description: str
    request: dict[str, Any]
    expected: RecommendationExpected
    label_status: Literal["reviewed", "provisional"] = "reviewed"
    reviewer: str | None = None


class RecommendationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    description: str
    reference_date: date
    cases: list[RecommendationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("recommendation case IDs must be unique")
        return self


def evaluate_recommendations(dataset: RecommendationDataset, repeats=1):
    records = []
    with frozen_dates(dataset.reference_date):
        for repeat in range(1, repeats + 1):
            for case in dataset.cases:
                started = perf_counter()
                checks = []

                def check(name, wanted, actual, checks=checks):
                    checks.append(
                        {
                            "name": name,
                            "expected": wanted,
                            "actual": actual,
                            "passed": wanted == actual,
                        }
                    )

                try:
                    request = TripRequest.model_validate(case.request)
                except ValueError:
                    outcome, response = "validation_error", None
                else:
                    try:
                        response = CountingRecommendations(
                            dataset.reference_date
                        ).get_recommendations(request)
                    except Exception as error:
                        outcome, response = "service_error", None
                        error_type = type(error).__name__
                    else:
                        outcome = response.status.value
                check("outcome", case.expected.outcome, outcome)
                actual = {"outcome": outcome}
                if outcome == "service_error":
                    actual["error_type"] = error_type
                if response is not None:
                    ids = sorted(
                        r.destination.destination_id for r in response.recommendations
                    )
                    exclusions = sorted({r.destination_id for r in response.exclusions})
                    actual.update(
                        destination_ids=ids,
                        eligible_count=response.metadata.eligible_destination_count,
                        excluded_ids=exclusions,
                        data_mode=response.metadata.data_mode.value,
                    )
                    check("destination_ids", sorted(case.expected.destination_ids), ids)
                    check(
                        "eligible_count",
                        case.expected.eligible_count,
                        actual["eligible_count"],
                    )
                    check(
                        "excluded_ids", sorted(case.expected.excluded_ids), exclusions
                    )
                    check("fixture_data", "fixture", actual["data_mode"])
                    check("top_three", True, len(response.recommendations) <= 3)
                    if outcome == "no_match":
                        check(
                            "no_match_has_explanation", True, bool(response.exclusions)
                        )
                    for recommendation in response.recommendations:
                        for group in recommendation.flight_options_by_traveler:
                            traveler = next(
                                t
                                for t in request.travelers
                                if t.traveler_id == group.traveler_id
                            )
                            check(
                                f"budget:{recommendation.destination.destination_id}:{group.traveler_id}",
                                True,
                                all(
                                    o.round_trip_price_usd <= traveler.budget_usd
                                    for o in group.options
                                ),
                            )
                            check(
                                f"travel_time:{recommendation.destination.destination_id}:{group.traveler_id}",
                                True,
                                all(
                                    o.outbound.duration_minutes
                                    <= traveler.max_one_way_travel_minutes
                                    and o.return_flight.duration_minutes
                                    <= traveler.max_one_way_travel_minutes
                                    for o in group.options
                                ),
                            )
                reasons = [check["name"] for check in checks if not check["passed"]]
                records.append(
                    {
                        "case_id": case.id,
                        "category": case.category,
                        "description": case.description,
                        "label_status": case.label_status,
                        "reviewer": case.reviewer,
                        "repeat": repeat,
                        "request": case.request,
                        "expected": case.expected.model_dump(),
                        "actual": actual,
                        "checks": checks,
                        "passed": not reasons,
                        "reasons": reasons,
                        "latency_ms": round((perf_counter() - started) * 1000, 2),
                    }
                )
    return records


def summarize_recommendations(records):
    return {
        "case_runs": len(records),
        "case_runs_passed": sum(record["passed"] for record in records),
        "provisional_case_runs": sum(
            record["label_status"] == "provisional" for record in records
        ),
        "categories": {
            category: {
                "passed": sum(
                    r["passed"] for r in records if r["category"] == category
                ),
                "total": sum(r["category"] == category for r in records),
            }
            for category in sorted({r["category"] for r in records})
        },
        "failure_reasons": dict(
            Counter(reason for r in records for reason in r["reasons"])
        ),
    }
