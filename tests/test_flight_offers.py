"""Tests for normalized flight offers, fixture loading, and selection policy."""

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from travel_ai.providers.fixtures import (
    DEFAULT_FLIGHT_OFFERS_PATH,
    FixtureDataError,
    FixtureFlightOfferProvider,
)
from travel_ai.schemas.flights import FlightOffer, FlightSearchQuery
from travel_ai.services.fixture_loader import load_destination_fixtures
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


def miami_search_query(
    traveler_id: str = "traveler_a",
    origin_id: str = "boston_ma",
    origin_airport_codes: list[str] | None = None,
) -> FlightSearchQuery:
    """Return the Miami search represented by the expanded fixtures."""
    return FlightSearchQuery(
        traveler_id=traveler_id,
        origin_id=origin_id,
        destination_id="miami_fl",
        origin_airport_codes=origin_airport_codes or ["BOS"],
        destination_airport_codes=["MIA"],
        departure_date=date(2099, 6, 10),
        return_date=date(2099, 6, 14),
    )


def destination_search_query(
    traveler_id: str,
    origin_id: str,
    destination_id: str,
    origin_airport_code: str,
    destination_airport_code: str,
) -> FlightSearchQuery:
    """Return the standard fixture search for one traveler and candidate city."""
    return FlightSearchQuery(
        traveler_id=traveler_id,
        origin_id=origin_id,
        destination_id=destination_id,
        origin_airport_codes=[origin_airport_code],
        destination_airport_codes=[destination_airport_code],
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


def test_miami_fixtures_cover_price_duration_and_connection_tradeoffs() -> None:
    """Both travelers have comparable nonstop and connecting alternatives."""
    provider = FixtureFlightOfferProvider()

    traveler_a_offers = provider.search(miami_search_query())
    traveler_b_offers = provider.search(
        miami_search_query("traveler_b", "new_york_ny", ["JFK"])
    )

    assert len(traveler_a_offers) == len(traveler_b_offers) == 2
    for offers in (traveler_a_offers, traveler_b_offers):
        nonstop = next(offer for offer in offers if offer.is_round_trip_nonstop)
        connecting = next(offer for offer in offers if not offer.is_round_trip_nonstop)

        assert nonstop.total_amount > connecting.total_amount
        assert nonstop.total_travel_minutes < connecting.total_travel_minutes
        assert (
            nonstop.outbound_slice.segments[-1].arrival_at
            != connecting.outbound_slice.segments[-1].arrival_at
        )


@pytest.mark.parametrize("destination_id", ["miami_fl", "seattle_wa", "denver_co"])
def test_expanded_fixture_durations_match_timestamps(destination_id: str) -> None:
    """Expanded fixture durations include flight and layover time across zones."""
    records = json.loads(DEFAULT_FLIGHT_OFFERS_PATH.read_text(encoding="utf-8"))
    offers = [
        FlightOffer.model_validate(record)
        for record in records
        if record["destination_id"] == destination_id
    ]
    assert offers
    for offer in offers:
        for flight_slice in (offer.outbound_slice, offer.return_slice):
            elapsed = (
                flight_slice.segments[-1].arrival_at
                - flight_slice.segments[0].departure_at
            )
            assert timedelta(minutes=flight_slice.duration_minutes) == elapsed, (
                offer.offer_id,
                flight_slice.origin_airport_code,
            )


def test_every_fixture_offer_targets_a_supported_candidate_city() -> None:
    """Flight fixtures may start anywhere but must end in the candidate pool."""
    supported_destination_ids = {
        city.city_id for city in load_destination_fixtures().cities
    }
    fixture_records = json.loads(DEFAULT_FLIGHT_OFFERS_PATH.read_text(encoding="utf-8"))
    fixture_destination_ids = {record["destination_id"] for record in fixture_records}

    assert fixture_destination_ids <= supported_destination_ids


def test_fixture_dataset_covers_eligible_and_no_match_workflow_scenarios() -> None:
    """Three cities are eligible under the standard fixture request; Denver is not."""
    provider = FixtureFlightOfferProvider()
    standard_city_queries = {
        "chicago_il": ("ORD",),
        "miami_fl": ("MIA",),
        "seattle_wa": ("SEA",),
    }

    for city_id, (airport_code,) in standard_city_queries.items():
        traveler_a_offers = provider.search(
            destination_search_query(
                "traveler_a", "boston_ma", city_id, "BOS", airport_code
            )
        )
        traveler_b_offers = provider.search(
            destination_search_query(
                "traveler_b", "new_york_ny", city_id, "JFK", airport_code
            )
        )

        assert len(traveler_a_offers) >= 2
        assert len(traveler_b_offers) >= 2
        assert all(
            offer.total_amount <= Decimal("500.00") for offer in traveler_a_offers
        )
        assert all(
            offer.total_amount <= Decimal("500.00") for offer in traveler_b_offers
        )
        assert all(
            offer.maximum_one_way_travel_minutes <= 600
            for offer in traveler_a_offers + traveler_b_offers
        )

    denver_a_offers = provider.search(
        destination_search_query("traveler_a", "boston_ma", "denver_co", "BOS", "DEN")
    )
    denver_b_offers = provider.search(
        destination_search_query("traveler_b", "new_york_ny", "denver_co", "JFK", "DEN")
    )

    assert [offer.offer_id for offer in denver_a_offers] == [
        "fixture_a_denver_over_budget"
    ]
    assert [offer.offer_id for offer in denver_b_offers] == [
        "fixture_b_denver_excessive_time"
    ]
    assert denver_a_offers[0].total_amount > Decimal("500.00")
    assert denver_b_offers[0].maximum_one_way_travel_minutes > 600


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


def test_expired_offer_metadata_is_allowed_for_research_results() -> None:
    """V1 may compare a recorded offer without promising current bookability."""
    provider = FixtureFlightOfferProvider()
    offer_data = provider.search(chicago_search_query())[0].model_dump()
    retrieved_at = datetime(2099, 6, 1, 12, tzinfo=UTC)
    offer_data["retrieved_at"] = retrieved_at
    offer_data["expires_at"] = retrieved_at - timedelta(minutes=1)

    offer = FlightOffer.model_validate(offer_data)

    assert offer.expires_at < offer.retrieved_at


def test_flight_pairs_derive_arrival_and_time_together_metrics() -> None:
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
    assert synchronized_pair.time_together_minutes == 5955
    assert synchronized_pair.traveler_a_connections == 2
    assert synchronized_pair.traveler_b_connections == 0


def test_flight_pairs_require_the_same_destination_airport() -> None:
    """V1 does not pair arrivals at different airports in the same metro area."""
    provider = FixtureFlightOfferProvider()
    traveler_a_offers = provider.search(chicago_search_query())
    traveler_b_offers = provider.search(
        chicago_search_query("traveler_b", "new_york_ny", ["JFK", "LGA", "EWR"])
    )
    mdw_offer = traveler_b_offers[0].model_copy(
        update={
            "offer_id": "fixture_b_chicago_mdw",
            "outbound_slice": traveler_b_offers[0].outbound_slice.model_copy(
                update={"destination_airport_code": "MDW"}
            ),
            "return_slice": traveler_b_offers[0].return_slice.model_copy(
                update={"origin_airport_code": "MDW"}
            ),
        }
    )

    pairs = build_flight_offer_pairs(traveler_a_offers, [mdw_offer])

    assert pairs == []


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
                    scored.score_breakdown.time_together,
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


def test_connection_score_averages_each_travelers_connection_burden() -> None:
    """One nonstop and one one-stop itinerary receive a 0.75 pair score."""
    provider = FixtureFlightOfferProvider()
    pair = build_flight_offer_pairs(
        provider.search(chicago_search_query()),
        provider.search(
            chicago_search_query("traveler_b", "new_york_ny", ["JFK", "LGA", "EWR"])
        ),
    )[0].model_copy(
        update={
            "traveler_a_connections": 1,
            "traveler_b_connections": 0,
            "total_connections": 1,
        }
    )

    scored = score_flight_offer_pairs([pair])[0]

    assert scored.score_breakdown.connections.value == 0.75


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
