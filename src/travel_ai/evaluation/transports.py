"""Enforce live-call limits at the actual HTTP transport boundary."""

from threading import Lock

import httpx

from travel_ai.services.deepseek_preference_extraction import DeepSeekUnavailableError


class CallLimitExceeded(DeepSeekUnavailableError):
    """No additional provider request was sent."""


class LimitedTransport(httpx.BaseTransport):
    """Count attempts, including unsuccessful requests, before sending anything."""

    def __init__(self, transport: httpx.BaseTransport, limit: int):
        if limit < 1:
            raise ValueError("live call limit must be positive")
        self.transport = transport
        self.limit = limit
        self.calls = 0
        self._lock = Lock()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            if self.calls >= self.limit:
                raise CallLimitExceeded("Evaluation live-call limit reached")
            self.calls += 1
        return self.transport.handle_request(request)

    def close(self) -> None:
        self.transport.close()
