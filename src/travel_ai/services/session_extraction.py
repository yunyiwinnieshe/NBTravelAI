"""Bounded retries and wall-clock isolation for live session extraction."""

import math
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass
from threading import BoundedSemaphore
from time import monotonic, sleep

from travel_ai.schemas.preference_extraction import PreferenceExtractionResult
from travel_ai.schemas.sessions import ExtractionContext, TripRequestDraft
from travel_ai.services.deepseek_preference_extraction import (
    DeepSeekConfigurationError,
    DeepSeekUnavailableError,
)
from travel_ai.services.preference_extraction import PreferenceExtractor


@dataclass(frozen=True)
class SessionExtractionPolicy:
    max_retries: int = 1
    total_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not 0 <= self.max_retries <= 2:
            raise DeepSeekConfigurationError("DEEPSEEK_MAX_RETRIES must be 0, 1, or 2")
        if (
            not math.isfinite(self.total_timeout_seconds)
            or not 0 < self.total_timeout_seconds <= 120
        ):
            raise DeepSeekConfigurationError(
                "DEEPSEEK_TOTAL_TIMEOUT_SECONDS must be in (0, 120]"
            )

    @classmethod
    def from_environment(cls) -> "SessionExtractionPolicy":
        try:
            return cls(
                max_retries=int(os.getenv("DEEPSEEK_MAX_RETRIES", "1")),
                total_timeout_seconds=float(
                    os.getenv("DEEPSEEK_TOTAL_TIMEOUT_SECONDS", "30")
                ),
            )
        except ValueError:
            raise DeepSeekConfigurationError(
                "Invalid DeepSeek retry/timeout settings"
            ) from None


class SessionPreferenceExtractor(PreferenceExtractor):
    """Run an isolated snapshot with a hard caller deadline and bounded workers.

    A synchronous HTTP call cannot be forcibly cancelled. After the deadline its
    result is discarded, with no reference to saved session state. At most four
    calls can remain in flight; new calls fail fast instead of queuing indefinitely.
    The underlying adapter's I/O timeout eventually releases timed-out workers.
    """

    def __init__(
        self, extractor: PreferenceExtractor, policy: SessionExtractionPolicy
    ) -> None:
        self._extractor = extractor
        self._policy = policy
        self._pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="extraction")
        self._slots = BoundedSemaphore(4)

    def extract(
        self,
        user_message: str,
        current_draft: TripRequestDraft,
        context: ExtractionContext | None = None,
    ) -> PreferenceExtractionResult:
        if context is None:
            context = ExtractionContext()
        if not self._slots.acquire(blocking=False):
            raise DeepSeekUnavailableError("Trip processing is busy. Please try again.")
        deadline = monotonic() + self._policy.total_timeout_seconds
        snapshot = current_draft.model_copy(deep=True)
        context = context.model_copy(deep=True)
        try:
            future = self._pool.submit(
                self._attempts, user_message, snapshot, context, deadline
            )
        except RuntimeError:
            self._slots.release()
            raise DeepSeekUnavailableError(
                "Trip processing is unavailable. Please try again."
            ) from None
        try:
            return future.result(timeout=max(0, deadline - monotonic()))
        except TimeoutError:
            raise DeepSeekUnavailableError(
                "Trip processing timed out. Please try again."
            ) from None

    def _attempts(self, message, snapshot, context, deadline):
        try:
            for attempt in range(self._policy.max_retries + 1):
                if monotonic() >= deadline:
                    raise DeepSeekUnavailableError(
                        "Trip processing timed out. Please try again."
                    )
                try:
                    return self._extractor.extract(
                        message,
                        snapshot.model_copy(deep=True),
                        context=context.model_copy(deep=True),
                    )
                except DeepSeekUnavailableError:
                    if (
                        attempt == self._policy.max_retries
                        or monotonic() + 0.25 >= deadline
                    ):
                        raise
                    sleep(0.25)
        finally:
            self._slots.release()

    def close(self) -> None:
        # Drain finite I/O calls before closing their shared client on app shutdown.
        self._pool.shutdown(wait=True)
        self._extractor.close()
