"""Regression tests for grounded explanation generation and validation."""

from datetime import UTC, datetime

import pytest

from travel_ai.schemas.trip import TripRequest
from travel_ai.services.explanation_evidence import build_explanation_evidence
from travel_ai.services.explanation_generation import (
    GroundedRecommendationExplainer,
    UnsupportedExplanationClaim,
    validate_claims,
)
from travel_ai.services.recommendation_service import RecommendationService

EVALUATED_AT = datetime(2099, 6, 1, 10, tzinfo=UTC)


def trip_request(*, budget: int = 500) -> TripRequest:
    """Build a canonical fixture request with two distinct travelers."""
    return TripRequest.model_validate(
        {
            "start_date": "2099-06-10",
            "end_date": "2099-06-14",
            "travelers": [
                {
                    "traveler_id": "alex",
                    "origin_id": "boston_ma",
                    "budget_usd": budget,
                    "max_one_way_travel_minutes": 600,
                    "preferences": {"interest_tags": ["museums"]},
                },
                {
                    "traveler_id": "jamie",
                    "origin_id": "new_york_ny",
                    "budget_usd": budget,
                    "max_one_way_travel_minutes": 600,
                    "preferences": {"interest_tags": ["nature"]},
                },
            ],
        }
    )


def service(
    explainer: GroundedRecommendationExplainer | None = None,
) -> RecommendationService:
    """Use a fixed clock so explanation output is reproducible."""
    return RecommendationService(
        clock=lambda: EVALUATED_AT,
        explainer=explainer,
    )


def test_generates_tradeoffs_and_bounded_fairness_language() -> None:
    response = service().get_recommendations(trip_request())

    assert response.status == "success"
    assert [item.destination_id for item in response.explanations.destinations] == [
        recommendation.destination.destination_id
        for recommendation in response.recommendations
    ]
    first = response.explanations.destinations[0]
    assert first.tradeoffs
    assert "travel-fairness score" in first.fairness_note
    assert "does not establish that the trip is fair in every respect" in (
        first.fairness_note
    )
    rendered = response.explanations.model_dump_json().lower()
    assert "completely fair" not in rendered
    assert "safest" not in rendered
    assert "most popular" not in rendered


def test_rejects_unsupported_claim_shape() -> None:
    request = trip_request()
    response = service().get_recommendations(request)
    evidence = build_explanation_evidence(request, response)

    with pytest.raises(UnsupportedExplanationClaim):
        validate_claims(
            evidence,
            [
                {
                    "kind": "destination_fact",
                    "destination_id": "chicago_il",
                    "fact": "safety",
                }
            ],
        )


def test_unsafe_custom_generator_falls_back_to_grounded_output() -> None:
    def unsafe_generator(_evidence: object) -> object:
        return [
            {
                "kind": "destination_fact",
                "destination_id": "chicago_il",
                "fact": "safety",
                "text": "Chicago is the safest choice.",
            }
        ]

    explainer = GroundedRecommendationExplainer(unsafe_generator)
    response = service(explainer).get_recommendations(trip_request())
    rendered = response.explanations.model_dump_json().lower()

    assert response.status == "success"
    assert "safest" not in rendered
    assert response.explanations.destinations[0].summary.startswith("Chicago ranks #1")


def test_no_match_guidance_is_bounded_and_does_not_promise_results() -> None:
    response = service().get_recommendations(trip_request(budget=100))

    assert response.status == "no_match"
    assert response.explanations.destinations == []
    explanation = response.explanations.no_match
    assert explanation is not None
    assert explanation.guidance
    rendered = explanation.model_dump_json().lower()
    assert "guarantee" not in rendered
    assert "will find" not in rendered
    assert "fixture/test data" in explanation.freshness_note
