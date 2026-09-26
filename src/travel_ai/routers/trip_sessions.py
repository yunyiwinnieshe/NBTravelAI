"""Conversational trip-planning HTTP routes."""

from datetime import date
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from travel_ai.schemas.preference_extraction import (
    MissingField,
    MissingFieldReason,
    PreferenceExtractionResult,
    PreferenceExtractionStatus,
)
from travel_ai.schemas.sessions import (
    ConversationTurnResponse,
    CreateTripSessionRequest,
    TravelerPreferencesDraft,
    TripRequestDraft,
    TripSessionMessageRequest,
)
from travel_ai.services.preference_extraction import FixturePreferenceExtractor
from travel_ai.services.recommendation_service import RecommendationService
from travel_ai.services.trip_session_service import (
    TripSessionNotFoundError,
    TripSessionNotReadyError,
    TripSessionService,
)

router = APIRouter(prefix="/trip-sessions", tags=["trip sessions"])


@lru_cache
def get_trip_session_service() -> TripSessionService:
    """Build the limited offline session flow used before live LLM integration."""
    initial_draft = TripRequestDraft(
        travelers=[
            TravelerPreferencesDraft(
                traveler_id="traveler_a", display_name="Alice", origin="Boston"
            ),
            TravelerPreferencesDraft(
                traveler_id="traveler_b", display_name="Bob", origin="New York"
            ),
        ]
    )
    complete_draft = TripRequestDraft(
        travelers=[
            TravelerPreferencesDraft(
                traveler_id="traveler_a",
                display_name="Alice",
                origin="Boston",
                budget_usd=500,
                max_travel_time_hours=10,
            ),
            TravelerPreferencesDraft(
                traveler_id="traveler_b",
                display_name="Bob",
                origin="New York",
                budget_usd=500,
                max_travel_time_hours=10,
            ),
        ],
        start_date=date(2099, 6, 10),
        end_date=date(2099, 6, 14),
    )
    extractor = FixturePreferenceExtractor(
        {
            "Alice is leaving from Boston and Bob is leaving from New York.": (
                PreferenceExtractionResult(
                    draft=initial_draft,
                    status=PreferenceExtractionStatus.NEEDS_CLARIFICATION,
                    missing_fields=[
                        MissingField(
                            field_path="start_date",
                            reason=MissingFieldReason.MISSING,
                            clarification_question=(
                                "What dates would you like to travel?"
                            ),
                        ),
                        MissingField(
                            field_path="travelers.budget_usd",
                            reason=MissingFieldReason.MISSING,
                            clarification_question=(
                                "What is each traveler's flight budget?"
                            ),
                        ),
                        MissingField(
                            field_path="travelers.max_travel_time_hours",
                            reason=MissingFieldReason.MISSING,
                            clarification_question=(
                                "What is each traveler's maximum one-way travel time?"
                            ),
                        ),
                    ],
                )
            ),
            (
                "We will travel June 10 to June 14, 2099. Alice and Bob each have "
                "a $500 budget and can travel up to 10 hours."
            ): PreferenceExtractionResult(
                draft=complete_draft,
                status=PreferenceExtractionStatus.READY_FOR_REVIEW,
            ),
        }
    )
    return TripSessionService(extractor, RecommendationService())


@router.post(
    "",
    response_model=ConversationTurnResponse,
)
def create_trip_session(
    request: CreateTripSessionRequest,
    service: Annotated[TripSessionService, Depends(get_trip_session_service)],
) -> ConversationTurnResponse:
    """Start a fixture-backed planning session."""
    try:
        return service.create_session(request.initial_message)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error


@router.post(
    "/{session_id}/messages",
    response_model=ConversationTurnResponse,
)
def add_trip_session_message(
    session_id: str,
    request: TripSessionMessageRequest,
    service: Annotated[TripSessionService, Depends(get_trip_session_service)],
) -> ConversationTurnResponse:
    """Apply a fixture extraction result to the saved session draft."""
    try:
        if request.action == "confirm":
            return service.confirm_session(session_id)
        assert request.message is not None
        return service.add_message(session_id, request.message)
    except TripSessionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="trip session was not found",
        ) from error
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error


@router.post(
    "/{session_id}/confirm", response_model=ConversationTurnResponse, deprecated=True
)
def confirm_trip_session(
    session_id: str,
    service: Annotated[TripSessionService, Depends(get_trip_session_service)],
) -> ConversationTurnResponse:
    """Confirm the reviewed draft and return fixture recommendations."""
    try:
        return service.confirm_session(session_id)
    except TripSessionNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="trip session was not found",
        ) from error
    except TripSessionNotReadyError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
