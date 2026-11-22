"""Contract tests for durable planning-session records and repositories."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from travel_ai.schemas.sessions import (
    ConversationState,
    TravelerPreferencesDraft,
    TripRequestDraft,
    UnsupportedRequestNotice,
)
from travel_ai.services.planning_session_repository import (
    InMemoryPlanningSessionRepository,
    PlanningSessionConflictError,
    PlanningSessionRecord,
    PlanningSessionRepository,
    SQLitePlanningSessionRepository,
)
from travel_ai.services.trip_session_service import TripSessionService

CREATED_AT = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)
UPDATED_AT = CREATED_AT + timedelta(minutes=5)


def session_record(session_id: str = "session_1") -> PlanningSessionRecord:
    return PlanningSessionRecord(
        session_id=session_id,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        draft=TripRequestDraft(
            travelers=[
                TravelerPreferencesDraft(traveler_id="traveler_a"),
                TravelerPreferencesDraft(traveler_id="traveler_b"),
            ]
        ),
        state=ConversationState.COLLECTING,
        missing_questions=["Where is each traveler leaving from?"],
    )


def test_in_memory_repository_satisfies_storage_contract() -> None:
    repository: PlanningSessionRepository = InMemoryPlanningSessionRepository()
    record = session_record()

    repository.create(record)
    loaded = repository.get(record.session_id)

    assert loaded == record
    assert loaded is not record


def test_repository_returns_defensive_copies_and_versions_saves() -> None:
    repository = InMemoryPlanningSessionRepository(clock=lambda: UPDATED_AT)
    record = session_record()
    repository.create(record)

    loaded = repository.get("session_1")
    assert loaded is not None
    loaded.missing_questions.append("What dates work?")
    assert repository.get("session_1").missing_questions == [
        "Where is each traveler leaving from?"
    ]

    repository.save(loaded)
    saved = repository.get("session_1")
    assert saved is not None
    assert saved.revision == 2
    assert saved.updated_at == UPDATED_AT
    assert saved.missing_questions[-1] == "What dates work?"


def test_repository_rejects_stale_revision() -> None:
    repository = InMemoryPlanningSessionRepository(clock=lambda: UPDATED_AT)
    repository.create(session_record())
    first = repository.get("session_1")
    stale = repository.get("session_1")
    assert first is not None and stale is not None

    repository.save(first)

    with pytest.raises(PlanningSessionConflictError, match="stale"):
        repository.save(stale)


def test_create_rejects_duplicate_and_save_rejects_unknown_session() -> None:
    repository = InMemoryPlanningSessionRepository()
    record = session_record()
    repository.create(record)

    with pytest.raises(ValueError, match="already exists"):
        repository.create(record)

    with pytest.raises(KeyError) as captured:
        repository.save(session_record("missing"))
    assert captured.value.args == ("missing",)


def test_durable_record_round_trips_required_message_excerpts() -> None:
    record = session_record().model_copy(
        update={
            "question_context": {"start_date": "Change departure to June 11"},
            "unsupported": {
                "request-123": UnsupportedRequestNotice(
                    request_id="request-123",
                    user_text="I also want a hotel with a pool",
                    explanation="Hotel preferences are not supported yet.",
                )
            },
            "deferred": ["I also want a rental car"],
        }
    )

    restored = PlanningSessionRecord.model_validate_json(record.model_dump_json())

    assert restored == record
    assert "lock" not in restored.model_dump()
    assert restored.question_context["start_date"] == "Change departure to June 11"
    assert restored.unsupported["request-123"].user_text.endswith("with a pool")
    assert restored.deferred == ["I also want a rental car"]


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 2},
        {"created_at": datetime(2026, 11, 21, 15, 0)},
        {"updated_at": CREATED_AT - timedelta(seconds=1)},
        {"unexpected": "value"},
    ],
)
def test_durable_record_rejects_unsupported_or_ambiguous_data(change) -> None:
    payload = session_record().model_dump()
    payload.update(change)

    with pytest.raises(ValidationError):
        PlanningSessionRecord.model_validate(payload)


def test_durable_record_rejects_mismatched_unsupported_request_key() -> None:
    payload = session_record().model_dump()
    payload["unsupported"] = {
        "wrong-key": {
            "request_id": "request-123",
            "user_text": "I also want a hotel",
            "explanation": "Hotel preferences are not supported yet.",
        }
    }

    with pytest.raises(ValidationError, match="request keys"):
        PlanningSessionRecord.model_validate(payload)


def test_failed_initial_message_is_never_created() -> None:
    repository = InMemoryPlanningSessionRepository()
    extractor = Mock()
    extractor.extract.side_effect = RuntimeError("extraction failed")
    service = TripSessionService(
        extractor,
        Mock(),
        repository=repository,
    )

    with pytest.raises(RuntimeError, match="extraction failed"):
        service.create_session("initial message")

    assert len(repository) == 0


def test_sqlite_repository_survives_new_instance(tmp_path) -> None:
    database_path = tmp_path / "planning-sessions.sqlite"
    first = SQLitePlanningSessionRepository(
        database_path,
        clock=lambda: UPDATED_AT,
    )
    first.create(session_record())

    candidate = first.get("session_1")
    assert candidate is not None
    candidate.missing_questions.append("What dates work?")
    first.save(candidate)

    restored = SQLitePlanningSessionRepository(database_path).get("session_1")
    assert restored is not None
    assert restored.revision == 2
    assert restored.updated_at == UPDATED_AT
    assert restored.missing_questions[-1] == "What dates work?"


def test_sqlite_repository_rejects_duplicate_and_unknown_sessions(tmp_path) -> None:
    repository = SQLitePlanningSessionRepository(tmp_path / "planning-sessions.sqlite")
    record = session_record()
    repository.create(record)

    with pytest.raises(ValueError, match="already exists"):
        repository.create(record)

    with pytest.raises(KeyError) as captured:
        repository.save(session_record("missing"))
    assert captured.value.args == ("missing",)


def test_sqlite_concurrent_updates_cannot_silently_overwrite(tmp_path) -> None:
    database_path = tmp_path / "planning-sessions.sqlite"
    first_repository = SQLitePlanningSessionRepository(database_path)
    second_repository = SQLitePlanningSessionRepository(database_path)
    first_repository.create(session_record())
    first = first_repository.get("session_1")
    second = second_repository.get("session_1")
    assert first is not None and second is not None
    barrier = Barrier(2)

    def save(
        repository: SQLitePlanningSessionRepository,
        candidate: PlanningSessionRecord,
        question: str,
    ) -> str:
        candidate.missing_questions = [question]
        barrier.wait()
        try:
            repository.save(candidate)
        except PlanningSessionConflictError:
            return "conflict"
        return "saved"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = [
            pool.submit(save, first_repository, first, "First update"),
            pool.submit(save, second_repository, second, "Second update"),
        ]
        results = [future.result() for future in outcomes]

    assert sorted(results) == ["conflict", "saved"]
    stored = first_repository.get("session_1")
    assert stored is not None
    assert stored.revision == 2
    assert stored.missing_questions in [["First update"], ["Second update"]]


def test_sqlite_repository_requires_file_and_bounded_timeout(tmp_path) -> None:
    with pytest.raises(ValueError, match="durable SQLite file"):
        SQLitePlanningSessionRepository(":memory:")

    with pytest.raises(ValueError, match="must not be negative"):
        SQLitePlanningSessionRepository(
            tmp_path / "planning-sessions.sqlite",
            busy_timeout_seconds=-1,
        )
