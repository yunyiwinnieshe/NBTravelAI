"""Fixture-backed conversational planning sessions."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from threading import RLock
from uuid import uuid4

from pydantic import ValidationError

from travel_ai.schemas.preference_extraction import (
    PreferenceExtractionResult,
)
from travel_ai.schemas.sessions import (
    ConversationState,
    ConversationTurnResponse,
    TravelerPreferencesDraft,
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
    missing_fields: list[str] = field(default_factory=list)
    issues: dict[str, str] = field(default_factory=dict)
    confirmed_result: ConversationTurnResponse | None = None
    lock: RLock = field(default_factory=RLock)


class FixtureOriginResolver:
    """Resolve the limited fixture place names without generating location IDs."""

    _ORIGIN_IDS_BY_NAME = {
        "boston": "boston_ma",
        "boston, ma": "boston_ma",
        "new york": "new_york_ny",
        "new york, ny": "new_york_ny",
        "boston_ma": "boston_ma",
        "new_york_ny": "new_york_ny",
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
            draft=TripRequestDraft(
                travelers=[
                    TravelerPreferencesDraft(traveler_id="traveler_a"),
                    TravelerPreferencesDraft(traveler_id="traveler_b"),
                ]
            ),
            state=ConversationState.COLLECTING,
            missing_questions=["Tell me where each traveler is leaving from."],
        )
        self._sessions[session_id] = session
        self._refresh_state(session)
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
        with session.lock:
            result = self.extractor.extract(
                message, session.draft.model_copy(deep=True)
            )
            self._apply_extraction(session, result)
            if session.confirmed_result is not None:
                return session.confirmed_result.model_copy(deep=True)
            return self._response(session_id, session)

    def confirm_session(self, session_id: str) -> ConversationTurnResponse:
        """Run recommendations only for the draft currently shown for review."""
        session = self._get_session(session_id)
        with session.lock:
            return self._confirm_session(session_id, session)

    def _confirm_session(
        self, session_id: str, session: _TripSession
    ) -> ConversationTurnResponse:
        """Serialize confirmation with edits and duplicate confirmations."""
        if session.confirmed_result is not None:
            return session.confirmed_result.model_copy(deep=True)
        self._refresh_state(session)
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
        session.confirmed_result = ConversationTurnResponse(
            session_id=session_id,
            state=session.state,
            assistant_message=(
                f"Found {len(response.recommendations)} destination recommendations."
                if session.state == ConversationState.RESULTS
                else "No fixture destination meets both travelers' "
                "current constraints. "
                "Adjust a budget, travel-time limit, date, or origin and try again."
            ),
            trip_request_draft=session.draft.model_copy(deep=True),
            recommendations=response.recommendations,
        )
        return session.confirmed_result.model_copy(deep=True)

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
        """Merge valid mentioned fields, retaining unresolved issues across turns."""
        expected_ids = [traveler.traveler_id for traveler in session.draft.travelers]
        returned_ids = [traveler.traveler_id for traveler in result.draft.travelers]
        if sorted(returned_ids) != sorted(expected_ids):
            raise ValueError("extraction must preserve the two assigned traveler IDs")
        previous = session.draft.model_copy(deep=True)
        updates = result.draft.model_dump(exclude_unset=True)
        reported = {
            item.field_path: item.clarification_question
            for item in result.missing_fields
            if item.reason != "missing"
        }
        for key in ("start_date", "end_date"):
            if key in updates and key not in reported:
                setattr(session.draft, key, updates[key])
                session.issues.pop(key, None)
        for update in updates.get("travelers", []):
            traveler = next(
                t
                for t in session.draft.travelers
                if t.traveler_id == update["traveler_id"]
            )
            for key, value in update.items():
                if key in ("traveler_id", "origin_id"):
                    continue
                path = f"travelers.{traveler.traveler_id}.{key}"
                if any(path == p or path.startswith(p + ".") for p in reported):
                    continue
                if key == "preferences":
                    valid_preferences = {
                        k: v for k, v in value.items() if f"{path}.{k}" not in reported
                    }
                    for preference_key in valid_preferences:
                        session.issues.pop(f"{path}.{preference_key}", None)
                    traveler.preferences = traveler.preferences.model_validate(
                        {**traveler.preferences.model_dump(), **valid_preferences}
                    )
                    continue
                setattr(traveler, key, value)
                session.issues = {
                    p: q
                    for p, q in session.issues.items()
                    if p != path and not p.startswith(path + ".")
                }
        session.issues.update(reported)
        self._validate_updates(session, previous)
        if session.draft != previous or session.issues:
            session.confirmed_result = None
        if session.confirmed_result is None:
            self._refresh_state(session)

    def _validate_updates(
        self, session: _TripSession, previous: TripRequestDraft
    ) -> None:
        """Reject invalid dates and origins without discarding other valid updates."""
        draft = session.draft
        if draft.start_date is not None and draft.start_date < date.today():
            draft.start_date = previous.start_date
            session.issues["start_date"] = (
                "What is your departure date, today or later?"
            )
        if (
            draft.start_date
            and draft.end_date
            and not 3 <= (draft.end_date - draft.start_date).days + 1 <= 7
        ):
            draft.start_date, draft.end_date = previous.start_date, previous.end_date
            session.issues["end_date"] = (
                "What exact dates would you like for a 3–7 day trip?"
            )
        for traveler, old in zip(draft.travelers, previous.travelers, strict=True):
            try:
                traveler.origin_id = (
                    self.origin_resolver.resolve(traveler.origin)
                    if traveler.origin
                    else None
                )
            except FixtureOriginResolutionError:
                session.issues[f"travelers.{traveler.traveler_id}.origin"] = (
                    f"Which place does {traveler.display_label} mean? "
                    "Fixture mode supports Boston or New York."
                )
                traveler.origin, traveler.origin_id = old.origin, old.origin_id
        origins = [t.origin_id for t in draft.travelers]
        if origins[0] is not None and origins[0] == origins[1]:
            for traveler, old in reversed(
                list(zip(draft.travelers, previous.travelers, strict=True))
            ):
                if (
                    traveler.origin != old.origin
                    and old.origin_id != traveler.origin_id
                ):
                    session.issues[f"travelers.{traveler.traveler_id}.origin"] = (
                        "Which distinct origin should this traveler use? "
                        "The travelers must leave from different places."
                    )
                    traveler.origin, traveler.origin_id = old.origin, old.origin_id
                    break

    def _refresh_state(self, session: _TripSession) -> None:
        """Determine readiness independently of the extractor's status claim."""
        questions = dict(session.issues)
        draft = session.draft
        for key in ("start_date", "end_date"):
            if getattr(draft, key) is None:
                questions.setdefault(key, f"What is your {key.replace('_', ' ')}?")
        for traveler in draft.travelers:
            for key, question in (
                ("origin", f"Where is {traveler.display_label} leaving from?"),
                (
                    "budget_usd",
                    f"What is {traveler.display_label}'s maximum round-trip "
                    "airfare budget in USD?",
                ),
                (
                    "max_travel_time_hours",
                    f"What is {traveler.display_label}'s maximum one-way "
                    "travel time in hours, including layovers?",
                ),
            ):
                if getattr(traveler, key) is None:
                    questions.setdefault(
                        f"travelers.{traveler.traveler_id}.{key}", question
                    )
        if not questions:
            try:
                self._build_trip_request(draft)
            except TripSessionNotReadyError:
                questions["request"] = (
                    "Please correct the dates, distinct origins, budgets, or "
                    "travel-time limits to match the trip requirements."
                )
        ordered = sorted(questions, key=lambda p: "preferences" in p)
        session.missing_fields = ordered
        session.missing_questions = [questions[p] for p in ordered]
        session.state = (
            ConversationState.COLLECTING if questions else ConversationState.REVIEW
        )

    def _response(
        self,
        session_id: str,
        session: _TripSession,
    ) -> ConversationTurnResponse:
        if session.state == ConversationState.REVIEW:
            lines = [
                f"Travel dates: {session.draft.start_date} to {session.draft.end_date}."
            ]
            for traveler in session.draft.travelers:
                preferences = traveler.preferences.model_dump(
                    mode="json", exclude_none=True
                )
                description = (
                    str(preferences)
                    if traveler.preferences.interest_tags
                    or traveler.preferences.temperature_range
                    else "none provided"
                )
                lines.append(
                    f"{traveler.display_label}: {traveler.origin} "
                    f"({traveler.origin_id}); airfare budget ${traveler.budget_usd} "
                    f"USD; maximum one-way time {traveler.max_travel_time_hours} "
                    f"hours including layovers. Preferences: {description}."
                )
            lines.append("Confirm this trip request to find destinations.")
            assistant_message = "\n".join(lines)
        else:
            assistant_message = session.missing_questions[0]
        return ConversationTurnResponse(
            session_id=session_id,
            state=session.state,
            assistant_message=assistant_message,
            trip_request_draft=session.draft.model_copy(deep=True),
            missing_fields=session.missing_fields,
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
        except (
            FixtureOriginResolutionError,
            ValidationError,
            InvalidOperation,
        ) as error:
            raise TripSessionNotReadyError(
                "the reviewed trip details cannot be converted into a valid request"
            ) from error
