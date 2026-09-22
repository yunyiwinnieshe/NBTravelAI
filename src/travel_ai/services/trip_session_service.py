"""Fixture-backed conversational planning sessions."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

from pydantic import ValidationError

from travel_ai.schemas.preference_extraction import (
    PreferenceExtractionResult,
    PreferenceExtractionStatus,
)
from travel_ai.schemas.sessions import (
    ConversationState,
    ConversationTurnResponse,
    TripRequestDraft,
)
from travel_ai.schemas.trip import TravelerRequest, TripRequest
from travel_ai.services.preference_extraction import PreferenceExtractor
from travel_ai.services.recommendation_service import RecommendationService


class TripSessionNotFoundError(KeyError):
    """A request referred to a planning session that does not exist."""


class TripSessionNotReadyError(ValueError):
    """A session was confirmed before it had a complete reviewable draft."""


class FixtureOriginResolutionError(ValueError):
    """A fixture conversation named an origin outside the supported mapping."""


@dataclass
class _TripSession:
    """Mutable in-memory state for one fixture planning conversation."""

    draft: TripRequestDraft
    state: ConversationState
    missing_questions: list[str]


class FixtureOriginResolver:
    """Resolve the limited fixture place names without generating location IDs."""

    _ORIGIN_IDS_BY_NAME = {
        "boston": "boston_ma",
        "boston, ma": "boston_ma",
        "new york": "new_york_ny",
        "new york, ny": "new_york_ny",
    }

    def resolve(self, origin: str) -> str:
        """Return a configured fixture ID for an already-confirmed place name."""
        normalized_origin = origin.strip().casefold()
        try:
            return self._ORIGIN_IDS_BY_NAME[normalized_origin]
        except KeyError as error:
            raise FixtureOriginResolutionError(
                f"'{origin}' is not a supported fixture origin"
            ) from error


class TripSessionService:
    """Collect a typed draft before calling deterministic recommendations."""

    def __init__(
        self,
        extractor: PreferenceExtractor,
        recommendation_service: RecommendationService,
        origin_resolver: FixtureOriginResolver | None = None,
    ) -> None:
        self.extractor = extractor
        self.recommendation_service = recommendation_service
        self.origin_resolver = origin_resolver or FixtureOriginResolver()
        self._sessions: dict[str, _TripSession] = {}

    def create_session(self, initial_message: str | None) -> ConversationTurnResponse:
        """Create a session and optionally process its first fixture message."""
        session_id = str(uuid4())
        session = _TripSession(
            draft=TripRequestDraft(),
            state=ConversationState.COLLECTING,
            missing_questions=["Tell me where each traveler is leaving from."],
        )
        self._sessions[session_id] = session
        if initial_message is not None:
            return self.add_message(session_id, initial_message)
        return self._response(session_id, session)

    def add_message(
        self,
        session_id: str,
        message: str,
    ) -> ConversationTurnResponse:
        """Apply one extractor result to the session's saved draft."""
        session = self._get_session(session_id)
        result = self.extractor.extract(message, session.draft)
        self._apply_extraction(session, result)
        return self._response(session_id, session)

    def confirm_session(self, session_id: str) -> ConversationTurnResponse:
        """Run recommendations only for the draft currently shown for review."""
        session = self._get_session(session_id)
        if session.state != ConversationState.REVIEW:
            raise TripSessionNotReadyError(
                "complete the trip details before confirming this session"
            )
        trip_request = self._build_trip_request(session.draft)
        response = self.recommendation_service.get_recommendations(trip_request)
        session.state = (
            ConversationState.RESULTS
            if response.status == "success"
            else ConversationState.NO_MATCH
        )
        session.missing_questions = []
        return ConversationTurnResponse(
            session_id=session_id,
            state=session.state,
            assistant_message=(
                f"Found {len(response.recommendations)} destination recommendations."
                if session.state == ConversationState.RESULTS
                else "No fixture destinations match these confirmed trip details."
            ),
            trip_request_draft=session.draft,
            recommendations=response.recommendations,
        )

    def _get_session(self, session_id: str) -> _TripSession:
        try:
            return self._sessions[session_id]
        except KeyError as error:
            raise TripSessionNotFoundError(session_id) from error

    def _apply_extraction(
        self,
        session: _TripSession,
        result: PreferenceExtractionResult,
    ) -> None:
        """Replace the draft with the extractor's complete post-message snapshot."""
        session.draft = result.draft
        session.missing_questions = [
            missing_field.clarification_question
            for missing_field in result.missing_fields
        ]
        session.state = (
            ConversationState.COLLECTING
            if result.status == PreferenceExtractionStatus.NEEDS_CLARIFICATION
            else ConversationState.REVIEW
        )

    def _response(
        self,
        session_id: str,
        session: _TripSession,
    ) -> ConversationTurnResponse:
        if session.state == ConversationState.REVIEW:
            assistant_message = (
                "Your trip details are ready. Confirm to see recommendations."
            )
        else:
            assistant_message = " ".join(session.missing_questions)
        return ConversationTurnResponse(
            session_id=session_id,
            state=session.state,
            assistant_message=assistant_message,
            trip_request_draft=session.draft,
            missing_fields=session.missing_questions,
        )

    def _build_trip_request(self, draft: TripRequestDraft) -> TripRequest:
        """Convert a reviewable draft into the canonical deterministic request."""
        if draft.start_date is None or draft.end_date is None:
            raise TripSessionNotReadyError(
                "trip dates are required before confirmation"
            )
        try:
            travelers = [
                TravelerRequest(
                    traveler_id=traveler.traveler_id,
                    origin_id=self.origin_resolver.resolve(traveler.origin or ""),
                    budget_usd=Decimal(str(traveler.budget_usd)),
                    max_one_way_travel_minutes=round(
                        (traveler.max_travel_time_hours or 0) * 60
                    ),
                    preferences=traveler.preferences,
                )
                for traveler in draft.travelers
            ]
            return TripRequest(
                travelers=travelers,
                start_date=draft.start_date,
                end_date=draft.end_date,
            )
        except (FixtureOriginResolutionError, ValidationError) as error:
            raise TripSessionNotReadyError(
                "the reviewed trip details cannot be converted into a valid request"
            ) from error
