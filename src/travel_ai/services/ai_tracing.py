"""Bounded, process-local AI call tracing without raw traveler data."""

import hashlib
import json
import threading
from collections import deque
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

_events: deque[dict[str, Any]] = deque(maxlen=500)
_lock = threading.Lock()


def fingerprint(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()[:16]


def record_call(
    *,
    model: str,
    operation: str,
    input_fingerprint: str,
    output_fingerprint: str | None,
    started: float,
    status: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    estimated_cost_usd: float | None = None,
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
    }
    with _lock:
        _events.append(event)


def recent_calls() -> list[dict[str, Any]]:
    with _lock:
        return list(reversed(_events))
