"""Tests for the LLM-independent preference-extraction contract."""

import pytest
from pydantic import ValidationError

from travel_ai.schemas.preference_extraction import (
    MissingField,
    MissingFieldReason,
    PreferenceExtractionResult,
    PreferenceExtractionStatus,
)
from travel_ai.schemas.sessions import TripRequestDraft
from travel_ai.services.preference_extraction import FixturePreferenceExtractor


def test_incomplete_extraction_identifies_a_missing_canonical_field() -> None:
    """An incomplete result makes the next clarification explicit and typed."""
    result = PreferenceExtractionResult(
        draft=TripRequestDraft(),
        status=PreferenceExtractionStatus.NEEDS_CLARIFICATION,
        missing_fields=[
            MissingField(
                field_path="start_date",
                reason=MissingFieldReason.MISSING,
                clarification_question="What date would you like to leave?",
            )
        ],
    )

    assert result.status == PreferenceExtractionStatus.NEEDS_CLARIFICATION
    assert result.missing_fields[0].field_path == "start_date"


def test_ready_extraction_cannot_claim_unresolved_fields() -> None:
    """Review is only possible when the extractor reports no unresolved fields."""
    with pytest.raises(ValidationError, match="ready_for_review"):
        PreferenceExtractionResult(
            draft=TripRequestDraft(),
            status=PreferenceExtractionStatus.READY_FOR_REVIEW,
            missing_fields=[
                MissingField(
                    field_path="travelers[0].origin",
                    reason=MissingFieldReason.AMBIGUOUS,
                    clarification_question="Which Portland do you mean?",
                )
            ],
        )


def test_fixture_extractor_returns_a_copy_of_the_configured_result() -> None:
    """Tests can use a predictable extractor without reaching a model provider."""
    configured_result = PreferenceExtractionResult(
        draft=TripRequestDraft(),
        status=PreferenceExtractionStatus.NEEDS_CLARIFICATION,
        missing_fields=[
            MissingField(
                field_path="travelers",
                reason=MissingFieldReason.MISSING,
                clarification_question="Where is each traveler leaving from?",
            )
        ],
    )
    extractor = FixturePreferenceExtractor({"We want to meet up.": configured_result})

    result = extractor.extract("We want to meet up.", TripRequestDraft())
    result.missing_fields.clear()

    assert configured_result.missing_fields
    assert result is not configured_result


def test_fixture_extractor_rejects_an_unconfigured_message() -> None:
    """A missing fixture is explicit rather than silently behaving like an LLM."""
    extractor = FixturePreferenceExtractor({})

    with pytest.raises(ValueError, match="no fixture extraction result"):
        extractor.extract("Where should we go?", TripRequestDraft())
