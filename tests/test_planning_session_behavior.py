"""Acceptance cases for the agreed planning-session behavior (no network)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from travel_ai.main import create_app
from travel_ai.routers.trip_sessions import get_trip_session_service
from travel_ai.schemas.preference_extraction import PreferenceExtractionResult
from travel_ai.schemas.sessions import TripRequestDraft
from travel_ai.services.preference_extraction import FixturePreferenceExtractor
from travel_ai.services.recommendation_service import RecommendationService
from travel_ai.services.trip_session_service import (
    TripSessionNotReadyError,
    TripSessionService,
)


def extraction(a=None, b=None, issues=None, **dates):
    """Script only mentioned values, keeping both stable IDs in every turn."""
    return PreferenceExtractionResult(
        draft=TripRequestDraft.model_validate(
            {
                "travelers": [
                    {"traveler_id": "traveler_a", **(a or {})},
                    {"traveler_id": "traveler_b", **(b or {})},
                ],
                **dates,
            }
        ),
        status="needs_clarification" if issues else "ready_for_review",
        missing_fields=issues or [],
    )


def issue(path, reason="ambiguous", question="What exact budget does Bob mean?"):
    return {"field_path": path, "reason": reason, "clarification_question": question}


@pytest.fixture
def workflow():
    results = {
        "partial": extraction(
            {"display_name": "Alice", "origin": "Boston"},
            {"display_name": "Bob", "origin": "New York"},
            start_date="2099-06-10",
            end_date="2099-06-14",
        ),
        "complete": extraction(
            {
                "origin": "Boston",
                "display_name": "Alice",
                "budget_usd": 500,
                "max_travel_time_hours": 6,
            },
            {
                "origin": "New York",
                "display_name": "Bob",
                "budget_usd": 450,
                "max_travel_time_hours": 5,
            },
            start_date="2099-06-10",
            end_date="2099-06-14",
        ),
    }
    recommendations = Mock(wraps=RecommendationService())
    service = TripSessionService(FixturePreferenceExtractor(results), recommendations)
    session_id = service.create_session(None).session_id
    return service, session_id, results, recommendations


def test_partial_details_and_one_focused_question(workflow):
    service, sid, _, recommendations = workflow
    turn = service.add_message(sid, "partial")
    assert turn.state == "collecting"  # Despite extractor claiming readiness.
    assert (
        turn.assistant_message
        == "What is Alice's maximum round-trip airfare budget in USD?"
    )
    assert len(turn.missing_fields) == 4
    assert [t.origin_id for t in turn.trip_request_draft.travelers] == [
        "boston_ma",
        "new_york_ny",
    ]
    recommendations.get_recommendations.assert_not_called()


def test_unclear_value_preserves_old_value_and_saves_other_preferences(workflow):
    service, sid, scripts, _ = workflow
    service.add_message(sid, "complete")
    scripts["unclear"] = extraction(
        {"preferences": {"interest_tags": ["food"]}},
        {"preferences": {"interest_tags": ["food"]}},
        issues=[issue("travelers.traveler_b.budget_usd")],
    )
    turn = service.add_message(sid, "unclear")
    assert turn.state == "collecting"
    assert turn.trip_request_draft.travelers[1].budget_usd == 450
    assert all(
        t.preferences.interest_tags == ["food"]
        for t in turn.trip_request_draft.travelers
    )
    scripts["name"] = extraction({"display_name": "Winnie"})
    assert service.add_message(sid, "name").state == "collecting"
    scripts["clarify"] = extraction(b={"budget_usd": 450})
    assert service.add_message(sid, "clarify").state == "review"


def test_complete_review_and_single_traveler_correction(workflow):
    service, sid, scripts, recommendations = workflow
    turn = service.add_message(sid, "complete")
    assert turn.state == "review"
    assert "Boston (boston_ma)" in turn.assistant_message
    assert "New York (new_york_ny)" in turn.assistant_message
    assert turn.assistant_message.count("Preferences: none provided") == 2
    scripts["correction"] = extraction({"budget_usd": 600})
    updated = service.add_message(sid, "correction")
    assert updated.trip_request_draft.travelers[0].budget_usd == 600
    assert (
        updated.trip_request_draft.travelers[1] == turn.trip_request_draft.travelers[1]
    )
    assert updated.trip_request_draft.start_date == turn.trip_request_draft.start_date
    recommendations.get_recommendations.assert_not_called()


@pytest.mark.parametrize("empty", [False, True])
def test_confirmation_cached_until_change_including_no_match(workflow, empty):
    service, sid, scripts, recommendations = workflow
    service.add_message(sid, "complete")
    if empty:
        scripts["cheap"] = extraction({"budget_usd": 1}, {"budget_usd": 1})
        service.add_message(sid, "cheap")
    first = service.confirm_session(sid)
    assert first.state == ("no_match" if empty else "results")
    assert service.confirm_session(sid) == first
    assert recommendations.get_recommendations.call_count == 1
    scripts["unchanged"] = extraction()
    assert service.add_message(sid, "unchanged") == first
    scripts["change"] = extraction({"budget_usd": 600})
    assert service.add_message(sid, "change").state == "review"
    assert recommendations.get_recommendations.call_count == 1
    service.confirm_session(sid)
    assert recommendations.get_recommendations.call_count == 2


@pytest.mark.parametrize("origin", ["Vancouver", "Tokyo", "New York"])
def test_invalid_or_same_origin_stays_collecting_preserving_valid_values(
    workflow, origin
):
    service, sid, scripts, recommendations = workflow
    service.add_message(sid, "complete")
    scripts["origin"] = extraction({"origin": origin, "budget_usd": 650})
    turn = service.add_message(sid, "origin")
    assert turn.state == "collecting"
    assert turn.trip_request_draft.travelers[0].origin_id == "boston_ma"
    assert turn.trip_request_draft.travelers[0].budget_usd == 650
    with pytest.raises(TripSessionNotReadyError):
        service.confirm_session(sid)
    recommendations.get_recommendations.assert_not_called()


@pytest.mark.parametrize(
    "dates",
    [
        {"start_date": date.today() - timedelta(days=1)},
        {"end_date": "2099-06-20"},
        {"end_date": "2099-06-09"},
    ],
)
def test_bad_dates_do_not_replace_valid_dates(workflow, dates):
    service, sid, scripts, _ = workflow
    previous = service.add_message(sid, "complete")
    scripts["bad dates"] = extraction({"budget_usd": 650}, **dates)
    turn = service.add_message(sid, "bad dates")
    assert turn.state == "collecting"
    assert turn.trip_request_draft.start_date == previous.trip_request_draft.start_date
    assert turn.trip_request_draft.end_date == previous.trip_request_draft.end_date
    assert turn.trip_request_draft.travelers[0].budget_usd == 650


def test_hard_constraints_before_unsupported_preference(workflow):
    service, sid, scripts, _ = workflow
    scripts["unsupported"] = extraction(
        issues=[
            issue(
                "travelers.traveler_a.preferences.interest_tags",
                "unsupported",
                "Ski-in lodging is outside V1. "
                "Would you like to remove that preference?",
            )
        ]
    )
    turn = service.add_message(sid, "unsupported")
    assert turn.assistant_message == "What is your start date?"
    turn = service.add_message(sid, "complete")
    assert "outside V1" in turn.assistant_message
    scripts["remove"] = extraction({"preferences": {"interest_tags": []}})
    assert service.add_message(sid, "remove").state == "review"


@pytest.mark.parametrize(
    "payload", [{}, {"message": "hi", "action": "confirm"}, {"action": "book"}]
)
def test_message_contract_rejects_invalid_actions(workflow, payload):
    service, sid, _, _ = workflow
    app = create_app()
    app.dependency_overrides[get_trip_session_service] = lambda: service
    with TestClient(app) as client:
        assert (
            client.post(f"/trip-sessions/{sid}/messages", json=payload).status_code
            == 422
        )


def test_confirmation_action_is_idempotent_over_http(workflow):
    service, sid, _, recommendations = workflow
    service.add_message(sid, "complete")
    app = create_app()
    app.dependency_overrides[get_trip_session_service] = lambda: service
    with TestClient(app) as client:
        url = f"/trip-sessions/{sid}/messages"
        assert client.post(url, json={"message": "confirm"}).status_code == 422
        recommendations.get_recommendations.assert_not_called()
        first = client.post(url, json={"action": "confirm"})
        assert first.status_code == 200
        assert client.post(url, json={"action": "confirm"}).json() == first.json()
    assert recommendations.get_recommendations.call_count == 1


def test_concurrent_confirmation_runs_only_once(workflow):
    service, sid, _, recommendations = workflow
    service.add_message(sid, "complete")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(service.confirm_session, [sid, sid]))
    assert results[0] == results[1]
    assert recommendations.get_recommendations.call_count == 1


def test_invalid_correction_after_results_requires_clarification(workflow):
    service, sid, scripts, recommendations = workflow
    service.add_message(sid, "complete")
    service.confirm_session(sid)
    scripts["invalid budget"] = extraction(
        b={"preferences": {"interest_tags": ["food"]}},
        issues=[
            issue(
                "travelers.traveler_a.budget_usd",
                "invalid",
                "Please provide a positive budget in USD.",
            )
        ],
    )
    turn = service.add_message(sid, "invalid budget")
    assert turn.state == "collecting"
    assert not turn.recommendations
    assert turn.trip_request_draft.travelers[0].budget_usd == 500
    assert turn.trip_request_draft.travelers[1].preferences.interest_tags == ["food"]
    with pytest.raises(TripSessionNotReadyError):
        service.confirm_session(sid)
    assert recommendations.get_recommendations.call_count == 1


def test_same_origins_on_first_turn_keeps_one_valid_origin(workflow):
    service, sid, scripts, _ = workflow
    scripts["same"] = extraction({"origin": "Boston"}, {"origin": "Boston"})
    turn = service.add_message(sid, "same")
    assert turn.state == "collecting"
    assert turn.trip_request_draft.travelers[0].origin_id == "boston_ma"
    assert turn.trip_request_draft.travelers[1].origin_id is None


def test_recommendation_failure_does_not_become_no_match_or_cached(workflow):
    service, sid, _, recommendations = workflow
    service.add_message(sid, "complete")
    recommendations.get_recommendations.side_effect = RuntimeError("provider failure")
    with pytest.raises(RuntimeError, match="provider failure"):
        service.confirm_session(sid)
    assert service._sessions[sid].state == "review"
    assert service._sessions[sid].confirmed_result is None
