"""Offline conversation, recovery, and evaluation-grader tests."""

import copy
import json
from datetime import date
from pathlib import Path

import httpx
import pytest

from travel_ai.schemas.sessions import TripRequestDraft
from travel_ai.scripts.evaluate_extraction import (
    compare_reports,
    evaluate,
    merge_for_evaluation,
    sparse_values,
    summarize,
)
from travel_ai.services.deepseek_preference_extraction import (
    DeepSeekPreferenceExtractor,
    DeepSeekSettings,
    DeepSeekUnavailableError,
)

DATASET = json.loads(
    (
        Path(__file__).parents[1] / "evals/preference_extraction/cases.v1.json"
    ).read_text()
)


def envelope(operations):
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {
                            "operations": operations,
                            "missing_fields": [],
                            "unsupported_requests": [],
                        }
                    )
                },
            }
        ]
    }


def operation(path, value, evidence, action="set"):
    return dict(op=action, field_path=path, value=value, evidence=evidence)


def test_five_turn_conversation_preserves_state_and_companion():
    scenario = next(s for s in DATASET["scenarios"] if s["id"] == "conversation")
    dataset = {**DATASET, "scenarios": [scenario]}
    calls = []
    responses = [
        [("display_name", "Alex", "set"), ("budget_usd", 800, "set")],
        [("preferences.interest_tags", ["museums"], "set")],
        [("preferences.interest_tags", ["outdoor_activities"], "add")],
        [("preferences.interest_tags", ["museums"], "remove")],
        [("budget_usd", 600, "set")],
    ]

    def handler(request):
        context = json.loads(json.loads(request.content)["messages"][1]["content"])
        index = len(calls)
        calls.append(context)
        return httpx.Response(
            200,
            json=envelope(
                [
                    operation(
                        "travelers.traveler_a." + path,
                        value,
                        context["user_message"],
                        action,
                    )
                    for path, value, action in responses[index]
                ]
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DeepSeekPreferenceExtractor(
            DeepSeekSettings(api_key="fake"),
            http_client=client,
            today=lambda: date(2026, 9, 27),
        ) as extractor:
            records = evaluate(extractor, dataset)
    assert all(r["passed"] for r in records)
    assert len(calls) == 5
    final = records[-1]["draft_after"]["travelers"]
    assert final[0]["display_name"] == "Alex"
    assert final[0]["budget_usd"] == 600
    assert final[0]["preferences"]["interest_tags"] == ["outdoor_activities"]
    assert final[1] == scenario["initial_draft"]["travelers"][1]


def test_timeout_then_success_preserves_input_and_all_unmentioned_values():
    current = TripRequestDraft.model_validate(DATASET["initial_draft"])
    before = current.model_dump()
    calls = 0
    message = "My round-trip airfare budget is $600 USD."

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("mock timeout", request=request)
        return httpx.Response(
            200,
            json=envelope(
                [
                    operation("travelers.traveler_a.budget_usd", 600, message),
                ]
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DeepSeekPreferenceExtractor(
            DeepSeekSettings(api_key="fake"),
            http_client=client,
            today=lambda: date(2026, 9, 27),
        ) as extractor:
            with pytest.raises(DeepSeekUnavailableError):
                extractor.extract(message, current)
            assert current.model_dump() == before
            result = extractor.extract(message, current)
    merged = merge_for_evaluation(current, sparse_values(result.draft))
    expected = current.model_copy(deep=True)
    expected.travelers[0].budget_usd = 600
    assert merged == expected
    assert current.model_dump() == before
    assert calls == 2


def test_grader_catches_extra_edit_even_if_expected_budget_is_correct():
    scenario = DATASET["scenarios"][0]

    def handler(_):
        return httpx.Response(
            200,
            json=envelope(
                [
                    operation("travelers.traveler_a.budget_usd", 800, "airfare"),
                    operation("travelers.traveler_b.budget_usd", 800, "airfare"),
                ]
            ),
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with DeepSeekPreferenceExtractor(
            DeepSeekSettings(api_key="fake"),
            http_client=client,
            today=lambda: date(2026, 9, 27),
        ) as extractor:
            records = evaluate(extractor, {**DATASET, "scenarios": [scenario]})
    assert not records[0]["passed"]
    assert not records[0]["checks"]["exact_updates"]
    assert not records[0]["checks"]["cumulative_state"]


def report_for(passes):
    records = [
        dict(
            case_id=str(index),
            repeat=1,
            passed=passed,
            category="test",
            latency_ms=100,
            checks={"exact_updates": passed},
        )
        for index, passed in enumerate(passes)
    ]
    return dict(
        metadata=dict(dataset_sha256="dataset", evaluator_sha256="grader", repeats=1),
        records=records,
        summary=summarize(records),
    )


def test_comparison_identifies_regression_even_when_total_score_is_unchanged():
    comparison = compare_reports(report_for([True, False]), report_for([False, True]))
    assert comparison["pass_rate_change_percentage_points"] == 0
    assert comparison["regressed"] == [["0", 1]]
    assert comparison["improved"] == [["1", 1]]


@pytest.mark.parametrize("key", ["dataset_sha256", "evaluator_sha256", "repeats"])
def test_comparison_rejects_incomparable_runs(key):
    before = report_for([True])
    after = copy.deepcopy(before)
    after["metadata"][key] = "changed"
    with pytest.raises(ValueError, match="different"):
        compare_reports(before, after)


def test_repeated_case_score_requires_every_attempt_to_pass():
    records = report_for([True, False])["records"]
    records[1]["case_id"] = records[0]["case_id"]
    records[1]["repeat"] = 2
    summary = summarize(records)
    assert summary["pass_rate"] == 0.5
    assert summary["cases_passing_all_repeats"] == 0
    assert summary["unique_cases"] == 1
