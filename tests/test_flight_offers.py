"""Tests for normalized flight offers, fixture loading, and selection policy."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from travel_ai.providers.fixtures import FixtureDataError, FixtureFlightOfferProvider
from travel_ai.schemas.flights import FlightOffer, FlightSearchQuery
from travel_ai.services.flight_offer_selection import (
    build_flight_offer_pairs,
    score_flight_offer_pairs,
    select_display_flight_offers,
    select_recommended_flight_pair,
)


def chicago_search_query(
    traveler_id: str = "traveler_a",
    origin_id: str = "boston_ma",
    origin_airport_codes: list[str] | None = None,
) -> FlightSearchQuery:
    """Return an airport-group query represented by the bundled fixtures."""
    return FlightSearchQuery(
        traveler_id=traveler_id,
        origin_id=origin_id,
        destination_id="chicago_il",
        origin_airport_codes=origin_airport_codes or ["BOS", "PVD"],
        destination_airport_codes=["ORD", "MDW"],
        departure_date=date(2099, 6, 10),
        return_date=date(2099, 6, 14),
    )


def test_fixture_provider_loads_round_trip_offers_for_both_travelers() -> None:
    """The provider returns only records matching each airport-group query."""
    provider = FixtureFlightOfferProvider()

    traveler_a_offers = provider.search(chicago_search_query())
    traveler_b_offers = provider.search(
        chicago_search_query("traveler_b", "new_york_ny", ["JFK", "LGA", "EWR"])
    )

    assert len(traveler_a_offers) == 2
    assert len(traveler_b_offers) == 2
    assert all(offer.outbound_slice.segments for offer in traveler_a_offers)
    assert all(offer.return_slice.segments for offer in traveler_b_offers)


def test_search_query_expands_all_airport_pairs() -> None:
    """Every approved origin airport is searched against every destination airport."""
    query = chicago_search_query()

    assert query.airport_pairs == [
        ("BOS", "ORD"),
        ("BOS", "MDW"),
        ("PVD", "ORD"),
        ("PVD", "MDW"),
    ]


def test_search_query_accepts_three_airports_per_location() -> None:
    """The V1 airport-group limit includes metro areas with three airports."""
    query = chicago_search_query(origin_airport_codes=["JFK", "LGA", "EWR"])

    assert query.origin_airport_codes == ["JFK", "LGA", "EWR"]
    assert len(query.airport_pairs) == 6


def test_search_query_rejects_more_than_three_airports_per_location() -> None:
    """The V1 cap prevents an unexpectedly large number of provider searches."""
    with pytest.raises(ValidationError, match="at most 3 items"):
        chicago_search_query(origin_airport_codes=["JFK", "LGA", "EWR", "SWF"])


def test_fixture_provider_accepts_only_airports_in_the_resolved_groups() -> None:
    """An offer outside the query's approved airport set is not returned."""
    provider = FixtureFlightOfferProvider()

    offers = provider.search(chicago_search_query(origin_airport_codes=["PVD"]))

    assert offers == []


def test_round_trip_offer_derives_connections_and_duration() -> None:
    """Selection features are derived consistently from both journey slices."""
    provider = FixtureFlightOfferProvider()
    offers = provider.search(chicago_search_query())
    connecting = next(
        offer for offer in offers if offer.offer_id == "fixture_a_chicago_connecting"
    )

    assert connecting.total_connections == 2
    assert connecting.total_travel_minutes == 710
    assert connecting.maximum_one_way_travel_minutes == 360
    assert connecting.is_round_trip_nonstop is False


def test_round_trip_offer_must_return_to_its_outbound_origin() -> None:
    """A normalized round trip cannot end at an unrelated airport."""
    provider = FixtureFlightOfferProvider()
    offer_data = provider.search(chicago_search_query())[0].model_dump()
    offer_data["return_slice"]["destination_airport_code"] = "PVD"
    offer_data["return_slice"]["segments"][-1]["destination_airport_code"] = "PVD"

    with pytest.raises(ValidationError, match="outbound origin"):
        FlightOffer.model_validate(offer_data)


def test_flight_pairs_derive_arrival_and_shared_time_metrics() -> None:
    """Every A/B combination records the schedule metrics used for selection."""
    provider = FixtureFlightOfferProvider()
    traveler_a_offers = provider.search(chicago_search_query())
    traveler_b_offers = provider.search(
        chicago_search_query("traveler_b", "new_york_ny", ["JFK", "LGA", "EWR"])
    )

    pairs = build_flight_offer_pairs(traveler_a_offers, traveler_b_offers)
    synchronized_pair = next(pair for pair in pairs if pair.arrival_gap_minutes == 0)

    assert len(pairs) == 4
    assert synchronized_pair.traveler_a_offer_id == "fixture_a_chicago_connecting"
    assert synchronized_pair.traveler_b_offer_id == "fixture_b_chicago_nonstop"
    assert synchronized_pair.combined_price_usd == Decimal("615.00")
    assert synchronized_pair.return_departure_gap_minutes == 120
    assert synchronized_pair.shared_trip_minutes == 5955


def test_every_valid_pair_receives_an_auditable_score() -> None:
    """Pair selection scores every valid combination without a price cutoff."""
    provider = FixtureFlightOfferProvider()
    pairs = build_flight_offer_pairs(
        provider.search(chicago_search_query()),
        provider.search(
            chicago_search_query("traveler_b", "new_york_ny", ["JFK", "LGA", "EWR"])
        ),
    )

    scored_pairs = score_flight_offer_pairs(pairs)

    assert len(scored_pairs) == len(pairs) == 4
    assert all(0 <= scored.selection_score <= 1 for scored in scored_pairs)
    assert all(
        scored.selection_score
        == pytest.approx(
            sum(
                component.contribution
                for component in (
                    scored.score_breakdown.price,
                    scored.score_breakdown.arrival_alignment,
                    scored.score_breakdown.travel_time,
                    scored.score_breakdown.connections,
                    scored.score_breakdown.shared_trip,
                )
            )
        )
        for scored in scored_pairs
    )


def test_recommended_pair_uses_pair_score_without_a_price_guardrail() -> None:
    """An expensive pair remains eligible and competes through normalized price."""
    provider = FixtureFlightOfferProvider()
    pairs = build_flight_offer_pairs(
        provider.search(chicago_search_query()),
        provider.search(
            chicago_search_query("traveler_b", "new_york_ny", ["JFK", "LGA", "EWR"])
        ),
    )
    expensive_pair = next(pair for pair in pairs if pair.arrival_gap_minutes == 0)
    pairs = [
        pair.model_copy(update={"combined_price_usd": Decimal("900.00")})
        if pair == expensive_pair
        else pair
        for pair in pairs
    ]

    selected = select_recommended_flight_pair(pairs)

    assert len(score_flight_offer_pairs(pairs)) == 4
    assert selected.pair in pairs
    assert selected.selection_score == max(
        scored.selection_score for scored in score_flight_offer_pairs(pairs)
    )


def test_arrival_alignment_has_two_hour_preferred_and_six_hour_zero_windows() -> None:
    """The documented arrival thresholds produce full, partial, and zero credit."""
    provider = FixtureFlightOfferProvider()
    base_pair = build_flight_offer_pairs(
        provider.search(chicago_search_query()),
        provider.search(
            chicago_search_query("traveler_b", "new_york_ny", ["JFK", "LGA", "EWR"])
        ),
    )[0]
    pairs = [
        base_pair.model_copy(
            update={
                "traveler_a_offer_id": f"arrival_{gap}",
                "arrival_gap_minutes": gap,
            }
        )
        for gap in (120, 240, 360)
    ]

    scores = {
        scored.pair.arrival_gap_minutes: scored.score_breakdown.arrival_alignment.value
        for scored in score_flight_offer_pairs(pairs)
    }

    assert scores == {120: 1.0, 240: 0.5, 360: 0.0}


def test_display_offers_are_distinct_and_include_recommended_pair_offer() -> None:
    """The bounded customer list retains the pair-selected offer without duplicates."""
    provider = FixtureFlightOfferProvider()
    offers = provider.search(chicago_search_query())
    extra_offer = offers[0].model_copy(
        update={
            "offer_id": "fixture_a_chicago_extra",
            "total_amount": Decimal("310.00"),
        }
    )
    selected = select_display_flight_offers(
        [*offers, extra_offer],
        recommended_offer_id="fixture_a_chicago_extra",
    )

    assert selected[0].offer_id == "fixture_a_chicago_extra"
    assert len(selected) == 3
    assert len({offer.offer_id for offer in selected}) == len(selected)


def test_fixture_provider_reports_invalid_json(tmp_path: Path) -> None:
    """Invalid provider fixtures fail at the data boundary with context."""
    fixture_path = tmp_path / "invalid_flight_offers.json"
    fixture_path.write_text("not-json", encoding="utf-8")

    with pytest.raises(FixtureDataError, match="Invalid flight fixture"):
        FixtureFlightOfferProvider(fixture_path)


def test_pair_selector_requires_at_least_one_pair() -> None:
    """An empty valid pair set is represented as an explicit selection failure."""
    with pytest.raises(ValueError, match="at least one valid flight pair"):
        select_recommended_flight_pair([])
