"""Retrieval quality cases and verifier behavior for illustrative activities."""

from travel_ai.services.activity_itinerary import (
    ActivitySearch,
    ItineraryDraft,
    run_itinerary_agent_loop,
    search_activities,
)


def test_retrieval_cases() -> None:
    cases = [
        (
            ActivitySearch(
                city_id="seattle_wa", weekday=6, tags=["kid_friendly", "museums"]
            ),
            {"sea_museum_of_flight"},
        ),
        (
            ActivitySearch(
                city_id="new_york_ny", weekday=6, tags=["nature"], max_price_usd=0
            ),
            {"nyc_central_park"},
        ),
        (
            ActivitySearch(city_id="new_york_ny", weekday=6, neighborhood="Tukwila"),
            set(),
        ),
    ]
    for query, expected in cases:
        assert {item.activity_id for item in search_activities(query)} == expected


def test_agent_loop_repairs_unsupported_activity() -> None:
    available = search_activities(ActivitySearch(city_id="seattle_wa", weekday=6))
    observed_issues: list[list[str]] = []

    def planner(_available, issues):
        observed_issues.append(issues)
        return ItineraryDraft(
            activity_ids=["invented"] if not issues else ["sea_museum_of_flight"]
        )

    result = run_itinerary_agent_loop(available, 40, planner)
    assert result.status == "verified"
    assert result.attempts == 2
    assert observed_issues[1] == ["unknown_or_unavailable_activity"]


def test_agent_loop_rejects_after_bound() -> None:
    available = search_activities(ActivitySearch(city_id="seattle_wa", weekday=6))
    result = run_itinerary_agent_loop(
        available,
        0,
        lambda _items, _issues: ItineraryDraft(activity_ids=["sea_museum_of_flight"]),
    )
    assert result.status == "rejected"
    assert result.activity_ids == []
    assert result.attempts == 3
