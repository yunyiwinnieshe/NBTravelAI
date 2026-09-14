"""Tests for the finalized public recommendation response contract."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from travel_ai.schemas.recommendations import RecommendationResponse


def flight_option(
    traveler_id: str,
    offer_id: str,
    labels: list[str],
    price: str,
    *,
    arrival_hour: int,
    return_hour: int,
) -> dict[str, object]:
    """Build one compact round-trip option for contract tests."""
    origin = "BOS" if traveler_id == "traveler_a" else "JFK"
    outbound_departure = datetime(2099, 6, 10, 8, tzinfo=UTC)
    outbound_arrival = datetime(2099, 6, 10, arrival_hour, tzinfo=UTC)
    return_departure = datetime(2099, 6, 14, return_hour, tzinfo=UTC)
    return_arrival = return_departure + timedelta(hours=5)
    return {
        "offer_id": offer_id,
        "traveler_id": traveler_id,
        "labels": labels,
        "round_trip_price_usd": price,
        "outbound": {
            "origin_airport_code": origin,
            "destination_airport_code": "ORD",
            "departure_at": outbound_departure.isoformat(),
            "arrival_at": outbound_arrival.isoformat(),
            "duration_minutes": 300,
            "connection_count": 0,
            "carrier_codes": ["ZZ"],
        },
        "return_flight": {
            "origin_airport_code": "ORD",
            "destination_airport_code": origin,
            "departure_at": return_departure.isoformat(),
            "arrival_at": return_arrival.isoformat(),
            "duration_minutes": 300,
            "connection_count": 0,
            "carrier_codes": ["ZZ"],
        },
        "total_travel_minutes": 600,
        "total_connections": 0,
        "is_round_trip_nonstop": True,
        "expires_at": "2099-06-01T12:00:00+00:00",
    }


def valid_response() -> dict[str, object]:
    """Build a successful result containing four labeled options per traveler."""
    traveler_a_options = [
        flight_option(
            "traveler_a",
            "offer_a2",
            ["recommended_pair", "fewest_connections"],
            "300.00",
            arrival_hour=13,
            return_hour=15,
        ),
        flight_option(
            "traveler_a",
            "offer_a1",
            ["lowest_price"],
            "250.00",
            arrival_hour=16,
            return_hour=14,
        ),
        flight_option(
            "traveler_a",
            "offer_a3",
            ["shortest_travel"],
            "330.00",
            arrival_hour=12,
            return_hour=16,
        ),
    ]
    traveler_b_options = [
        flight_option(
            "traveler_b",
            "offer_b1",
            ["recommended_pair", "shortest_travel"],
            "315.00",
            arrival_hour=14,
            return_hour=14,
        ),
        flight_option(
            "traveler_b",
            "offer_b2",
            ["lowest_price"],
            "270.00",
            arrival_hour=17,
            return_hour=13,
        ),
        flight_option(
            "traveler_b",
            "offer_b3",
            ["fewest_connections"],
            "325.00",
            arrival_hour=15,
            return_hour=15,
        ),
    ]
    return {
        "status": "success",
        "recommendations": [
            {
                "rank": 1,
                "destination": {
                    "destination_id": "chicago_il",
                    "name": "Chicago",
                    "state_code": "IL",
                    "metro_airport_codes": ["ORD", "MDW"],
                },
                "score": 0.8,
                "score_breakdown": {
                    "affordability": {
                        "value": 0.8,
                        "weight": 0.35,
                        "contribution": 0.28,
                    },
                    "travel_fairness": {
                        "value": 0.8,
                        "weight": 0.30,
                        "contribution": 0.24,
                    },
                    "preference_match": {
                        "value": 0.8,
                        "weight": 0.20,
                        "contribution": 0.16,
                    },
                    "travel_time": {
                        "value": 0.8,
                        "weight": 0.15,
                        "contribution": 0.12,
                    },
                    "travel_fairness_details": {
                        "duration_balance": 0.8,
                        "budget_burden_balance": 0.8,
                        "arrival_alignment": 0.8,
                    },
                },
                "recommended_pair": {
                    "offers": [
                        {"traveler_id": "traveler_a", "offer_id": "offer_a2"},
                        {"traveler_id": "traveler_b", "offer_id": "offer_b1"},
                    ],
                    "combined_price_usd": "615.00",
                    "arrival_gap_minutes": 60,
                    "return_departure_gap_minutes": 60,
                    "time_together_minutes": 5760,
                    "total_connections": 0,
                    "combined_travel_minutes": 1200,
                    "selection_score": 0.92,
                    "selection_score_breakdown": {
                        "price": {
                            "value": 0.9,
                            "weight": 0.35,
                            "contribution": 0.315,
                        },
                        "arrival_alignment": {
                            "value": 1.0,
                            "weight": 0.25,
                            "contribution": 0.25,
                        },
                        "travel_time": {
                            "value": 0.8,
                            "weight": 0.20,
                            "contribution": 0.16,
                        },
                        "connections": {
                            "value": 1.0,
                            "weight": 0.10,
                            "contribution": 0.10,
                        },
                        "time_together": {
                            "value": 0.95,
                            "weight": 0.10,
                            "contribution": 0.095,
                        },
                    },
                    "price_comparison": {
                        "lowest_valid_combined_price_usd": "580.00",
                        "premium_usd": "35.00",
                        "premium_percentage": 6.03,
                    },
                },
                "flight_options_by_traveler": [
                    {
                        "traveler_id": "traveler_a",
                        "options": traveler_a_options,
                    },
                    {
                        "traveler_id": "traveler_b",
                        "options": traveler_b_options,
                    },
                ],
            }
        ],
        "exclusions": [],
        "metadata": {
            "evaluated_at": "2099-06-01T10:00:00+00:00",
            "candidate_pool_version": "v1.0",
            "data_mode": "fixture",
            "eligible_destination_count": 1,
        },
    }


def test_success_response_deduplicates_category_winners() -> None:
    """One offer may represent multiple categories without requiring backfill."""
    response = RecommendationResponse.model_validate(valid_response())

    assert response.status == "success"
    assert len(response.recommendations[0].flight_options_by_traveler[0].options) == 3
    assert response.recommendations[0].recommended_pair.combined_price_usd == Decimal(
        "615.00"
    )


def test_response_rejects_more_than_four_options_per_traveler() -> None:
    """The public response stays bounded even when a provider returns many offers."""
    payload = valid_response()
    recommendation = payload["recommendations"][0]  # type: ignore[index]
    options = recommendation["flight_options_by_traveler"][0]["options"]  # type: ignore[index]
    options.extend(  # type: ignore[union-attr]
        [
            flight_option(
                "traveler_a",
                "offer_a4",
                ["lowest_price"],
                "340.00",
                arrival_hour=14,
                return_hour=14,
            ),
            flight_option(
                "traveler_a",
                "offer_a5",
                ["shortest_travel"],
                "350.00",
                arrival_hour=14,
                return_hour=14,
            ),
        ]
    )

    with pytest.raises(ValidationError, match="at most 4 items"):
        RecommendationResponse.model_validate(payload)


def test_pair_price_comparison_allows_a_premium_above_fifty_percent() -> None:
    """The response explains high premiums without enforcing a fixed guardrail."""
    payload = valid_response()
    pair = payload["recommendations"][0]["recommended_pair"]  # type: ignore[index]
    pair["combined_price_usd"] = "615.00"  # type: ignore[index]
    pair["price_comparison"] = {  # type: ignore[index]
        "lowest_valid_combined_price_usd": "300.00",
        "premium_usd": "315.00",
        "premium_percentage": 105.0,
    }

    response = RecommendationResponse.model_validate(payload)

    assert (
        response.recommendations[0].recommended_pair.price_comparison.premium_percentage
        == 105.0
    )


def test_response_requires_recommended_offer_in_traveler_options() -> None:
    """Pair references cannot point to an offer hidden from the customer."""
    payload = valid_response()
    recommendation = payload["recommendations"][0]  # type: ignore[index]
    recommendation["recommended_pair"]["offers"][0]["offer_id"] = "missing_offer"  # type: ignore[index]

    with pytest.raises(ValidationError, match="must appear"):
        RecommendationResponse.model_validate(payload)


def test_response_requires_recommended_pair_to_arrive_at_same_airport() -> None:
    """The V1 response cannot publish a pair that needs an airport transfer."""
    payload = valid_response()
    recommendation = payload["recommendations"][0]  # type: ignore[index]
    traveler_b = recommendation["flight_options_by_traveler"][1]  # type: ignore[index]
    recommended = traveler_b["options"][0]  # type: ignore[index]
    recommended["outbound"]["destination_airport_code"] = "MDW"  # type: ignore[index]
    recommended["return_flight"]["origin_airport_code"] = "MDW"  # type: ignore[index]

    with pytest.raises(ValidationError, match="same destination airport"):
        RecommendationResponse.model_validate(payload)


def test_no_match_response_has_no_recommendations() -> None:
    """A completed evaluation may return exclusions instead of ranked cities."""
    payload = valid_response()
    payload["status"] = "no_match"
    payload["recommendations"] = []
    payload["exclusions"] = [
        {
            "destination_id": "chicago_il",
            "traveler_id": "traveler_a",
            "reason_code": "no_eligible_flight",
        }
    ]
    payload["metadata"]["eligible_destination_count"] = 0  # type: ignore[index]

    response = RecommendationResponse.model_validate(payload)

    assert response.status == "no_match"
    assert response.exclusions[0].reason_code == "no_eligible_flight"
