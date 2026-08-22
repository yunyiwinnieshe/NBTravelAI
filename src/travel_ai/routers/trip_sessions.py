"""Conversational trip-planning HTTP routes."""

from fastapi import APIRouter, HTTPException, status

from travel_ai.schemas.sessions import (
    ConversationTurnResponse,
    CreateTripSessionRequest,
    TripSessionMessageRequest,
)

router = APIRouter(prefix="/trip-sessions", tags=["trip sessions"])


@router.post(
    "",
    response_model=ConversationTurnResponse,
    responses={501: {"description": "Trip sessions are planned but not implemented."}},
)
def create_trip_session(
    _request: CreateTripSessionRequest,
) -> ConversationTurnResponse:
    """Reserve the session-creation API before session storage is added."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Trip sessions will be implemented with the LLM workflow in Week 4.",
    )


@router.post(
    "/{session_id}/messages",
    response_model=ConversationTurnResponse,
    responses={501: {"description": "Trip sessions are planned but not implemented."}},
)
def add_trip_session_message(
    session_id: str,
    _request: TripSessionMessageRequest,
) -> ConversationTurnResponse:
    """Reserve the conversation-turn API before session storage is added."""
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=(
            f"Trip session '{session_id}' cannot accept messages until the LLM "
            "workflow is implemented in Week 4."
        ),
    )
