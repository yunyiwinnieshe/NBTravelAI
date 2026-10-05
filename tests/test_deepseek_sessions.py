"""Session API integration with real extraction code and mocked DeepSeek HTTP."""

import json
from threading import Event
from time import monotonic
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from travel_ai.main import create_app
from travel_ai.routers import trip_sessions as routes
from travel_ai.services.deepseek_preference_extraction import (
    DeepSeekConfigurationError,
    DeepSeekPreferenceExtractor,
    DeepSeekSettings,
)
from travel_ai.services.session_extraction import (
    SessionExtractionPolicy,
)


def reply(operations=None, issues=None, unsupported=None, acknowledgments=None):
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": json.dumps(
                            {
                                "operations": operations or [],
                                "missing_fields": issues or [],
                                "unsupported_requests": unsupported or [],
                                "acknowledged_unsupported": acknowledgments or [],
                            }
                        )
                    },
                }
            ]
        },
    )


def op(path, value, evidence, action="set"):
    return dict(op=action, field_path=path, value=value, evidence=evidence)


COMPLETE = (
    "I'm Alice from Boston; Bob is from New York. "
    "June 10–14, 2099; $500 USD airfare each, 10 hours each."
)


def complete_reply(message=COMPLETE):
    return reply(
        [
            op("start_date", "2099-06-10", message),
            op("end_date", "2099-06-14", message),
            *[
                op(f"travelers.{tid}.{field}", value, message)
                for tid, name, origin in [
                    ("traveler_a", "Alice", "Boston"),
                    ("traveler_b", "Bob", "New York"),
                ]
                for field, value in [
                    ("display_name", name),
                    ("origin", origin),
                    ("budget_usd", 500),
                    ("max_travel_time_hours", 10),
                ]
            ],
        ]
    )


@pytest.fixture
def live_api(monkeypatch):
    """Select the live factory but replace only its network transport."""
    routes.get_trip_session_service.cache_clear()
    monkeypatch.setenv("EXTRACTION_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setenv("DEEPSEEK_MAX_RETRIES", "1")
    script = {"handler": lambda request, context: reply()}
    calls = []

    def handler(request):
        context = json.loads(json.loads(request.content)["messages"][1]["content"])
        calls.append(context)
        return script["handler"](request, context)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        monkeypatch.setattr(
            routes,
            "DeepSeekPreferenceExtractor",
            lambda: DeepSeekPreferenceExtractor(
                DeepSeekSettings.from_environment(),
                http_client=http,
            ),
        )
        with TestClient(create_app()) as client:
            service = routes.get_trip_session_service()
            service.recommendation_service = Mock(wraps=service.recommendation_service)
            yield client, service, script, calls
    routes.get_trip_session_service.cache_clear()


def start_complete(live_api):
    client, service, script, calls = live_api
    script["handler"] = lambda request, context: complete_reply()
    result = client.post("/trip-sessions", json={"initial_message": COMPLETE})
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "review"
    service.recommendation_service.get_recommendations.assert_not_called()
    return result.json()


def snapshot(service, sid):
    session = service._sessions[sid]
    return (
        session.draft.model_dump(),
        dict(session.issues),
        session.state,
        list(session.missing_questions),
        dict(session.unsupported),
        session.confirmed_result.model_dump() if session.confirmed_result else None,
    )


def test_live_factory_complete_correct_confirm_and_no_match(live_api):
    client, service, script, calls = live_api
    first = start_complete(live_api)
    sid = first["session_id"]
    url = f"/trip-sessions/{sid}/messages"
    message = "My airfare budget is $600 USD."
    script["handler"] = lambda request, context: reply(
        [
            op("travelers.traveler_a.budget_usd", 600, message),
        ]
    )
    updated = client.post(url, json={"message": message}).json()
    assert (
        updated["trip_request_draft"]["travelers"][1]
        == first["trip_request_draft"]["travelers"][1]
    )
    assert (
        updated["trip_request_draft"]["start_date"]
        == first["trip_request_draft"]["start_date"]
    )
    assert updated["trip_request_draft"]["travelers"][0]["budget_usd"] == 600
    service.recommendation_service.get_recommendations.assert_not_called()
    # Merely typing confirm does not bypass the structured confirmation gate.
    script["handler"] = lambda request, context: reply()
    assert client.post(url, json={"message": "confirm"}).json()["state"] == "review"
    before = len(calls)
    confirmed = client.post(url, json={"action": "confirm"})
    assert confirmed.json()["state"] == "results"
    assert client.post(url, json={"action": "confirm"}).json() == confirmed.json()
    assert len(calls) == before
    assert service.recommendation_service.get_recommendations.call_count == 1
    message = "We each have a $1 USD airfare budget now."
    script["handler"] = lambda request, context: reply(
        [
            op(f"travelers.{tid}.budget_usd", 1, message)
            for tid in ("traveler_a", "traveler_b")
        ]
    )
    assert client.post(url, json={"message": message}).json()["state"] == "review"
    assert client.post(url, json={"action": "confirm"}).json()["state"] == "no_match"


@pytest.mark.parametrize(
    ("failure", "status", "attempts"),
    [
        ("timeout", 503, 2),
        ("connection", 503, 2),
        ("server", 503, 2),
        ("rate", 503, 2),
        ("json", 502, 1),
        ("auth", 503, 1),
        ("path", 502, 1),
    ],
)
def test_provider_failures_preserve_entire_session(live_api, failure, status, attempts):
    client, service, script, calls = live_api
    sid = start_complete(live_api)["session_id"]
    client.post(f"/trip-sessions/{sid}/messages", json={"action": "confirm"})
    before = snapshot(service, sid)
    count = len(calls)

    def fail(request, context):
        if failure == "timeout":
            raise httpx.ReadTimeout("secret details", request=request)
        if failure == "connection":
            raise httpx.ConnectError("secret details", request=request)
        if failure in ("server", "rate", "auth"):
            return httpx.Response(
                {"server": 503, "rate": 429, "auth": 401}[failure],
                text="secret details",
            )
        if failure == "path":
            return reply([op("travelers.evil.budget_usd", 800, "800")])
        return httpx.Response(200, json={"choices": []})

    script["handler"] = fail
    response = client.post(f"/trip-sessions/{sid}/messages", json={"message": "800"})
    assert response.status_code == status
    assert "secret" not in response.text
    assert snapshot(service, sid) == before
    assert len(calls) - count == attempts


def test_failed_initial_message_leaves_no_orphan_session(live_api):
    client, service, script, _ = live_api
    script["handler"] = lambda request, context: httpx.Response(401)
    before = set(service._sessions)
    assert (
        client.post("/trip-sessions", json={"initial_message": "Hello"}).status_code
        == 503
    )
    assert set(service._sessions) == before


def test_retry_once_then_success(live_api):
    client, service, script, calls = live_api

    def handler(request, context):
        return httpx.Response(503) if len(calls) == 1 else complete_reply()

    script["handler"] = handler
    assert (
        client.post("/trip-sessions", json={"initial_message": COMPLETE}).json()[
            "state"
        ]
        == "review"
    )
    assert len(calls) == 2


def test_short_answer_uses_only_displayed_questions(live_api):
    client, service, script, calls = live_api
    initial = client.post("/trip-sessions", json={}).json()
    sid = initial["session_id"]
    assert len(initial["pending_questions"]) == 3
    script["handler"] = lambda request, context: complete_reply()
    client.post(f"/trip-sessions/{sid}/messages", json={"message": COMPLETE})
    message = "Remove my airfare budget."
    script["handler"] = lambda request, context: reply(
        [op("travelers.traveler_a.budget_usd", None, message, "remove")]
    )
    result = client.post(
        f"/trip-sessions/{sid}/messages", json={"message": message}
    ).json()
    assert result["trip_request_draft"]["travelers"][0]["budget_usd"] is None
    assert len(result["pending_questions"]) == 1
    script["handler"] = lambda request, context: reply(
        [op("travelers.traveler_a.budget_usd", 800, "800")]
    )
    result = client.post(
        f"/trip-sessions/{sid}/messages", json={"message": "800"}
    ).json()
    assert (
        calls[-1]["conversation_context"]["pending_questions"][0]["field_path"]
        == "travelers.traveler_a.budget_usd"
    )
    assert result["state"] == "review"
    assert result["trip_request_draft"]["travelers"][0]["budget_usd"] == 800


@pytest.mark.parametrize("natural", [False, True])
def test_unsupported_notice_persists_until_explicit_acknowledgment(live_api, natural):
    client, service, script, calls = live_api
    sid = start_complete(live_api)["session_id"]
    url = f"/trip-sessions/{sid}/messages"
    message = "I want a hotel with a pool."
    script["handler"] = lambda request, context: reply(
        unsupported=[
            {
                "user_text": message,
                "explanation": "Hotel preferences aren't supported yet.",
            }
        ]
    )
    result = client.post(url, json={"message": message}).json()
    assert result["state"] == "collecting"
    assert "continue without" in result["assistant_message"]
    request_id = result["unsupported_requests"][0]["request_id"]
    assert client.post(url, json={"action": "confirm"}).status_code == 422
    script["handler"] = lambda request, context: reply()
    result = client.post(url, json={"message": "Hello"}).json()
    assert result["unsupported_requests"][0]["request_id"] == request_id
    if natural:
        script["handler"] = lambda request, context: reply(
            acknowledgments=[
                {
                    "request_id": request_id,
                    "evidence": "Yes, continue without the hotel request.",
                }
            ]
        )
        result = client.post(
            url, json={"message": "Yes, continue without the hotel request."}
        ).json()
        assert (
            calls[-1]["conversation_context"]["unsupported_requests"][0]["request_id"]
            == request_id
        )
    else:
        result = client.post(
            url, json={"action": "continue_without_unsupported"}
        ).json()
    assert result["state"] == "review"
    assert result["unsupported_requests"] == []
    assert result["deferred_requests"] == [message]
    service.recommendation_service.get_recommendations.assert_not_called()
    assert client.post(url, json={"action": "confirm"}).json()["state"] == "results"


def test_invalid_acknowledgment_cannot_erase_pending_notice(live_api):
    client, service, script, _ = live_api
    sid = start_complete(live_api)["session_id"]
    script["handler"] = lambda request, context: reply(
        acknowledgments=[
            {
                "request_id": "invented",
                "evidence": "yes",
            }
        ]
    )
    before = snapshot(service, sid)
    assert (
        client.post(
            f"/trip-sessions/{sid}/messages", json={"message": "yes"}
        ).status_code
        == 502
    )
    assert snapshot(service, sid) == before


def test_late_success_after_deadline_never_changes_saved_draft(live_api):
    client, service, script, _ = live_api
    sid = start_complete(live_api)["session_id"]
    service.extractor._policy = SessionExtractionPolicy(total_timeout_seconds=0.05)
    started, release = Event(), Event()
    message = "My airfare budget is $900 USD."

    def delayed(request, context):
        started.set()
        release.wait(2)
        return reply([op("travelers.traveler_a.budget_usd", 900, message)])

    script["handler"] = delayed
    before = snapshot(service, sid)
    start = monotonic()
    response = client.post(f"/trip-sessions/{sid}/messages", json={"message": message})
    assert response.status_code == 503
    assert monotonic() - start < 1
    assert started.is_set()
    release.set()
    service.extractor.close()
    assert snapshot(service, sid) == before


def test_factory_rejects_unknown_mode_and_missing_credentials(monkeypatch):
    for provider in ("unknown", "deepseek"):
        routes.get_trip_session_service.cache_clear()
        monkeypatch.setenv("EXTRACTION_PROVIDER", provider)
        with pytest.raises(DeepSeekConfigurationError):
            routes.get_trip_session_service()


@pytest.mark.parametrize(
    "variable,value",
    [
        ("DEEPSEEK_MAX_RETRIES", "3"),
        ("DEEPSEEK_MAX_RETRIES", "-1"),
        ("DEEPSEEK_TOTAL_TIMEOUT_SECONDS", "nan"),
        ("DEEPSEEK_TOTAL_TIMEOUT_SECONDS", "0"),
    ],
)
def test_invalid_retry_policy(monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    with pytest.raises(DeepSeekConfigurationError):
        SessionExtractionPolicy.from_environment()


def test_ambiguous_short_reply_keeps_both_budgets_unchanged(live_api):
    client, service, script, calls = live_api
    sid = start_complete(live_api)["session_id"]
    url = f"/trip-sessions/{sid}/messages"
    message = "Remove both our airfare budgets."
    script["handler"] = lambda request, context: reply(
        [
            op(f"travelers.{tid}.budget_usd", None, message, "remove")
            for tid in ("traveler_a", "traveler_b")
        ]
    )
    result = client.post(url, json={"message": message}).json()
    assert len(result["pending_questions"]) == 2
    script["handler"] = lambda request, context: reply(
        issues=[
            {
                "field_path": "travelers.traveler_a.budget_usd",
                "reason": "ambiguous",
                "clarification_question": "Is $800 for you, Jamie, or each of you?",
            }
        ]
    )
    result = client.post(url, json={"message": "800"}).json()
    assert len(calls[-1]["conversation_context"]["pending_questions"]) == 2
    assert result["state"] == "collecting"
    assert all(
        t["budget_usd"] is None for t in result["trip_request_draft"]["travelers"]
    )


def test_unsupported_origin_does_not_replace_saved_origin(live_api):
    client, service, script, _ = live_api
    first = start_complete(live_api)
    sid = first["session_id"]
    message = "I am leaving from Chicago and my airfare budget is $700 USD."
    script["handler"] = lambda request, context: reply(
        [
            op("travelers.traveler_a.origin", "Chicago", message),
            op("travelers.traveler_a.budget_usd", 700, message),
        ]
    )
    result = client.post(
        f"/trip-sessions/{sid}/messages", json={"message": message}
    ).json()
    assert result["state"] == "collecting"
    assert result["trip_request_draft"]["travelers"][0]["origin"] == "Boston"
    assert result["trip_request_draft"]["travelers"][0]["budget_usd"] == 700
    assert "Boston or New York" in result["assistant_message"]


def test_missing_year_question_is_preserved_even_with_saved_dates(live_api):
    client, service, script, _ = live_api
    first = start_complete(live_api)
    script["handler"] = lambda request, context: reply(
        issues=[
            {
                "field_path": "start_date",
                "reason": "missing",
                "clarification_question": "What year do you mean?",
            }
        ]
    )
    result = client.post(
        f"/trip-sessions/{first['session_id']}/messages", json={"message": "October 10"}
    ).json()
    assert result["state"] == "collecting"
    assert result["assistant_message"] == "What year do you mean?"
    assert result["trip_request_draft"] == first["trip_request_draft"]


def test_short_year_reply_retains_original_date_question_context(live_api):
    client, service, script, calls = live_api
    sid = start_complete(live_api)["session_id"]
    url = f"/trip-sessions/{sid}/messages"
    script["handler"] = lambda request, context: reply(
        issues=[
            {
                "field_path": "start_date",
                "reason": "ambiguous",
                "clarification_question": "What year do you mean?",
            }
        ]
    )
    question = client.post(url, json={"message": "Change departure to June 11."}).json()
    assert (
        question["pending_questions"][0]["source_message"]
        == "Change departure to June 11."
    )
    script["handler"] = lambda request, context: reply(
        [
            op("start_date", "2099-06-11", "2099"),
        ]
    )
    result = client.post(url, json={"message": "2099"}).json()
    assert result["state"] == "review"
    assert result["trip_request_draft"] == {
        **question["trip_request_draft"],
        "start_date": "2099-06-11",
    }
    assert result["missing_fields"] == []
    assert result["pending_questions"] == []
    assert result["recommendations"] == []
    assert (
        calls[-1]["conversation_context"]["pending_questions"][0]["source_message"]
        == "Change departure to June 11."
    )


def test_exception_during_merge_does_not_partially_commit(live_api):
    from travel_ai.schemas.preference_extraction import PreferenceExtractionResult
    from travel_ai.schemas.sessions import TravelerPreferencesDraft, TripRequestDraft

    client, service, script, _ = live_api
    sid = start_complete(live_api)["session_id"]
    before = snapshot(service, sid)
    # Bypass Pydantic to emulate a faulty custom extractor implementation.
    invalid = TravelerPreferencesDraft.model_construct(
        traveler_id="traveler_a",
        budget_usd=800,
        preferences={"interest_tags": ["invented"]},
    )
    result = PreferenceExtractionResult.model_construct(
        draft=TripRequestDraft.model_construct(
            travelers=[
                invalid,
                TravelerPreferencesDraft(traveler_id="traveler_b"),
            ]
        ),
        status="ready_for_review",
        missing_fields=[],
        unsupported_requests=[],
        acknowledged_unsupported=[],
    )
    service.extractor.close()
    service.extractor = Mock()
    service.extractor.extract.return_value = result
    with pytest.warns(UserWarning):
        response = client.post(
            f"/trip-sessions/{sid}/messages", json={"message": "change"}
        )
    assert response.status_code == 422
    assert snapshot(service, sid) == before


@pytest.mark.parametrize("proposed_date", [None, "2020-06-11", "2099-06-15"])
def test_year_reply_does_not_clear_issue_without_valid_update(live_api, proposed_date):
    client, service, script, _ = live_api
    sid = start_complete(live_api)["session_id"]
    url = f"/trip-sessions/{sid}/messages"
    script["handler"] = lambda request, context: reply(
        issues=[
            {
                "field_path": "start_date",
                "reason": "ambiguous",
                "clarification_question": "What year is your June 11 departure?",
            }
        ]
    )
    question = client.post(url, json={"message": "Change departure to June 11."}).json()
    answer = "2020" if proposed_date == "2020-06-11" else "2099"
    script["handler"] = lambda request, context: reply(
        [] if proposed_date is None else [op("start_date", proposed_date, answer)]
    )
    result = client.post(url, json={"message": answer}).json()
    assert result["state"] == "collecting"
    assert result["trip_request_draft"] == question["trip_request_draft"]
    assert "start_date" in result["missing_fields"]
    assert result["recommendations"] == []


def test_year_reply_with_two_pending_dates_requires_clarification(live_api):
    client, service, script, calls = live_api
    sid = start_complete(live_api)["session_id"]
    url = f"/trip-sessions/{sid}/messages"
    issues = [
        {
            "field_path": field,
            "reason": "ambiguous",
            "clarification_question": f"What year is the {field}?",
        }
        for field in ("start_date", "end_date")
    ]
    script["handler"] = lambda request, context: reply(issues=issues)
    question = client.post(
        url,
        json={
            "message": (
                "Departure June 11 and return June 14; the years are unspecified."
            )
        },
    ).json()
    result = client.post(url, json={"message": "2099 for one of those dates."}).json()
    assert result["state"] == "collecting"
    assert result["trip_request_draft"] == question["trip_request_draft"]
    assert set(result["missing_fields"]) == {"start_date", "end_date"}
    assert len(calls[-1]["conversation_context"]["pending_questions"]) == 2


def test_bare_year_without_pending_question_preserves_reviewed_dates(live_api):
    client, service, script, calls = live_api
    before = start_complete(live_api)
    script["handler"] = lambda request, context: reply()
    result = client.post(
        f"/trip-sessions/{before['session_id']}/messages",
        json={"message": "2099"},
    ).json()
    assert "conversation_context" not in calls[-1]
    assert result["trip_request_draft"] == before["trip_request_draft"]
    assert result["state"] == "review"
    assert result["missing_fields"] == []
    assert result["recommendations"] == []
