"""Contract tests for durable planning-session records and repositories."""

from datetime import UTC, datetime, timedelta
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
