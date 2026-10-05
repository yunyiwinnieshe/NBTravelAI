"""Evaluate saved conversations through real normalization and session behavior.

This invokes services directly; Postman remains the HTTP routing walkthrough.
Offline fixtures replace only model HTTP responses, never expected outcomes.
"""

import copy
import json
from collections import Counter
from contextlib import contextmanager
from datetime import UTC, date, datetime
from time import perf_counter
from typing import Any, Literal
from unittest.mock import patch

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from travel_ai.evaluation.transports import CallLimitExceeded
from travel_ai.schemas import trip
from travel_ai.schemas.sessions import (
    CreateTripSessionRequest,
    TripSessionMessageRequest,
)
from travel_ai.services import trip_session_service as sessions
from travel_ai.services.deepseek_preference_extraction import (
    DeepSeekExtractionError,
    DeepSeekResponseError,
)
from travel_ai.services.recommendation_service import RecommendationService


class Expected(BaseModel):
    model_config = ConfigDict(extra="forbid")
    http_status: int
    state: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    missing_any: list[str] = Field(default_factory=list)
    unsupported: bool | None = None
    deferred: bool | None = None
    preserve_except: list[str] | None = None

    @model_validator(mode="after")
    def require_success_state(self):
        if self.http_status == 200 and self.state not in {
            "collecting",
            "review",
            "results",
            "no_match",
        }:
            raise ValueError("successful steps need a valid expected state")
        return self


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    body: dict[str, Any]
    expected: Expected


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    category: str = Field(min_length=1)
    description: str
    label_status: Literal["reviewed", "provisional"] = "reviewed"
    reviewer: str | None = None
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_requests(self):
        CreateTripSessionRequest.model_validate(self.steps[0].body)
        for step in self.steps[1:]:
            TripSessionMessageRequest.model_validate(step.body)
        return self


class Dataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    description: str
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case IDs must be unique")
        return self


def needs_extraction(step: Step) -> bool:
    message = step.body.get("initial_message") or step.body.get("message")
    return bool(message) and not sessions.is_non_trip_control_message(message)


class ReplayTransport(httpx.BaseTransport):
    """Serve independent saved model outputs; never consult expected fields."""

    def __init__(self, bundle: dict, dataset: Dataset):
        self.bundle = bundle
        self.calls = 0
        self.selected = None
        for case in dataset.cases:
            keys = bundle["cases"][case.id]
            if len(keys) != len(case.steps):
                raise ValueError("offline fixture step count differs from dataset")
            for key, step in zip(keys, case.steps, strict=True):
                if needs_extraction(step) != (key is not None):
                    raise ValueError("offline fixtures must match extraction steps")
                if key is not None and key not in bundle["responses"]:
                    raise ValueError("unknown offline response fixture")

    def select(self, case_id: str, step: int):
        self.selected = self.bundle["cases"][case_id][step]

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        payload = json.loads(json.loads(request.content)["messages"][1]["content"])

        def render(value):
            if isinstance(value, dict):
                return {key: render(item) for key, item in value.items()}
            if isinstance(value, list):
                return [render(item) for item in value]
            if value == "$message":
                return payload["user_message"]
            if value == "$pending_notice_id":
                notices = payload["conversation_context"]["unsupported_requests"]
                if len(notices) != 1:
                    raise ValueError("ack fixture requires exactly one pending notice")
                return notices[0]["request_id"]
            return value

        output = render(self.bundle["responses"][self.selected])
        return httpx.Response(
            200,
            json={
                "model": "offline-authored-fixture",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(output),
                        },
                    }
                ],
            },
        )


@contextmanager
def frozen_dates(reference: date):
    """Scope a clock to this single-process evaluator, never a production server."""

    class FrozenDate(date):
        @classmethod
        def today(cls):
            return reference

    with (
        patch.object(sessions, "date", FrozenDate),
        patch.object(trip, "date", FrozenDate),
    ):
        yield


class CountingRecommendations(RecommendationService):
    def __init__(self, reference: date):
        super().__init__(
            clock=lambda: datetime.combine(reference, datetime.min.time(), UTC)
        )
        self.calls = 0

    def get_recommendations(self, request):
        self.calls += 1
        return super().get_recommendations(request)


def normalize_draft(draft: dict | None) -> dict:
    if not draft:
        return {}
    return {**draft, "travelers": {t["traveler_id"]: t for t in draft["travelers"]}}


def field_value(data, path):
    for part in path.split("."):
        if not isinstance(data, dict) or part not in data:
            return "<absent>"
        data = data[part]
    return (
        sorted(data)
        if path.endswith("interest_tags") and isinstance(data, list)
        else data
    )


def omit_paths(data: dict, paths: list[str]) -> dict:
    result = copy.deepcopy(data)
    for path in paths:
        parts = path.split(".")
        parent = result
        for part in parts[:-1]:
            parent = parent.get(part, {})
        parent.pop(parts[-1], None)
    return result


def grade(
    expected: Expected, status: int, body: dict, before: dict | None
) -> list[dict]:
    checks = []

    def check(name, wanted, actual):
        checks.append(
            {
                "name": name,
                "expected": wanted,
                "actual": actual,
                "passed": wanted == actual,
            }
        )

    check("http_status", expected.http_status, status)
    if expected.http_status != 200 or status != 200:
        return checks
    check("state", expected.state, body.get("state"))
    check("assistant_message", True, bool(body.get("assistant_message")))
    draft = body.get("trip_request_draft") or {}
    check(
        "stable_traveler_ids",
        ["traveler_a", "traveler_b"],
        sorted(t["traveler_id"] for t in draft.get("travelers", [])),
    )
    normalized = normalize_draft(draft)
    for path, wanted in expected.fields.items():
        check(
            "field:" + path,
            sorted(wanted) if isinstance(wanted, list) else wanted,
            field_value(normalized, path),
        )
    missing = body.get("missing_fields", [])
    for path in expected.missing:
        check("clarification:" + path, True, path in missing)
    if expected.missing_any:
        check(
            "clarify_ambiguous_target",
            True,
            any(p in missing for p in expected.missing_any),
        )
    notices = body.get("unsupported_requests", [])
    if expected.unsupported is not None:
        check("unsupported_notice", expected.unsupported, bool(notices))
    if expected.deferred is not None:
        check("deferred_notice", expected.deferred, bool(body.get("deferred_requests")))
    check(
        "question_batch_limit",
        True,
        len(body.get("pending_questions", [])) <= (2 if notices else 3),
    )
    check(
        "recommendation_result",
        expected.state == "results",
        bool(body.get("recommendations")),
    )
    if expected.preserve_except is not None:
        check(
            "unrelated_fields_preserved",
            omit_paths(normalize_draft(before), expected.preserve_except),
            omit_paths(normalized, expected.preserve_except),
        )
    return checks


def evaluate(dataset: Dataset, extractor, reference: date, *, repeats=1, replay=None):
    records = []
    exhausted = False
    with frozen_dates(reference):
        for repeat in range(1, repeats + 1):
            for case in dataset.cases:
                recommender = CountingRecommendations(reference)
                service = sessions.TripSessionService(extractor, recommender)
                sid = None
                for index, step in enumerate(case.steps):
                    record = {
                        "case_id": case.id,
                        "step_id": f"{case.id}/{index + 1:02d}",
                        "name": step.name,
                        "category": case.category,
                        "label_status": case.label_status,
                        "reviewer": case.reviewer,
                        "repeat": repeat,
                        "request": step.body,
                        "expected": step.expected.model_dump(exclude_none=True),
                    }
                    if exhausted or (index > 0 and sid is None):
                        record.update(
                            status="skipped",
                            passed=False,
                            checks=[],
                            actual=None,
                            reasons=[
                                "call_limit_exhausted"
                                if exhausted
                                else "session_creation_failed"
                            ],
                        )
                        records.append(record)
                        continue
                    before = (
                        service._get_session(sid).draft.model_dump(mode="json")
                        if sid
                        else None
                    )
                    state_before = service._get_session(sid).state if sid else None
                    calls_before = recommender.calls
                    if replay:
                        replay.select(case.id, index)
                    started = perf_counter()
                    error_type = None
                    try:
                        if index == 0:
                            response = service.create_session(
                                step.body.get("initial_message")
                            )
                        elif step.body.get("action") == "confirm":
                            response = service.confirm_session(sid)
                        elif step.body.get("action") == "continue_without_unsupported":
                            response = service.defer_unsupported(sid)
                        else:
                            response = service.add_message(sid, step.body["message"])
                        status, body = 200, response.model_dump(mode="json")
                        sid = response.session_id
                    except CallLimitExceeded:
                        exhausted = True
                        error_type = "call_limit_exhausted"
                        status, body = 503, {"error": error_type}
                    except DeepSeekExtractionError as error:
                        error_type = type(error).__name__
                        status = (
                            502 if isinstance(error, DeepSeekResponseError) else 503
                        )
                        body = {"error": error_type}
                    except ValueError as error:
                        status, body = 422, {"error": type(error).__name__}
                    except Exception as error:
                        error_type = type(error).__name__
                        status, body = 500, {"error": error_type}
                    checks = grade(step.expected, status, body, before)
                    calls_made = recommender.calls - calls_before
                    allowed_confirmation = (
                        step.body.get("action") == "confirm"
                        and state_before == "review"
                    )
                    gate_passed = (
                        calls_made <= 1 if allowed_confirmation else calls_made == 0
                    )
                    checks.append(
                        {
                            "name": "confirmation_gate",
                            "expected": True,
                            "actual": gate_passed,
                            "passed": gate_passed,
                        }
                    )
                    if status != 200 and sid:
                        after = service._get_session(sid).draft.model_dump(mode="json")
                        checks.append(
                            {
                                "name": "failed_turn_preserves_draft",
                                "expected": before,
                                "actual": after,
                                "passed": before == after,
                            }
                        )
                    reasons = [c["name"] for c in checks if not c["passed"]]
                    if error_type:
                        reasons.append(error_type)
                    record.update(
                        status="failed" if reasons else "passed",
                        passed=not reasons,
                        actual={"http_status": status, "body": body},
                        checks=checks,
                        reasons=reasons,
                        latency_ms=round((perf_counter() - started) * 1000, 2),
                    )
                    records.append(record)
                    print(
                        f"{record['status'].upper()} r{repeat} "
                        f"{record['step_id']} {reasons}",
                        flush=True,
                    )
    return records


def summarize(records):
    groups = {}
    for record in records:
        groups.setdefault((record["case_id"], record["repeat"]), []).append(record)
    return {
        "case_runs": len(groups),
        "case_runs_passed": sum(
            all(r["passed"] for r in group) for group in groups.values()
        ),
        "steps": len(records),
        "steps_passed": sum(r["passed"] for r in records),
        "steps_skipped": sum(r["status"] == "skipped" for r in records),
        "categories": {
            category: {
                "passed": sum(
                    r["passed"] for r in records if r["category"] == category
                ),
                "total": sum(r["category"] == category for r in records),
            }
            for category in sorted({r["category"] for r in records})
        },
        "failure_reasons": dict(
            Counter(reason for r in records for reason in r["reasons"])
        ),
    }
