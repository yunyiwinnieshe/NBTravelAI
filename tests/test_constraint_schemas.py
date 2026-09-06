"""Tests for deterministic exclusion contracts."""

import pytest
from pydantic import ValidationError

from travel_ai.schemas.constraints import (
    CityExclusion,
    ExclusionReason,
    OfferRejection,
)


def valid_offer_rejection_data() -> dict[str, object]:
    """Return a valid offer-level rejection record."""
    return {
        "traveler_id": "traveler_a",
        "city_id": "san_diego_ca",
        "offer_id": "off_0000A3B1",
        "reason_codes": ["max_travel_time_exceeded", "budget_exceeded"],
    }


def test_offer_rejection_accepts_multiple_ordered_reasons() -> None:
    rejection = OfferRejection.model_validate(valid_offer_rejection_data())

    assert rejection.reason_codes == [
        ExclusionReason.MAX_TRAVEL_TIME_EXCEEDED,
        ExclusionReason.BUDGET_EXCEEDED,
    ]
    assert rejection.model_dump(mode="json") == valid_offer_rejection_data()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("traveler_id", "Traveler A"),
        ("city_id", "San Diego"),
        ("offer_id", "   "),
        ("reason_codes", []),
        ("reason_codes", ["unknown_reason"]),
        ("reason_codes", ["budget_exceeded", "budget_exceeded"]),
        ("reason_codes", ["no_eligible_flight"]),
    ],
)
def test_offer_rejection_rejects_invalid_fields(field: str, value: object) -> None:
    data = valid_offer_rejection_data()
    data[field] = value

    with pytest.raises(ValidationError):
        OfferRejection.model_validate(data)


def test_offer_rejection_rejects_unknown_fields() -> None:
    data = valid_offer_rejection_data()
    data["message"] = "This wording belongs outside the domain contract."

    with pytest.raises(ValidationError):
        OfferRejection.model_validate(data)


def test_city_exclusion_uses_no_eligible_flight_by_default() -> None:
    exclusion = CityExclusion(
        traveler_id="traveler_b",
        city_id="san_diego_ca",
    )

    assert exclusion.model_dump(mode="json") == {
        "traveler_id": "traveler_b",
        "city_id": "san_diego_ca",
        "reason_code": "no_eligible_flight",
    }


def test_city_exclusion_rejects_offer_level_reason() -> None:
    with pytest.raises(ValidationError):
        CityExclusion(
            traveler_id="traveler_b",
            city_id="san_diego_ca",
            reason_code=ExclusionReason.BUDGET_EXCEEDED,
        )
