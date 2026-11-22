"""Storage boundary for conversational planning sessions."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from threading import RLock
from typing import Protocol

from travel_ai.schemas.sessions import (
    ConversationState,
    ConversationTurnResponse,
    TripRequestDraft,
    UnsupportedRequestNotice,
)


@dataclass
class PlanningSessionRecord:
    """Application-owned session state stored behind the repository boundary."""

    session_id: str
    draft: TripRequestDraft
    state: ConversationState
    missing_questions: list[str]
    missing_fields: list[str] = field(default_factory=list)
    issues: dict[str, str] = field(default_factory=dict)
    confirmed_result: ConversationTurnResponse | None = None
    unsupported: dict[str, UnsupportedRequestNotice] = field(default_factory=dict)
    deferred: list[str] = field(default_factory=list)
    question_context: dict[str, str] = field(default_factory=dict)
    lock: RLock = field(default_factory=RLock, repr=False, compare=False)

    def copy(self, *, lock: RLock | None = None) -> PlanningSessionRecord:
        """Return a defensive copy while optionally retaining the session lock."""
        return replace(
            self,
            draft=self.draft.model_copy(deep=True),
            missing_questions=list(self.missing_questions),
            missing_fields=list(self.missing_fields),
            issues=dict(self.issues),
            confirmed_result=(
                self.confirmed_result.model_copy(deep=True)
                if self.confirmed_result is not None
                else None
            ),
            unsupported={
                key: value.model_copy(deep=True)
                for key, value in self.unsupported.items()
            },
            deferred=list(self.deferred),
            question_context=dict(self.question_context),
            lock=lock or self.lock,
        )


class PlanningSessionRepository(Protocol):
    """Minimal persistence contract used by the planning-session service."""

    def create(self, session: PlanningSessionRecord) -> None:
        """Store a new session, rejecting an existing session ID."""

    def get(self, session_id: str) -> PlanningSessionRecord | None:
        """Return a session, or ``None`` when it does not exist."""

    def save(self, session: PlanningSessionRecord) -> None:
        """Replace an existing session, rejecting an unknown session ID."""


class InMemoryPlanningSessionRepository:
    """Thread-safe process-local repository preserving current V1 behavior."""

    def __init__(self) -> None:
        self._records: dict[str, PlanningSessionRecord] = {}
        self._guard = RLock()

    def create(self, session: PlanningSessionRecord) -> None:
        with self._guard:
            if session.session_id in self._records:
                raise ValueError(
                    f"planning session already exists: {session.session_id}"
                )
            self._records[session.session_id] = session

    def get(self, session_id: str) -> PlanningSessionRecord | None:
        with self._guard:
            return self._records.get(session_id)

    def save(self, session: PlanningSessionRecord) -> None:
        with self._guard:
            if session.session_id not in self._records:
                raise KeyError(session.session_id)
            self._records[session.session_id] = session

    def __len__(self) -> int:
        """Expose the record count for focused repository tests."""
        with self._guard:
            return len(self._records)
