"""Transactional conversational planning sessions with configured extraction."""

import re
from dataclasses import dataclass, field, replace
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
    ExtractionContext,
    PendingQuestion,
    TravelerPreferencesDraft,
    TripRequestDraft,
    UnsupportedRequestNotice,
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


def is_non_trip_control_message(message: str) -> bool:
    """Recognize explicit, control-only messages before sending them to a model.

    This is a narrow backstop, not a general prompt-injection classifier. Ordinary
    corrections such as "ignore my previous budget" still reach extraction.
    """
    role_spoof = re.match(r"^\s*(?:system|developer|assistant)\s*:", message, re.I)
    control_verb = re.search(
        r"\b(?:call|confirm|reveal|override|ignore)\b", message, re.I
    )
    trip_detail = re.search(
        r"\b(?:budget|airfare|travel time|departure|depart|return date|origin|"
        r"flight|hotel|temperature|interest|beach|museum)\b",
        message,
        re.I,
    )
    explicit_override = re.match(
        r"^\s*ignore all previous instructions\b", message, re.I
    ) and re.search(r"\b(?:system override|not my trip request)\b", message, re.I)
    return bool((role_spoof and control_verb and not trip_detail) or explicit_override)


@dataclass
class _TripSession:
    """Mutable in-memory state for one fixture planning conversation."""

    draft: TripRequestDraft
    state: ConversationState
    missing_questions: list[str]
    missing_fields: list[str] = field(default_factory=list)
    issues: dict[str, str] = field(default_factory=dict)
    confirmed_result: ConversationTurnResponse | None = None
    unsupported: dict[str, UnsupportedRequestNotice] = field(default_factory=dict)
    deferred: list[str] = field(default_factory=list)
    question_context: dict[str, str] = field(default_factory=dict)
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

    def close(self) -> None:
        self.extractor.close()

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
            try:
                return self.add_message(session_id, initial_message)
            except Exception:
                # No inaccessible partial session is retained on failed creation.
                self._sessions.pop(session_id, None)
                raise
        return self._response(session_id, session)

    def add_message(
        self,
        session_id: str,
        message: str,
    ) -> ConversationTurnResponse:
        """Apply one extractor result to the session's saved draft."""
        session = self._get_session(session_id)
        with session.lock:
            if is_non_trip_control_message(message):
                response = (
                    session.confirmed_result.model_copy(deep=True)
                    if session.confirmed_result is not None
                    else self._response(session_id, session)
                )
                response.assistant_message = (
                    "I can't follow instructions to change system behavior or reveal "
                    "credentials. Your saved trip details are unchanged.\n"
                    + response.assistant_message
                )
                return response
            context = ExtractionContext(
                pending_questions=self._pending_questions(session),
                unsupported_requests=list(session.unsupported.values()),
            )
            result = self.extractor.extract(
                message,
                session.draft.model_copy(deep=True),
                context=context.model_copy(deep=True),
            )
            candidate = self._copy_session(session)
            self._apply_extraction(candidate, result)
            for path, question in candidate.issues.items():
                if path not in session.issues or question != session.issues[path]:
                    candidate.question_context[path] = message
            candidate.question_context = {
                path: source
                for path, source in candidate.question_context.items()
                if path in candidate.missing_fields
            }
            for acknowledgment in result.acknowledged_unsupported:
                if (
                    acknowledgment.evidence not in message
                    or acknowledgment.request_id not in session.unsupported
                ):
                    raise ValueError("acknowledgment must quote the current message")
                self._defer_request(candidate, acknowledgment.request_id)
            if result.acknowledged_unsupported:
                candidate.confirmed_result = None
                self._refresh_state(candidate)
            self._commit_session(session, candidate)
            if session.confirmed_result is not None:
                return session.confirmed_result.model_copy(deep=True)
            return self._response(session_id, session)

    @staticmethod
    def _copy_session(session: _TripSession) -> _TripSession:
        return replace(
            session,
            draft=session.draft.model_copy(deep=True),
            issues=dict(session.issues),
            missing_fields=list(session.missing_fields),
            missing_questions=list(session.missing_questions),
            unsupported={
                key: value.model_copy(deep=True)
                for key, value in session.unsupported.items()
            },
            deferred=list(session.deferred),
            question_context=dict(session.question_context),
        )

    @staticmethod
    def _commit_session(session: _TripSession, candidate: _TripSession) -> None:
        # Preserve the original object/lock for callers already waiting on it.
        for name in (
            "draft",
            "state",
            "issues",
            "missing_fields",
            "missing_questions",
            "unsupported",
            "deferred",
            "confirmed_result",
            "question_context",
        ):
            setattr(session, name, getattr(candidate, name))

    @staticmethod
    def _pending_questions(session: _TripSession) -> list[PendingQuestion]:
        count = 2 if session.unsupported else 3
        return [
            PendingQuestion(
                field_path=path,
                question=question,
                source_message=session.question_context.get(path),
            )
            for path, question in zip(
                session.missing_fields[:count],
                session.missing_questions[:count],
                strict=True,
            )
        ]

    @staticmethod
    def _defer_request(session: _TripSession, request_id: str) -> None:
        notice = session.unsupported.pop(request_id, None)
        if notice is None:
            raise ValueError("unsupported request is not pending in this session")
        session.deferred.append(notice.user_text)
        if notice.field_path:
            session.issues.pop(notice.field_path, None)

    def defer_unsupported(self, session_id: str) -> ConversationTurnResponse:
        """Explicitly continue without the currently displayed unsupported requests."""
        session = self._get_session(session_id)
        with session.lock:
            if session.unsupported:
                for request_id in list(session.unsupported):
                    self._defer_request(session, request_id)
                session.confirmed_result = None
                self._refresh_state(session)
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
            deferred_requests=list(session.deferred),
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
        for unsupported in result.unsupported_requests:
            if not any(
                n.user_text.casefold() == unsupported.user_text.casefold()
                for n in session.unsupported.values()
            ):
                request_id = str(uuid4())
                session.unsupported[request_id] = UnsupportedRequestNotice(
                    request_id=request_id,
                    user_text=unsupported.user_text,
                    explanation=unsupported.explanation,
                )
        for issue in result.missing_fields:
            if issue.reason == "unsupported" and not any(
                n.field_path == issue.field_path for n in session.unsupported.values()
            ):
                request_id = str(uuid4())
                session.unsupported[request_id] = UnsupportedRequestNotice(
                    request_id=request_id,
                    user_text=issue.clarification_question,
                    explanation=issue.clarification_question,
                    field_path=issue.field_path,
                )
        updates = result.draft.model_dump(exclude_unset=True)
        provided_paths = {key for key in ("start_date", "end_date") if key in updates}
        for traveler_update in updates.get("travelers", []):
            provided_paths.update(
                f"travelers.{traveler_update['traveler_id']}.{key}"
                for key in traveler_update
                if key != "traveler_id"
            )
        reported = {
            item.field_path: item.clarification_question
            for item in result.missing_fields
            if item.reason != "missing"
            or (
                item.field_path not in provided_paths
                and item.field_path
                in {
                    "start_date",
                    "end_date",
                    *(
                        f"travelers.{tid}.{name}"
                        for tid in expected_ids
                        for name in ("origin", "budget_usd", "max_travel_time_hours")
                    ),
                }
            )
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
                        k: v
                        for k, v in value.items()
                        if not any(
                            p == f"{path}.{k}" or p.startswith(f"{path}.{k}.")
                            for p in reported
                        )
                    }
                    for preference_key in valid_preferences:
                        changed_path = f"{path}.{preference_key}"
                        session.issues = {
                            p: q
                            for p, q in session.issues.items()
                            if p != changed_path
                            and not p.startswith(changed_path + ".")
                        }
                        for request_id, notice in list(session.unsupported.items()):
                            if notice.field_path == changed_path:
                                self._defer_request(session, request_id)
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
        if session.draft != previous or session.issues or session.unsupported:
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
        unsupported_paths = {n.field_path for n in session.unsupported.values()}
        questions = {
            p: q for p, q in session.issues.items() if p not in unsupported_paths
        }
        draft = session.draft
        for key in ("start_date", "end_date"):
            if getattr(draft, key) is None:
                questions.setdefault(
                    key,
                    f"What is your exact {key.replace('_', ' ')}, including the year?",
                )
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
            ConversationState.COLLECTING
            if questions or session.unsupported
            else ConversationState.REVIEW
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
            if session.deferred:
                lines.append("Not included, as agreed: " + "; ".join(session.deferred))
            lines.append("Confirm this trip request to find destinations.")
            assistant_message = "\n".join(lines)
        else:
            questions = [q.question for q in self._pending_questions(session)]
            assistant_message = "\n".join(questions)
            if session.unsupported:
                limitations = "\n".join(
                    n.explanation for n in session.unsupported.values()
                )
                assistant_message = (
                    limitations
                    + "\nCan we continue without these unsupported requests?"
                    + ("\n" + assistant_message if assistant_message else "")
                )
        return ConversationTurnResponse(
            session_id=session_id,
            state=session.state,
            assistant_message=assistant_message,
            trip_request_draft=session.draft.model_copy(deep=True),
            missing_fields=session.missing_fields,
            pending_questions=self._pending_questions(session),
            unsupported_requests=[
                n.model_copy(deep=True) for n in session.unsupported.values()
            ],
            deferred_requests=list(session.deferred),
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
