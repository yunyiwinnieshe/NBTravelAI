"""Interfaces and deterministic fixtures for preference extraction."""

from abc import ABC, abstractmethod

from travel_ai.schemas.preference_extraction import PreferenceExtractionResult
from travel_ai.schemas.sessions import TripRequestDraft


class PreferenceExtractor(ABC):
    """Extract a structured draft without deciding recommendation results."""

    @abstractmethod
    def extract(
        self,
        user_message: str,
        current_draft: TripRequestDraft,
    ) -> PreferenceExtractionResult:
        """Return sparse updates for both assigned traveler IDs.

        Omit unmentioned fields. Omit invalid/ambiguous values and report them
        in missing_fields using start_date/end_date or
        travelers.<traveler_id>.<field> paths. Names are labels, not identity:
        ambiguous references require clarification. The service merges valid
        updates and independently determines readiness.
        """


class FixturePreferenceExtractor(PreferenceExtractor):
    """Return predefined extraction results for deterministic unit tests."""

    def __init__(
        self, results_by_message: dict[str, PreferenceExtractionResult]
    ) -> None:
        self._results_by_message = results_by_message

    def extract(
        self,
        user_message: str,
        current_draft: TripRequestDraft,
    ) -> PreferenceExtractionResult:
        """Return the matching fixture result without calling an LLM provider."""
        del current_draft
        try:
            return self._results_by_message[user_message].model_copy(deep=True)
        except KeyError as error:
            raise ValueError(
                "no fixture extraction result is configured for this user message"
            ) from error
