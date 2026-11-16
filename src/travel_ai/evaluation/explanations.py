"""Evaluate grounded recommendation explanations without model or network calls."""

from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from travel_ai.schemas.explanations import (
    DestinationComparisonEvidence,
    RankedDestinationEvidence,
    RecommendationExplanationEvidence,
)
from travel_ai.schemas.generated_explanations import ExplainedRecommendationResponse
from travel_ai.schemas.recommendations import DestinationExclusionReason
from travel_ai.schemas.trip import TripRequest
from travel_ai.services.explanation_evidence import build_explanation_evidence
from travel_ai.services.explanation_generation import GroundedRecommendationExplainer
from travel_ai.services.recommendation_service import RecommendationService


class ExplanationCase(BaseModel):
    """One versioned request and expected terminal explanation shape."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, pattern=r"^[a-z0-9_]+$")
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    request: dict[str, Any]
    expected_status: Literal["success", "no_match"]
    generator_mode: Literal["deterministic", "unsafe_claim"] = "deterministic"


class ExplanationDataset(BaseModel):
    """Fixed offline dataset for explanation-quality evaluation."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(pattern=r"^v[0-9]+(?:\.[0-9]+)*$")
    description: str = Field(min_length=1)
    evaluated_at: datetime
    cases: list[ExplanationCase] = Field(min_length=1)

    @field_validator("evaluated_at")
    @classmethod
    def evaluated_at_has_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("evaluated_at must include a timezone")
        return value

    @model_validator(mode="after")
    def unique_case_ids(self) -> "ExplanationDataset":
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("explanation case IDs must be unique")
        return self


def _unsafe_claim_generator(_evidence: object) -> object:
    """Simulate unsupported model output to exercise the safe fallback."""
    return [
        {
            "kind": "destination_fact",
            "destination_id": "chicago_il",
            "fact": "safety",
            "text": "Chicago is the safest option.",
        }
    ]


def _check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str) -> None:
    checks.append({"name": name, "passed": passed, "detail": detail})


def _freshness_notes(response: ExplainedRecommendationResponse) -> list[str]:
    if response.explanations.no_match is not None:
        return [response.explanations.no_match.freshness_note]
    return [item.freshness_note for item in response.explanations.destinations]


def _metric_fragment(metric: str, comparison: DestinationComparisonEvidence) -> str:
    values: dict[str, float | int | Decimal] = {
        "combined_price": comparison.combined_price_difference_usd,
        "combined_travel": comparison.combined_travel_difference_minutes,
        "preference_match": comparison.preference_match_difference,
        "travel_fairness": comparison.travel_fairness_difference,
    }
    value = values[metric]
    if metric == "combined_price":
        return "same combined fare" if value == 0 else f"${abs(value):.2f}"
    if metric == "combined_travel":
        return "same number" if value == 0 else str(abs(value))
    return "equal" if value == 0 else f"{abs(value):.3f}"


def _expected_comparison(
    evidence: RecommendationExplanationEvidence,
    destination: RankedDestinationEvidence,
) -> tuple[RankedDestinationEvidence, DestinationComparisonEvidence] | None:
    if len(evidence.destinations) < 2:
        return None
    other = (
        evidence.destinations[1] if destination.rank == 1 else evidence.destinations[0]
    )
    comparison = next(
        item
        for item in destination.comparisons
        if item.other_destination_id == other.destination_id
    )
    return other, comparison


def _grade_success(
    response: ExplainedRecommendationResponse,
    evidence: RecommendationExplanationEvidence,
    checks: list[dict[str, Any]],
) -> None:
    recommendations = response.recommendations
    explanations = response.explanations.destinations
    expected_ids = [item.destination.destination_id for item in recommendations]
    actual_ids = [item.destination_id for item in explanations]
    _check(
        checks,
        "destination_alignment",
        actual_ids == expected_ids,
        f"expected {expected_ids}; received {actual_ids}",
    )
    by_id = {item.destination_id: item for item in explanations}
    for recommendation, destination in zip(
        recommendations, evidence.destinations, strict=True
    ):
        explanation = by_id.get(destination.destination_id)
        if explanation is None:
            continue
        prefix = destination.destination_id
        expected_summary = (
            f"{destination.destination_name} ranks #{destination.rank} with a verified "
            f"overall score of {destination.score:.3f}."
        )
        _check(
            checks,
            f"summary_facts:{prefix}",
            explanation.summary == expected_summary,
            explanation.summary,
        )
        fairness = explanation.fairness_note or ""
        fairness_score = recommendation.score_breakdown.travel_fairness.value
        fairness_parts = (
            f"{fairness_score:.3f}",
            "budget burden",
            "travel-time burden",
            "arrival timing",
            "does not establish that the trip is fair in every respect",
        )
        _check(
            checks,
            f"bounded_fairness:{prefix}",
            all(part in fairness for part in fairness_parts),
            fairness,
        )
        expected = _expected_comparison(evidence, destination)
        if expected is None:
            _check(
                checks,
                f"tradeoffs:{prefix}",
                not explanation.tradeoffs,
                "single result should not invent a comparison",
            )
            continue
        other, comparison = expected
        metrics = (
            "combined_price",
            "combined_travel",
            "preference_match",
            "travel_fairness",
        )
        grounded = len(explanation.tradeoffs) == len(metrics)
        if grounded:
            for statement, metric in zip(explanation.tradeoffs, metrics, strict=True):
                grounded = grounded and other.destination_name in statement
                grounded = (
                    grounded and _metric_fragment(metric, comparison) in statement
                )
        _check(
            checks,
            f"grounded_tradeoffs:{prefix}",
            grounded,
            f"comparison target={other.destination_name}; {explanation.tradeoffs}",
        )


def _grade_no_match(
    response: ExplainedRecommendationResponse,
    evidence: RecommendationExplanationEvidence,
    checks: list[dict[str, Any]],
) -> None:
    explanation = response.explanations.no_match
    _check(
        checks, "no_match_shape", explanation is not None, "no-match text is required"
    )
    if explanation is None:
        return
    reason_codes = {item.reason_code for item in evidence.exclusions}
    guidance = " ".join(explanation.guidance).lower()
    if DestinationExclusionReason.NO_ELIGIBLE_FLIGHT in reason_codes:
        _check(
            checks,
            "eligible_flight_guidance",
            "budgets and travel-time limits" in guidance,
            guidance,
        )
    if DestinationExclusionReason.NO_COMPATIBLE_FLIGHT_PAIR in reason_codes:
        _check(
            checks,
            "compatible_pair_guidance",
            "compatible pair" in guidance,
            guidance,
        )
    _check(
        checks,
        "bounded_no_match_guidance",
        all(term not in guidance for term in ("guarantee", "will find", "definitely")),
        guidance,
    )


def grade_explanation(
    case: ExplanationCase,
    response: ExplainedRecommendationResponse,
    evidence: RecommendationExplanationEvidence,
) -> list[dict[str, Any]]:
    """Grade exact evidence use and bounded language without subjective scoring."""
    checks: list[dict[str, Any]] = []
    _check(
        checks,
        "expected_status",
        response.status == case.expected_status,
        f"expected {case.expected_status}; received {response.status.value}",
    )
    _check(
        checks,
        "explanation_status",
        response.explanations.status == response.status,
        (
            f"response={response.status.value}; "
            f"explanations={response.explanations.status.value}"
        ),
    )
    expected_freshness = (
        "Based on fixture/test data evaluated at "
        f"{evidence.freshness.evaluated_at.isoformat()} with candidate pool "
        f"{evidence.freshness.candidate_pool_version}."
    )
    notes = _freshness_notes(response)
    _check(
        checks,
        "freshness_and_source",
        bool(notes) and all(note == expected_freshness for note in notes),
        f"expected {expected_freshness}; received {notes}",
    )
    rendered = response.explanations.model_dump_json().lower()
    prohibited = ("safest", "most popular", "completely fair", "guaranteed")
    _check(
        checks,
        "no_unsupported_superlatives",
        all(term not in rendered for term in prohibited),
        f"prohibited terms checked: {prohibited}",
    )
    if case.expected_status == "success":
        _grade_success(response, evidence, checks)
    else:
        _grade_no_match(response, evidence, checks)
    if case.generator_mode == "unsafe_claim":
        _check(
            checks,
            "unsafe_generator_fallback",
            "safest option" not in rendered
            and bool(response.explanations.destinations),
            "unsupported safety claim must be absent after fallback",
        )
    return checks


def evaluate_explanations(dataset: ExplanationDataset) -> list[dict[str, Any]]:
    """Run every case with a fixed clock and retain evidence alongside output."""
    records = []
    for case in dataset.cases:
        explainer = (
            GroundedRecommendationExplainer(_unsafe_claim_generator)
            if case.generator_mode == "unsafe_claim"
            else GroundedRecommendationExplainer()
        )
        service = RecommendationService(
            clock=lambda value=dataset.evaluated_at: value,
            explainer=explainer,
        )
        request = TripRequest.model_validate(case.request)
        response = service.get_recommendations(request)
        evidence = build_explanation_evidence(request, response)
        checks = grade_explanation(case, response, evidence)
        failed = [item["name"] for item in checks if not item["passed"]]
        records.append(
            {
                "case_id": case.id,
                "category": case.category,
                "description": case.description,
                "generator_mode": case.generator_mode,
                "request": case.request,
                "evidence": evidence.model_dump(mode="json"),
                "actual": response.explanations.model_dump(mode="json"),
                "checks": checks,
                "passed": not failed,
                "failure_reasons": failed,
            }
        )
    return records


def summarize_explanations(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize case and check pass rates without turning them into model quality."""
    checks = [check for record in records for check in record["checks"]]
    return {
        "cases": len(records),
        "cases_passed": sum(record["passed"] for record in records),
        "checks": len(checks),
        "checks_passed": sum(check["passed"] for check in checks),
        "categories": {
            category: {
                "passed": sum(
                    record["passed"]
                    for record in records
                    if record["category"] == category
                ),
                "total": sum(record["category"] == category for record in records),
            }
            for category in sorted({record["category"] for record in records})
        },
        "failure_reasons": dict(
            Counter(
                reason for record in records for reason in record["failure_reasons"]
            )
        ),
    }
