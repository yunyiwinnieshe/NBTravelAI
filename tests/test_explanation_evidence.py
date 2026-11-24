"""Tests for grounded explanation contracts and evidence assembly."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from travel_ai.schemas.explanations import (
    DestinationExplanation,
    NoMatchExplanation,
    RecommendationExplanationEvidence,
)
from travel_ai.schemas.trip import TripRequest
from travel_ai.services.explanation_evidence import build_explanation_evidence
from travel_ai.services.recommendation_service import RecommendationService

EVALUATED_AT = datetime(2099, 6, 1, 10, tzinfo=UTC)


def trip_request(*, budget: int = 500) -> TripRequest:
    """Build the canonical two-traveler request used by fixture recommendations."""
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
                    "preferences": {
                        "interest_tags": ["museums"],
                        "temperature_range": {
                            "minimum_celsius": 18,
                            "maximum_celsius": 27,
                        },
                    },
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


def response_for(request: TripRequest):
    """Run the deterministic fixture workflow at a fixed evaluation time."""
    return RecommendationService(clock=lambda: EVALUATED_AT).get_recommendations(
        request
    )


def test_builds_allowlisted_evidence_from_verified_result() -> None:
    request = trip_request()
    response = response_for(request)

    evidence = build_explanation_evidence(request, response)

    assert evidence.status == "success"
    assert evidence.trip_start_date.isoformat() == "2099-06-10"
    assert evidence.freshness.evaluated_at == EVALUATED_AT
    assert evidence.freshness.data_mode == "fixture"
    assert len(evidence.destinations) == 3

    chicago = evidence.destinations[0]
    assert chicago.rank == 1
    assert chicago.destination_id == "chicago_il"
    assert chicago.destination_name == "Chicago"
    assert chicago.score_breakdown == response.recommendations[0].score_breakdown
    assert chicago.recommended_pair.combined_price_usd == Decimal("639.00")
    assert chicago.recommended_pair.combined_travel_minutes == 675
    assert [item.traveler_id for item in chicago.recommended_pair.travelers] == [
        "alex",
        "jamie",
    ]
    assert chicago.recommended_pair.travelers[0].budget_utilization == pytest.approx(
        0.648
    )

    serialized = evidence.model_dump(mode="json")
    assert "flight_options_by_traveler" not in serialized["destinations"][0]
    assert "carrier_codes" not in str(serialized)
    assert "matched_interest_tags" not in str(serialized)


def test_keeps_requested_preferences_distinct_from_verified_match_score() -> None:
    request = trip_request()
    evidence = build_explanation_evidence(request, response_for(request))

    assert evidence.travelers[0].requested_preferences.interest_tags == ["museums"]
    assert evidence.travelers[1].requested_preferences.interest_tags == ["nature"]
    assert evidence.destinations[
        0
    ].score_breakdown.preference_match.value == pytest.approx(0.5)
    assert not hasattr(evidence.destinations[0], "matched_interest_tags")


def test_builds_signed_destination_comparisons() -> None:
    request = trip_request()
    evidence = build_explanation_evidence(request, response_for(request))

    chicago = evidence.destinations[0]
    seattle = next(
        item
        for item in chicago.comparisons
        if item.other_destination_id == "seattle_wa"
    )
    assert seattle.score_difference > 0
    assert seattle.combined_price_difference_usd == Decimal("-291.00")
    assert seattle.combined_travel_difference_minutes == -780
    assert seattle.preference_match_difference == pytest.approx(-0.5)


def test_no_match_evidence_contains_exclusions_without_ranked_destinations() -> None:
    request = trip_request(budget=1)
    evidence = build_explanation_evidence(request, response_for(request))

    assert evidence.status == "no_match"
    assert evidence.destinations == []
    assert evidence.exclusions
    assert {item.reason_code for item in evidence.exclusions} == {"no_eligible_flight"}
    assert {item.traveler_id for item in evidence.exclusions} == {"alex", "jamie"}


def test_rejects_recommendation_traveler_absent_from_request() -> None:
    request = trip_request()
    response = response_for(request)
    altered = request.model_copy(deep=True)
    altered.travelers[0].traveler_id = "someone_else"

    with pytest.raises(ValueError, match="absent from the confirmed request"):
        build_explanation_evidence(altered, response)


def test_explanation_contracts_forbid_unreviewed_fields_and_blank_guidance() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DestinationExplanation(
            destination_id="chicago_il",
            summary="Chicago ranks first on the verified score.",
            freshness_note="Fixture data evaluated at the recorded time.",
            unsupported_claim="Chicago is the safest city.",
        )

    with pytest.raises(ValidationError, match="blank statements"):
        NoMatchExplanation(
            summary="No destination met both travelers' constraints.",
            guidance=["  "],
            freshness_note="Fixture data evaluated at the recorded time.",
        )


def test_evidence_contract_forbids_fields_outside_the_allowlist() -> None:
    request = trip_request()
    payload = build_explanation_evidence(request, response_for(request)).model_dump(
        mode="json"
    )
    payload["general_city_knowledge"] = "Chicago is famous for architecture."

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RecommendationExplanationEvidence.model_validate(payload)
