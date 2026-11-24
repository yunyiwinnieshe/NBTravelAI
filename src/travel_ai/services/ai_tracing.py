"""Bounded, process-local AI call tracing without raw traveler data."""

import hashlib
import json
import threading
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

_events: deque[dict[str, Any]] = deque(maxlen=500)
_stages: deque[dict[str, Any]] = deque(maxlen=2000)
_lock = threading.Lock()
_trace_id: ContextVar[str | None] = ContextVar("trace_id", default=None)

# Stage metadata is deliberately limited to known, non-personal fields.
_STAGE_FIELDS = {
    "provider",
    "model",
    "version",
    "cache",
    "retry_attempt",
    "validation",
    "candidate_count",
    "eligible_count",
    "rejected_count",
    "result_count",
    "response_status",
    "http_status",
    "error_type",
    "prompt_tokens",
    "completion_tokens",
    "estimated_cost_usd",
    "cost_basis",
}


def begin_trace(trace_id: str):
    """Bind one server-generated ID to this request and its sync dependencies."""
    return _trace_id.set(trace_id)


def end_trace(token: Any) -> None:
    _trace_id.reset(token)


def current_trace_id() -> str | None:
    return _trace_id.get()


def record_stage(name: str, started: float, status: str = "ok", **fields: Any) -> None:
    trace_id = current_trace_id()
    if trace_id is None:
        return
    event = {
        "trace_id": trace_id,
        "at": datetime.now(UTC).isoformat(),
        "stage": name,
        "status": status,
        "latency_ms": round((perf_counter() - started) * 1000, 2),
    }
    event.update({key: value for key, value in fields.items() if key in _STAGE_FIELDS})
    with _lock:
        _stages.append(event)


def record_event(name: str, **fields: Any) -> None:
    """Record an instantaneous decision such as a cache hit or miss."""
    record_stage(name, perf_counter(), **fields)


@contextmanager
def stage(name: str, **fields: Any):
    started = perf_counter()
    try:
        yield fields
    except Exception as error:
        fields["error_type"] = type(error).__name__
        if fields.get("validation") == "passed":
            fields["validation"] = "failed"
        record_stage(name, started, "error", **fields)
        raise
    else:
        record_stage(name, started, **fields)


def recent_traces() -> list[dict[str, Any]]:
    with _lock:
        events = list(_stages)
    traces: dict[str, dict[str, Any]] = {}
    for event in events:
        trace = traces.setdefault(
            event["trace_id"],
            {"trace_id": event["trace_id"], "at": event["at"], "stages": []},
        )
        trace["stages"].append(event)
    for trace in traces.values():
        calls = [
            event
            for event in trace["stages"]
            if event["stage"] == "extraction_provider"
        ]
        if calls:
            priced = [
                event["estimated_cost_usd"]
                for event in calls
                if event.get("estimated_cost_usd") is not None
            ]
            trace["estimated_known_cost_usd"] = (
                round(sum(priced), 8) if priced else None
            )
            trace["unpriced_attempts"] = len(calls) - len(priced)
    return list(reversed(list(traces.values())))


def get_trace(trace_id: str) -> dict[str, Any] | None:
    return next(
        (trace for trace in recent_traces() if trace["trace_id"] == trace_id), None
    )


def fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def record_call(
    *,
    model: str,
    reported_version: str | None = None,
    operation: str,
    input_fingerprint: str,
    output_fingerprint: str | None,
    started: float,
    status: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    estimated_cost_usd: float | None = None,
    cost_basis: str | None = None,
    cache: str | None = None,
    validation_outcome: str = "not_run",
) -> None:
    event = {
        "at": datetime.now(UTC).isoformat(),
        "model": model,
        "operation": operation,
        "input_fingerprint": input_fingerprint,
        "output_fingerprint": output_fingerprint,
        "latency_ms": round((perf_counter() - started) * 1000, 2),
        "status": status,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "cost_basis": cost_basis,
        "validation_outcome": validation_outcome,
        "trace_id": current_trace_id(),
    }
    if cache is not None:
        event["cache"] = cache
    if reported_version is not None:
        event["reported_version"] = reported_version
    with _lock:
        _events.append(event)
    fields = {
        "provider": "deepseek",
        "model": model,
        "validation": validation_outcome,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "estimated_cost_usd": estimated_cost_usd,
        "cost_basis": cost_basis,
    }
    if cache is not None:
        fields["cache"] = cache
    if reported_version is not None:
        fields["version"] = reported_version
    record_stage("extraction_provider", started, status, **fields)


def recent_calls() -> list[dict[str, Any]]:
    with _lock:
        return list(reversed(_events))
