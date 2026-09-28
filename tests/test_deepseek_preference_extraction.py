"""Offline contract tests: every provider request uses httpx.MockTransport."""

import json
from datetime import date

import httpx
import pytest

from travel_ai.schemas.sessions import TravelerPreferencesDraft, TripRequestDraft
from travel_ai.schemas.trip import TripPreferences
from travel_ai.services.deepseek_preference_extraction import (
    DeepSeekConfigurationError,
    DeepSeekPreferenceExtractor,
    DeepSeekResponseError,
    DeepSeekSettings,
    DeepSeekUnavailableError,
)

TODAY = date(2026, 9, 27)
MESSAGE = "I have $800 for airfare, also beaches; no museums or temperature preference."


@pytest.fixture
def draft():
    return TripRequestDraft(
        travelers=[
            TravelerPreferencesDraft(
                traveler_id="traveler_a",
                display_name="Winnie",
                origin="Boston",
                origin_id="boston_ma",
                budget_usd=1000,
                max_travel_time_hours=8,
                preferences=TripPreferences(
                    interest_tags=["museums"],
                    temperature_range={"minimum_celsius": 15, "maximum_celsius": 23},
                ),
            ),
            TravelerPreferencesDraft(
                traveler_id="traveler_b",
                display_name="Ivy",
                origin="New York",
                budget_usd=900,
                max_travel_time_hours=7,
            ),
        ],
        start_date="2026-10-09",
        end_date="2026-10-13",
    )


def op(path, value=None, action="set", evidence="airfare"):
    return {"op": action, "field_path": path, "value": value, "evidence": evidence}


def body(operations=None, missing_fields=None, unsupported_requests=None):
    return {
        "operations": operations or [],
        "missing_fields": missing_fields or [],
        "unsupported_requests": unsupported_requests or [],
    }


def envelope(content, finish="stop"):
    return {"choices": [{"finish_reason": finish, "message": {"content": content}}]}


def run(draft, reply, message=MESSAGE, inspect=None):
    def handler(request):
        if inspect:
            inspect(request)
        return httpx.Response(200, json=envelope(json.dumps(reply)))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DeepSeekPreferenceExtractor(
            DeepSeekSettings(api_key="test-secret"),
            http_client=client,
            today=lambda: TODAY,
        ) as extractor:
            return extractor.extract(message, draft)


def test_sparse_budget_preserves_ids_and_input(draft):
    before = draft.model_dump()
    result = run(draft, body([op("travelers.traveler_a.budget_usd", 800)]))
    assert result.draft.model_dump(exclude_unset=True) == {
        "travelers": [
            {"traveler_id": "traveler_a", "budget_usd": 800},
            {"traveler_id": "traveler_b"},
        ]
    }
    assert draft.model_dump() == before
    assert result.status == "ready_for_review"


def test_empty_message_result_is_noop_not_a_copy_of_draft(draft):
    result = run(draft, body(), message="Hello")
    assert result.draft.model_dump(exclude_unset=True) == {
        "travelers": [{"traveler_id": "traveler_a"}, {"traveler_id": "traveler_b"}]
    }


@pytest.mark.parametrize(
    ("action", "value", "expected"),
    [
        ("add", ["beach", "beach"], ["museums", "beach"]),
        ("set", ["beach"], ["beach"]),
        ("remove", ["museums"], []),
        ("remove", None, []),
        ("remove", ["nature"], ["museums"]),
    ],
)
def test_interest_operations(draft, action, value, expected):
    result = run(
        draft,
        body(
            [
                op("travelers.traveler_a.preferences.interest_tags", value, action),
            ]
        ),
    )
    traveler = result.draft.travelers[0]
    assert [t.value for t in traveler.preferences.interest_tags] == expected
    assert "temperature_range" not in traveler.preferences.model_fields_set


def test_operations_apply_in_order_and_clear_is_explicit(draft):
    result = run(
        draft,
        body(
            [
                op("travelers.traveler_a.preferences.interest_tags", ["beach"], "add"),
                op(
                    "travelers.traveler_a.preferences.interest_tags",
                    ["museums"],
                    "remove",
                ),
                op(
                    "travelers.traveler_a.preferences.temperature_range", None, "remove"
                ),
            ]
        ),
    )
    assert result.draft.travelers[0].preferences.model_dump(exclude_unset=True) == {
        "interest_tags": ["beach"],
        "temperature_range": None,
    }


@pytest.mark.parametrize(
    ("path", "value", "action"),
    [
        ("budget_usd", -1, "set"),
        ("budget_usd", "800", "set"),
        ("budget_usd", True, "set"),
        ("budget_usd", 100001, "set"),
        ("budget_usd", float("nan"), "set"),
        ("budget_usd", 500, "add"),
        ("budget_usd", None, "set"),
        ("max_travel_time_hours", 49, "set"),
        ("preferences.interest_tags", ["romantic"], "set"),
        ("preferences.interest_tags", ["romantic"], "remove"),
        (
            "preferences.temperature_range",
            {
                "minimum_celsius": 30,
                "maximum_celsius": 20,
            },
            "set",
        ),
    ],
)
def test_bad_field_is_omitted_but_valid_sibling_survives(draft, path, value, action):
    path = "travelers.traveler_a." + path
    result = run(
        draft,
        body(
            [
                op(path, value, action),
                op("travelers.traveler_b.budget_usd", 700),
            ]
        ),
    )
    assert result.draft.travelers[0].model_dump(exclude_unset=True) == {
        "traveler_id": "traveler_a",
    }
    assert result.draft.travelers[1].budget_usd == 700
    assert result.missing_fields[0].field_path == path
    assert result.missing_fields[0].reason == "invalid"


@pytest.mark.parametrize(
    "path",
    [
        "travelers.evil.budget_usd",
        "travelers.traveler_a.traveler_id",
        "travelers.traveler_a.origin_id",
        "destination",
        "travelers[0].origin",
    ],
)
def test_unknown_update_paths_reject_whole_response(draft, path):
    with pytest.raises(DeepSeekResponseError):
        run(draft, body([op(path, "invented")]))


@pytest.mark.parametrize(
    "path",
    [
        "hotel",
        "travelers.traveler_c.origin",
        "travelers[0].origin",
        "travelers.traveler_a.preferences.happiness",
        "travelers",
    ],
)
def test_issue_paths_are_validated(draft, path):
    with pytest.raises(DeepSeekResponseError):
        run(
            draft,
            body(
                missing_fields=[
                    {
                        "field_path": path,
                        "reason": "ambiguous",
                        "clarification_question": "Which one?",
                    }
                ]
            ),
        )


def test_issue_wins_over_conflicting_update(draft):
    path = "travelers.traveler_a.preferences.temperature_range"
    result = run(
        draft,
        body(
            [
                op(path, {"minimum_celsius": 15, "maximum_celsius": 23}),
                op("travelers.traveler_a.budget_usd", 800),
            ],
            [
                {
                    "field_path": path + ".minimum_celsius",
                    "reason": "ambiguous",
                    "clarification_question": "How cool?",
                }
            ],
        ),
    )
    assert "preferences" not in result.draft.travelers[0].model_fields_set
    assert result.draft.travelers[0].budget_usd == 800


def test_unsupported_notice_needs_no_field_and_keeps_good_edits(draft):
    result = run(
        draft,
        body(
            [op("travelers.traveler_a.budget_usd", 800)],
            unsupported_requests=[
                {
                    "user_text": "hotel pool",
                    "explanation": "Hotels are not supported.",
                }
            ],
        ),
        message="I have $800 for airfare and want a hotel pool",
    )
    assert result.draft.travelers[0].budget_usd == 800
    assert result.status == "needs_clarification"
    assert result.missing_fields == []
    assert result.unsupported_requests[0].user_text == "hotel pool"


@pytest.mark.parametrize(
    "reply",
    [
        body([op("start_date", "2026-10-01", evidence="not in message")]),
        body(unsupported_requests=[{"user_text": "unmentioned", "explanation": "No"}]),
        {"operations": [], "missing_fields": []},
        {**body(), "draft": {}},
        body([{"op": "invent", "field_path": "start_date", "evidence": "I"}]),
    ],
)
def test_unsafe_structure_or_missing_evidence_fails(draft, reply):
    with pytest.raises(DeepSeekResponseError):
        run(draft, reply)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-01-01", "2026-01-05"),
        ("2026-10-15", "2026-10-13"),
        ("2026-10-09", "2026-10-25"),
        ("2026-10-09", "2026-10-09"),
        ("2026-99-01", "not a date"),
    ],
)
def test_invalid_dates_do_not_drop_valid_budget(draft, start, end):
    result = run(
        draft,
        body(
            [
                op("start_date", start),
                op("end_date", end),
                op("travelers.traveler_a.budget_usd", 800),
            ]
        ),
    )
    assert result.status == "needs_clarification"
    assert result.draft.travelers[0].budget_usd == 800
    assert result.missing_fields


def test_date_edit_is_checked_against_existing_other_date(draft):
    result = run(draft, body([op("start_date", "2026-10-14")]))
    assert "start_date" not in result.draft.model_fields_set
    assert result.missing_fields[0].reason == "invalid"


def test_missing_fields_are_computed_without_filling_draft():
    current = TripRequestDraft(
        travelers=[
            TravelerPreferencesDraft(traveler_id="traveler_a"),
            TravelerPreferencesDraft(traveler_id="traveler_b"),
        ]
    )
    result = run(current, body([op("travelers.traveler_a.budget_usd", 800)]))
    paths = {i.field_path for i in result.missing_fields}
    assert "start_date" in paths
    assert "travelers.traveler_a.origin" in paths
    assert "travelers.traveler_a.budget_usd" not in paths
    assert len(paths) == 7


def test_request_contract_and_reference_clock(draft):
    def inspect(request):
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        assert request.extensions["timeout"]["read"] == 20
        sent = json.loads(request.content)
        assert sent["model"] == "deepseek-flash"
        assert sent["thinking"] == {"type": "disabled"}
        assert sent["response_format"] == {"type": "json_object"}
        assert sent["stream"] is False
        data = json.loads(sent["messages"][1]["content"])
        assert data["reference_date"] == "2026-09-27"
        assert data["next_weekdays"] == {
            "monday": "2026-09-28",
            "tuesday": "2026-09-29",
            "wednesday": "2026-09-30",
            "thursday": "2026-10-01",
            "friday": "2026-10-02",
            "saturday": "2026-10-03",
            "sunday": "2026-10-04",
        }
        assert data["timezone"] == "America/Los_Angeles"
        assert data["user_message"] == MESSAGE
        assert data["current_draft"] == draft.model_dump(mode="json")

    run(draft, body(), inspect=inspect)


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, DeepSeekConfigurationError),
        (403, DeepSeekConfigurationError),
        (400, DeepSeekConfigurationError),
        (302, DeepSeekConfigurationError),
        (429, DeepSeekUnavailableError),
        (503, DeepSeekUnavailableError),
    ],
)
def test_http_errors_are_sanitized_and_never_retried(draft, status, error_type):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(status, text="secret provider response")

    before = draft.model_dump()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        extractor = DeepSeekPreferenceExtractor(
            DeepSeekSettings(api_key="secret"),
            http_client=client,
        )
        with pytest.raises(error_type) as caught:
            extractor.extract(MESSAGE, draft)
        assert "secret" not in str(caught.value)
        assert len(requests) == 1
    assert draft.model_dump() == before


@pytest.mark.parametrize("exception", [httpx.ReadTimeout, httpx.ConnectError])
def test_transport_failure_is_retryable(draft, exception):
    def handler(request):
        raise exception("sensitive details", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        extractor = DeepSeekPreferenceExtractor(
            DeepSeekSettings(api_key="secret"),
            http_client=client,
        )
        with pytest.raises(DeepSeekUnavailableError) as caught:
            extractor.extract(MESSAGE, draft)
        assert caught.value.retryable
        assert "sensitive" not in str(caught.value)


@pytest.mark.parametrize(
    "reply",
    [
        {},
        {"choices": []},
        {"choices": None},
        envelope("{}", "length"),
        envelope("{}", "content_filter"),
        envelope("not json"),
        envelope(""),
        envelope(None),
        envelope("[]"),
        envelope("```json\n{}\n```"),
    ],
)
def test_malformed_provider_envelopes_are_controlled(draft, reply):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=reply),
        )
    ) as client:
        extractor = DeepSeekPreferenceExtractor(
            DeepSeekSettings(api_key="secret"),
            http_client=client,
        )
        with pytest.raises(DeepSeekResponseError):
            extractor.extract(MESSAGE, draft)


def test_environment_settings(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "private-key")
    monkeypatch.setenv("DEEPSEEK_MODEL", "configured-model")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT_SECONDS", "12")
    settings = DeepSeekSettings.from_environment()
    assert settings.api_key == "private-key"
    assert settings.model == "configured-model"
    assert settings.timeout_seconds == 12
    assert "private-key" not in repr(settings)


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf", "wrong"])
def test_invalid_timeout_configuration(monkeypatch, timeout):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT_SECONDS", timeout)
    with pytest.raises(DeepSeekConfigurationError):
        DeepSeekSettings.from_environment()


def test_missing_key_fails_before_network(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(DeepSeekConfigurationError, match="DEEPSEEK_API_KEY"):
        DeepSeekPreferenceExtractor()


def test_bad_input_rejected_before_network(draft):
    def unexpected(_):
        pytest.fail("must not call provider")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        extractor = DeepSeekPreferenceExtractor(
            DeepSeekSettings(api_key="secret"),
            http_client=client,
        )
        for message in (" ", "x" * 10001):
            with pytest.raises(ValueError):
                extractor.extract(message, draft)
        for travelers in ([], [draft.travelers[0]] * 2):
            with pytest.raises(ValueError):
                extractor.extract("Hello", TripRequestDraft(travelers=travelers))


def test_injected_client_remains_open(draft):
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json=envelope(json.dumps(body())))
        ),
    ) as client:
        with DeepSeekPreferenceExtractor(
            DeepSeekSettings(api_key="secret"),
            http_client=client,
        ) as extractor:
            extractor.extract(MESSAGE, draft)
        assert not client.is_closed


def test_remove_requires_explicit_value_to_prevent_accidental_clear(draft):
    with pytest.raises(DeepSeekResponseError):
        run(
            draft,
            body(
                [
                    {
                        "op": "remove",
                        "field_path": "travelers.traveler_a.budget_usd",
                        "evidence": "I",
                    }
                ]
            ),
        )


def test_noop_cannot_claim_stale_dates_are_ready(draft):
    draft.start_date = date(2026, 1, 1)
    draft.end_date = date(2026, 1, 5)
    result = run(draft, body())
    assert result.status == "needs_clarification"
    assert result.missing_fields[0].field_path == "start_date"
    assert "start_date" not in result.draft.model_fields_set


@pytest.mark.parametrize(
    ("today", "weekday", "expected_date"),
    [
        (date(2026, 9, 28), "monday", "2026-10-05"),
        (date(2026, 9, 29), "tuesday", "2026-10-06"),
        (date(2026, 9, 30), "wednesday", "2026-10-07"),
        (date(2026, 10, 1), "thursday", "2026-10-08"),
        (date(2026, 10, 2), "friday", "2026-10-09"),
        (date(2026, 10, 3), "saturday", "2026-10-10"),
        (date(2026, 10, 4), "sunday", "2026-10-11"),
        (date(2026, 12, 31), "friday", "2027-01-01"),
    ],
)
def test_relative_date_context_handles_every_weekday_and_year_boundary(
    draft,
    today,
    weekday,
    expected_date,
):
    def handler(request):
        payload = json.loads(request.content)
        context = json.loads(payload["messages"][1]["content"])
        assert context["reference_date"] == today.isoformat()
        assert context["next_weekdays"][weekday] == expected_date
        return httpx.Response(200, json=envelope(json.dumps(body())))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DeepSeekPreferenceExtractor(
            DeepSeekSettings(api_key="secret"),
            http_client=client,
            today=lambda: today,
        ) as extractor:
            extractor.extract(f"Next {weekday}", draft)


def test_invalid_field_discards_earlier_and_later_edits_to_same_field(draft):
    result = run(
        draft,
        body(
            [
                op("travelers.traveler_a.budget_usd", 800),
                op("travelers.traveler_a.budget_usd", -1),
                op("travelers.traveler_a.budget_usd", 600),
                op("travelers.traveler_b.budget_usd", 700),
            ]
        ),
    )
    assert "budget_usd" not in result.draft.travelers[0].model_fields_set
    assert result.draft.travelers[1].budget_usd == 700


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (
            "preferences.interest_tags",
            ["food", "nightlife", "outdoor_activities", "nature"],
        ),
        (
            "preferences.temperature_range",
            {"minimum_celsius": 20, "maximum_celsius": 30},
        ),
    ],
)
def test_normalized_synonyms_and_temperature_values_pass_validation(draft, path, value):
    message = (
        "I like great restaurants, clubbing, hiking, "
        "parks and scenery, and warm weather"
    )
    result = run(
        draft,
        body(
            [
                op("travelers.traveler_a." + path, value, evidence=message),
            ]
        ),
        message=message,
    )
    preferences = result.draft.travelers[0].preferences.model_dump(mode="json")
    assert preferences[path.split(".")[-1]] == value


def test_live_regression_singular_budget_must_not_leak_to_companion(draft):
    message = "I have an $800 USD round-trip airfare budget."
    with pytest.raises(DeepSeekResponseError, match="speaker-only"):
        run(
            draft,
            body(
                [
                    op("travelers.traveler_a.budget_usd", 800, evidence=message),
                    op("travelers.traveler_b.budget_usd", 800, evidence=message),
                ]
            ),
            message=message,
        )


@pytest.mark.parametrize(
    "message",
    [
        "I and my companion each have $800 for airfare.",
        "I and Ivy both have $800 for airfare.",
        "We each have $800 for airfare.",
    ],
)
def test_explicit_shared_budget_can_update_both(draft, message):
    result = run(
        draft,
        body(
            [
                op("travelers.traveler_a.budget_usd", 800, evidence=message),
                op("travelers.traveler_b.budget_usd", 800, evidence=message),
            ]
        ),
        message=message,
    )
    assert [t.budget_usd for t in result.draft.travelers] == [800, 800]


@pytest.mark.parametrize(
    ("message", "traveler_id"),
    [
        ("Winnie's airfare budget is $800 USD.", "traveler_a"),
        ("WINNIE wants an $800 USD airfare budget.", "traveler_a"),
        ("Ivy's airfare budget is $800 USD.", "traveler_b"),
    ],
)
def test_named_traveler_updates_preserve_identity(draft, message, traveler_id):
    before = draft.model_dump()
    result = run(
        draft,
        body(
            [
                op(f"travelers.{traveler_id}.budget_usd", 800, evidence=message),
            ]
        ),
        message=message,
    )
    for traveler in result.draft.travelers:
        expected = {"traveler_id": traveler.traveler_id}
        if traveler.traveler_id == traveler_id:
            expected["budget_usd"] = 800
        assert traveler.model_dump(exclude_unset=True) == expected
    assert draft.model_dump() == before


def test_named_reference_uses_current_name_and_not_list_position(draft):
    draft.travelers[0].display_name = "Alex"
    draft.travelers.reverse()
    message = "Alex's airfare budget is $800 USD."

    def inspect(request):
        context = json.loads(json.loads(request.content)["messages"][1]["content"])
        assert context["current_draft"]["travelers"][1]["display_name"] == "Alex"
        assert context["current_draft"]["travelers"][1]["traveler_id"] == "traveler_a"

    result = run(
        draft,
        body(
            [
                op("travelers.traveler_a.budget_usd", 800, evidence=message),
            ]
        ),
        message=message,
        inspect=inspect,
    )
    assert result.draft.travelers[1].traveler_id == "traveler_a"
    assert result.draft.travelers[1].budget_usd == 800
    assert "budget_usd" not in result.draft.travelers[0].model_fields_set


def test_duplicate_name_clarification_leaves_both_travelers_unchanged(draft):
    for traveler in draft.travelers:
        traveler.display_name = "Alex"
    result = run(
        draft,
        body(
            missing_fields=[
                {
                    "field_path": f"travelers.{tid}.budget_usd",
                    "reason": "ambiguous",
                    "clarification_question": "Does Alex mean you or your companion?",
                }
                for tid in ("traveler_a", "traveler_b")
            ]
        ),
        message="Alex's airfare budget is $800 USD.",
    )
    assert result.status == "needs_clarification"
    assert all(t.model_fields_set == {"traveler_id"} for t in result.draft.travelers)
    assert len(result.missing_fields) == 2
