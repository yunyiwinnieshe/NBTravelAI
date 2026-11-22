"""Contract tests for the process-local planning-session repository."""

from unittest.mock import Mock

import pytest

from travel_ai.schemas.sessions import (
    ConversationState,
    TravelerPreferencesDraft,
    TripRequestDraft,
)
from travel_ai.services.planning_session_repository import (
    InMemoryPlanningSessionRepository,
    PlanningSessionRecord,
    PlanningSessionRepository,
)
from travel_ai.services.trip_session_service import TripSessionService


def session_record(session_id: str = "session_1") -> PlanningSessionRecord:
    return PlanningSessionRecord(
        session_id=session_id,
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
    assert loaded is record


def test_repository_saves_an_existing_session() -> None:
    repository = InMemoryPlanningSessionRepository()
    record = session_record()
    repository.create(record)
    record.missing_questions.append("What dates work?")

    repository.save(record)

    assert repository.get("session_1").missing_questions == [
        "Where is each traveler leaving from?",
        "What dates work?",
    ]


def test_create_rejects_duplicate_and_save_rejects_unknown_session() -> None:
    repository = InMemoryPlanningSessionRepository()
    record = session_record()
    repository.create(record)

    try:
        repository.create(record)
    except ValueError as error:
        assert "already exists" in str(error)
    else:
        raise AssertionError("duplicate session was accepted")

    try:
        repository.save(session_record("missing"))
    except KeyError as error:
        assert error.args == ("missing",)
    else:
        raise AssertionError("unknown session was saved")


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
