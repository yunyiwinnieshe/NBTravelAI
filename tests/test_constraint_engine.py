"""Tests for deterministic flight-offer constraints."""

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import TypeAdapter

from travel_ai.providers.fixtures import DEFAULT_FLIGHT_OFFERS_PATH
from travel_ai.schemas.destinations import City
from travel_ai.schemas.flights import FlightOffer
from travel_ai.schemas.trip import TravelerRequest
from travel_ai.services.constraint_engine import (
    evaluate_offer,
    evaluate_traveler_city_offers,
)
from travel_ai.services.fixture_loader import load_destination_fixtures

TRIP_START = date(2099, 6, 10)
TRIP_END = date(2099, 6, 14)
EVALUATED_AT = datetime(2026, 9, 6, 12, tzinfo=UTC)


def base_offer() -> FlightOffer:
    offers = TypeAdapter(list[FlightOffer]).validate_json(
        DEFAULT_FLIGHT_OFFERS_PATH.read_text(encoding="utf-8")
    )
    return offers[0]


def chicago() -> City:
    return next(
        city
        for city in load_destination_fixtures().cities
        if city.city_id == "chicago_il"
    )


def traveler(**updates: object) -> TravelerRequest:
    values: dict[str, object] = {
        "traveler_id": "traveler_a",
        "origin_id": "boston_ma",
        "budget_usd": Decimal("500.00"),
        "max_one_way_travel_minutes": 360,
    }
    values.update(updates)
    return TravelerRequest.model_validate(values)


def evaluate(
    offer: FlightOffer,
    traveler_request: TravelerRequest | None = None,
):
    return evaluate_offer(
        offer=offer,
        traveler=traveler_request or traveler(),
        city=chicago(),
        origin_airport_codes=["BOS"],
        trip_start_date=TRIP_START,
        trip_end_date=TRIP_END,
        evaluated_at=EVALUATED_AT,
    )


def test_valid_offer_is_eligible_at_exact_budget_and_time_boundaries() -> None:
    offer = base_offer()
    exact_boundary_traveler = traveler(
        budget_usd=offer.total_amount,
        max_one_way_travel_minutes=offer.maximum_one_way_travel_minutes,
    )

    assert evaluate(offer, exact_boundary_traveler) is None


@pytest.mark.parametrize(
    ("offer_update", "traveler_update", "expected_reason"),
    [
        (
            {"traveler_id": "traveler_b"},
            {},
            "traveler_mismatch",
        ),
        (
            {"origin_id": "seattle_wa"},
            {},
            "origin_mismatch",
        ),
        (
            {"destination_id": "miami_fl"},
            {},
            "destination_mismatch",
        ),
        (
            {},
            {"max_one_way_travel_minutes": 359},
            "max_travel_time_exceeded",
        ),
        (
            {},
            {"budget_usd": Decimal("299.99")},
            "budget_exceeded",
        ),
        (
            {"is_available": False},
            {},
            "offer_unavailable",
        ),
        (
            {"expires_at": EVALUATED_AT},
            {},
            "offer_expired",
        ),
    ],
)
def test_offer_rules_return_expected_reason(
    offer_update: dict[str, object],
    traveler_update: dict[str, object],
    expected_reason: str,
) -> None:
    offer = base_offer().model_copy(update=offer_update)

    rejection = evaluate(offer, traveler(**traveler_update))

    assert rejection is not None
    assert [reason.value for reason in rejection.reason_codes] == [expected_reason]


def test_date_rule_checks_outbound_and_return_departure_dates() -> None:
    offer = base_offer()
    changed_segment = offer.return_slice.segments[0].model_copy(
        update={"departure_at": datetime(2099, 6, 15, 14, tzinfo=UTC)}
    )
    changed_return = offer.return_slice.model_copy(
        update={"segments": [changed_segment, *offer.return_slice.segments[1:]]}
    )
    changed_offer = offer.model_copy(update={"return_slice": changed_return})

    rejection = evaluate(changed_offer)

    assert rejection is not None
    assert [reason.value for reason in rejection.reason_codes] == ["date_mismatch"]


def test_route_rule_checks_approved_airport_groups() -> None:
    rejection = evaluate_offer(
        offer=base_offer(),
        traveler=traveler(),
        city=chicago(),
        origin_airport_codes=["JFK"],
        trip_start_date=TRIP_START,
        trip_end_date=TRIP_END,
        evaluated_at=EVALUATED_AT,
    )

    assert rejection is not None
    assert [reason.value for reason in rejection.reason_codes] == ["origin_mismatch"]


def test_offer_returns_all_reasons_in_stable_rule_order() -> None:
    offer = base_offer().model_copy(
        update={
            "traveler_id": "traveler_b",
            "origin_id": "seattle_wa",
            "destination_id": "miami_fl",
            "is_available": False,
            "expires_at": EVALUATED_AT,
        }
    )

    rejection = evaluate(
        offer,
        traveler(
            budget_usd=Decimal("100.00"),
            max_one_way_travel_minutes=100,
        ),
    )

    assert rejection is not None
    assert [reason.value for reason in rejection.reason_codes] == [
        "traveler_mismatch",
        "origin_mismatch",
        "destination_mismatch",
        "max_travel_time_exceeded",
        "budget_exceeded",
        "offer_unavailable",
        "offer_expired",
    ]


def test_evaluation_partitions_eligible_and_rejected_offers() -> None:
    valid_offer = base_offer()
    unavailable_offer = valid_offer.model_copy(
        update={"offer_id": "fixture_unavailable", "is_available": False}
    )

    result = evaluate_traveler_city_offers(
        traveler=traveler(),
        city=chicago(),
        origin_airport_codes=["BOS"],
        trip_start_date=TRIP_START,
        trip_end_date=TRIP_END,
        offers=[valid_offer, unavailable_offer],
        evaluated_at=EVALUATED_AT,
    )

    assert [offer.offer_id for offer in result.eligible_offers] == [
        valid_offer.offer_id
    ]
    assert [item.offer_id for item in result.rejected_offers] == ["fixture_unavailable"]
    assert result.city_exclusion is None


def test_evaluation_excludes_city_when_no_offer_is_eligible() -> None:
    result = evaluate_traveler_city_offers(
        traveler=traveler(),
        city=chicago(),
        origin_airport_codes=["BOS"],
        trip_start_date=TRIP_START,
        trip_end_date=TRIP_END,
        offers=[],
        evaluated_at=EVALUATED_AT,
    )

    assert result.eligible_offers == []
    assert result.rejected_offers == []
    assert result.city_exclusion is not None
    assert result.city_exclusion.model_dump(mode="json") == {
        "traveler_id": "traveler_a",
        "city_id": "chicago_il",
        "reason_code": "no_eligible_flight",
    }


def test_evaluation_timestamp_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="must include a timezone"):
        evaluate_offer(
            offer=base_offer(),
            traveler=traveler(),
            city=chicago(),
            origin_airport_codes=["BOS"],
            trip_start_date=TRIP_START,
            trip_end_date=TRIP_END,
            evaluated_at=datetime(2026, 9, 6, 12),
        )


def test_empty_offer_evaluation_timestamp_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="must include a timezone"):
        evaluate_traveler_city_offers(
            traveler=traveler(),
            city=chicago(),
            origin_airport_codes=["BOS"],
            trip_start_date=TRIP_START,
            trip_end_date=TRIP_END,
            offers=[],
            evaluated_at=datetime(2026, 9, 6, 12),
        )
