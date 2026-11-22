"""Durable records and storage boundary for conversational planning sessions."""

import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from travel_ai.schemas.sessions import (
    ConversationState,
    ConversationTurnResponse,
    TripRequestDraft,
    UnsupportedRequestNotice,
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PlanningSessionConflictError(RuntimeError):
    """A save tried to replace a newer stored session revision."""


class PlanningSessionRecord(BaseModel):
    """Versioned, JSON-serializable state for one planning session."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    session_id: str = Field(min_length=1, max_length=100)
    revision: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    draft: TripRequestDraft
    state: ConversationState
    missing_questions: list[str] = Field(default_factory=list, max_length=100)
    missing_fields: list[str] = Field(default_factory=list, max_length=100)
    issues: dict[str, str] = Field(default_factory=dict, max_length=100)
    confirmed_result: ConversationTurnResponse | None = None
    unsupported: dict[str, UnsupportedRequestNotice] = Field(
        default_factory=dict,
        max_length=100,
    )
    deferred: list[str] = Field(default_factory=list, max_length=100)
    question_context: dict[str, str] = Field(default_factory=dict, max_length=100)

    @field_validator("created_at", "updated_at")
    @classmethod
    def normalize_utc(cls, value: datetime) -> datetime:
        """Require unambiguous timestamps and store them in UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("session timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("missing_questions", "missing_fields", "deferred")
    @classmethod
    def validate_text_lists(cls, values: list[str]) -> list[str]:
        """Reject blank or oversized persisted text values."""
        if any(not value.strip() or len(value) > 10_000 for value in values):
            raise ValueError("persisted session text must contain 1-10000 characters")
        return values

    @field_validator("issues", "question_context")
    @classmethod
    def validate_text_maps(cls, values: dict[str, str]) -> dict[str, str]:
        """Bound the limited message excerpts needed to continue a session."""
        if any(
            not key.strip()
            or len(key) > 500
            or not value.strip()
            or len(value) > 10_000
            for key, value in values.items()
        ):
            raise ValueError("persisted session text mappings contain invalid values")
        return values

    @model_validator(mode="after")
    def validate_record(self) -> "PlanningSessionRecord":
        """Reject inconsistent durable identity, state, and timestamps."""
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        if any(key != notice.request_id for key, notice in self.unsupported.items()):
            raise ValueError("unsupported request keys must match their request IDs")
        if self.confirmed_result is not None and (
            self.confirmed_result.session_id != self.session_id
            or self.confirmed_result.state != self.state
        ):
            raise ValueError("confirmed result must match the stored session")
        return self


class PlanningSessionRepository(Protocol):
    """Minimal persistence contract used by the planning-session service."""

    def create(self, session: PlanningSessionRecord) -> None:
        """Store a new session, rejecting an existing session ID."""

    def get(self, session_id: str) -> PlanningSessionRecord | None:
        """Return a defensive copy, or ``None`` when the session does not exist."""

    def save(self, session: PlanningSessionRecord) -> None:
        """Save the expected revision and reject stale or unknown sessions."""


class InMemoryPlanningSessionRepository:
    """Thread-safe process-local adapter for the durable record contract."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._records: dict[str, PlanningSessionRecord] = {}
        self._guard = RLock()
        self._clock = clock or _utc_now

    def create(self, session: PlanningSessionRecord) -> None:
        with self._guard:
            if session.session_id in self._records:
                raise ValueError(
                    f"planning session already exists: {session.session_id}"
                )
            self._records[session.session_id] = PlanningSessionRecord.model_validate(
                session.model_dump()
            )

    def get(self, session_id: str) -> PlanningSessionRecord | None:
        with self._guard:
            session = self._records.get(session_id)
            return session.model_copy(deep=True) if session is not None else None

    def save(self, session: PlanningSessionRecord) -> None:
        with self._guard:
            stored = self._records.get(session.session_id)
            if stored is None:
                raise KeyError(session.session_id)
            if session.revision != stored.revision:
                raise PlanningSessionConflictError(
                    f"stale planning session revision: {session.session_id}"
                )
            updated = session.model_dump()
            updated["revision"] = stored.revision + 1
            updated["updated_at"] = self._clock()
            self._records[session.session_id] = PlanningSessionRecord.model_validate(
                updated
            )

    def __len__(self) -> int:
        """Expose the record count for focused repository tests."""
        with self._guard:
            return len(self._records)


class SQLitePlanningSessionRepository:
    """Durable SQLite adapter with transactional optimistic concurrency."""

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS planning_sessions (
            session_id TEXT PRIMARY KEY,
            schema_version INTEGER NOT NULL,
            revision INTEGER NOT NULL CHECK (revision >= 1),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            record_json TEXT NOT NULL
        )
    """

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_seconds: float = 1.0,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if str(database_path) == ":memory:":
            raise ValueError("planning sessions require a durable SQLite file")
        if busy_timeout_seconds < 0:
            raise ValueError("busy_timeout_seconds must not be negative")
        self.database_path = Path(database_path)
        self.busy_timeout_seconds = busy_timeout_seconds
        self._busy_timeout_ms = round(busy_timeout_seconds * 1000)
        self._clock = clock or _utc_now
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database_path,
            timeout=self.busy_timeout_seconds,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        return connection

    def _initialize_schema(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(self._CREATE_TABLE)
            connection.commit()

    @staticmethod
    def _validated_copy(session: PlanningSessionRecord) -> PlanningSessionRecord:
        return PlanningSessionRecord.model_validate(session.model_dump())

    def create(self, session: PlanningSessionRecord) -> None:
        candidate = self._validated_copy(session)
        try:
            with closing(self._connect()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO planning_sessions (
                        session_id, schema_version, revision,
                        created_at, updated_at, record_json
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        candidate.session_id,
                        candidate.schema_version,
                        candidate.revision,
                        candidate.created_at.isoformat(),
                        candidate.updated_at.isoformat(),
                        candidate.model_dump_json(),
                    ),
                )
                connection.commit()
        except sqlite3.IntegrityError as error:
            raise ValueError(
                f"planning session already exists: {candidate.session_id}"
            ) from error

    def get(self, session_id: str) -> PlanningSessionRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT revision, record_json
                FROM planning_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        record = PlanningSessionRecord.model_validate_json(row["record_json"])
        if record.revision != row["revision"]:
            raise ValueError("stored planning session revision is inconsistent")
        return record

    def save(self, session: PlanningSessionRecord) -> None:
        updated = session.model_dump()
        updated["revision"] = session.revision + 1
        updated["updated_at"] = self._clock()
        candidate = PlanningSessionRecord.model_validate(updated)

        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    """
                    UPDATE planning_sessions
                    SET schema_version = ?, revision = ?, created_at = ?,
                        updated_at = ?, record_json = ?
                    WHERE session_id = ? AND revision = ?
                    """,
                    (
                        candidate.schema_version,
                        candidate.revision,
                        candidate.created_at.isoformat(),
                        candidate.updated_at.isoformat(),
                        candidate.model_dump_json(),
                        candidate.session_id,
                        session.revision,
                    ),
                )
                if cursor.rowcount != 1:
                    exists = connection.execute(
                        "SELECT 1 FROM planning_sessions WHERE session_id = ?",
                        (candidate.session_id,),
                    ).fetchone()
                    if exists is None:
                        raise KeyError(candidate.session_id)
                    raise PlanningSessionConflictError(
                        f"stale planning session revision: {candidate.session_id}"
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
