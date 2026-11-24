"""Generate recommendation explanations only from validated evidence claims."""

from collections import defaultdict
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Protocol

from pydantic import TypeAdapter, ValidationError

from travel_ai.schemas.explanations import (
    DestinationComparisonEvidence,
    DestinationExplanation,
    NoMatchExplanation,
    RankedDestinationEvidence,
    RecommendationExplanationEvidence,
)
from travel_ai.schemas.generated_explanations import (
    DestinationComparisonClaim,
    DestinationFactClaim,
    ExclusionClaim,
    ExplanationClaim,
    FairnessClaim,
    FreshnessClaim,
    RecommendationExplanationSet,
)
from travel_ai.schemas.recommendations import (
    DestinationExclusionReason,
    RecommendationDataMode,
    RecommendationStatus,
)


class ClaimGenerator(Protocol):
    """Boundary for a deterministic or future model-backed claim generator."""

    def __call__(self, evidence: RecommendationExplanationEvidence) -> object:
        """Return untrusted structured claims for validation."""


class UnsupportedExplanationClaim(ValueError):
    """A generated claim is not exactly supported by the supplied evidence."""


_CLAIMS_ADAPTER = TypeAdapter(list[ExplanationClaim])


def generate_default_claims(
    evidence: RecommendationExplanationEvidence,
) -> list[ExplanationClaim]:
    """Select a concise, deterministic set of useful evidence claims."""
    claims: list[ExplanationClaim] = []
    if evidence.status == RecommendationStatus.SUCCESS:
        for destination in evidence.destinations:
            claims.extend(
                [
                    DestinationFactClaim(
                        destination_id=destination.destination_id,
                        fact="rank",
                    ),
                    DestinationFactClaim(
                        destination_id=destination.destination_id,
                        fact="score",
                    ),
                    FairnessClaim(destination_id=destination.destination_id),
                ]
            )
            if len(evidence.destinations) > 1:
                other = (
                    evidence.destinations[1]
                    if destination.rank == 1
                    else evidence.destinations[0]
                )
                for metric in (
                    "combined_price",
                    "combined_travel",
                    "preference_match",
                    "travel_fairness",
                ):
                    claims.append(
                        DestinationComparisonClaim(
                            destination_id=destination.destination_id,
                            other_destination_id=other.destination_id,
                            metric=metric,
                        )
                    )
    else:
        claims.extend(
            ExclusionClaim(**exclusion.model_dump())
            for exclusion in evidence.exclusions
        )
    claims.append(FreshnessClaim())
    return claims


def validate_claims(
    evidence: RecommendationExplanationEvidence,
    raw_claims: object,
) -> list[ExplanationClaim]:
    """Parse claims and reject any target or relation absent from evidence."""
    try:
        claims = _CLAIMS_ADAPTER.validate_python(raw_claims)
    except ValidationError as error:
        raise UnsupportedExplanationClaim(
            "generated claims violate the allowlist"
        ) from error

    destinations = {
        destination.destination_id: destination for destination in evidence.destinations
    }
    exclusions = {
        (item.destination_id, item.traveler_id, item.reason_code)
        for item in evidence.exclusions
    }
    freshness_count = sum(isinstance(claim, FreshnessClaim) for claim in claims)
    if freshness_count != 1:
        raise UnsupportedExplanationClaim("claims require exactly one freshness claim")

    fact_keys: set[tuple[str, str]] = set()
    fairness_ids: set[str] = set()
    exclusion_keys: set[tuple[str, str | None, DestinationExclusionReason]] = set()
    for claim in claims:
        if isinstance(claim, DestinationFactClaim):
            if claim.destination_id not in destinations:
                raise UnsupportedExplanationClaim("destination fact has no evidence")
            fact_keys.add((claim.destination_id, claim.fact))
        elif isinstance(claim, FairnessClaim):
            if claim.destination_id not in destinations:
                raise UnsupportedExplanationClaim("fairness claim has no evidence")
            fairness_ids.add(claim.destination_id)
        elif isinstance(claim, DestinationComparisonClaim):
            destination = destinations.get(claim.destination_id)
            if destination is None or not any(
                item.other_destination_id == claim.other_destination_id
                for item in destination.comparisons
            ):
                raise UnsupportedExplanationClaim("comparison has no evidence")
        elif isinstance(claim, ExclusionClaim):
            key = (claim.destination_id, claim.traveler_id, claim.reason_code)
            if key not in exclusions:
                raise UnsupportedExplanationClaim("exclusion claim has no evidence")
            exclusion_keys.add(key)

    if evidence.status == RecommendationStatus.SUCCESS:
        expected_ids = set(destinations)
        expected_facts = {
            (item, fact) for item in expected_ids for fact in ("rank", "score")
        }
        if (
            fact_keys != expected_facts
            or fairness_ids != expected_ids
            or exclusion_keys
        ):
            raise UnsupportedExplanationClaim(
                "success claims are incomplete or inconsistent"
            )
    elif fact_keys or fairness_ids or exclusion_keys != exclusions:
        raise UnsupportedExplanationClaim(
            "no-match claims are incomplete or inconsistent"
        )
    return claims


class GroundedRecommendationExplainer:
    """Validate untrusted claims, then render text from evidence-owned values."""

    def __init__(self, claim_generator: ClaimGenerator | None = None) -> None:
        self.claim_generator = claim_generator or generate_default_claims

    def explain(
        self, evidence: RecommendationExplanationEvidence
    ) -> RecommendationExplanationSet:
        """Generate grounded text, falling back when custom claims are unsafe."""
        try:
            claims = validate_claims(evidence, self.claim_generator(evidence))
        except (UnsupportedExplanationClaim, TypeError, ValueError):
            claims = validate_claims(evidence, generate_default_claims(evidence))
        return _render_explanations(evidence, claims)


def _render_explanations(
    evidence: RecommendationExplanationEvidence,
    claims: list[ExplanationClaim],
) -> RecommendationExplanationSet:
    freshness = _freshness_note(evidence)
    if evidence.status == RecommendationStatus.NO_MATCH:
        return RecommendationExplanationSet(
            status=evidence.status,
            no_match=_render_no_match(evidence, freshness),
        )

    claims_by_destination: dict[str, list[ExplanationClaim]] = defaultdict(list)
    for claim in claims:
        destination_id = getattr(claim, "destination_id", None)
        if destination_id is not None:
            claims_by_destination[destination_id].append(claim)
    destination_names = {
        destination.destination_id: destination.destination_name
        for destination in evidence.destinations
    }
    return RecommendationExplanationSet(
        status=evidence.status,
        destinations=[
            _render_destination(
                destination,
                claims_by_destination[destination.destination_id],
                freshness,
                destination_names,
            )
            for destination in evidence.destinations
        ],
    )


def _render_destination(
    destination: RankedDestinationEvidence,
    claims: list[ExplanationClaim],
    freshness: str,
    destination_names: dict[str, str],
) -> DestinationExplanation:
    comparisons = {item.other_destination_id: item for item in destination.comparisons}
    tradeoffs = []
    for claim in claims:
        if not isinstance(claim, DestinationComparisonClaim):
            continue
        comparison = comparisons[claim.other_destination_id]
        tradeoffs.append(
            _render_comparison(
                claim.metric,
                comparison,
                destination_names[claim.other_destination_id],
            )
        )
    return DestinationExplanation(
        destination_id=destination.destination_id,
        summary=(
            f"{destination.destination_name} ranks #{destination.rank} with a verified "
            f"overall score of {destination.score:.3f}."
        ),
        tradeoffs=tradeoffs,
        fairness_note=(
            f"Its travel-fairness score is "
            f"{destination.score_breakdown.travel_fairness.value:.3f}. This measures "
            "balance in budget burden, travel-time burden, and arrival timing; it "
            "does not "
            "establish that the trip is fair in every respect."
        ),
        freshness_note=freshness,
    )


def _render_comparison(
    metric: str,
    comparison: DestinationComparisonEvidence,
    other_name: str,
) -> str:
    renderers: dict[str, Callable[[Any], str]] = {
        "score": lambda value: _signed_decimal(value, "overall-score points"),
        "combined_price": lambda value: _signed_money(value),
        "combined_travel": lambda value: _signed_integer(
            value, "combined travel minutes"
        ),
        "preference_match": lambda value: _signed_decimal(
            value, "preference-score points"
        ),
        "travel_fairness": lambda value: _signed_decimal(
            value, "travel-fairness points"
        ),
    }
    values = {
        "score": comparison.score_difference,
        "combined_price": comparison.combined_price_difference_usd,
        "combined_travel": comparison.combined_travel_difference_minutes,
        "preference_match": comparison.preference_match_difference,
        "travel_fairness": comparison.travel_fairness_difference,
    }
    rendered_value = renderers[metric](values[metric])
    return f"Compared with {other_name}, this option is {rendered_value}."


def _signed_money(value: Decimal) -> str:
    amount = abs(value)
    if value < 0:
        return f"${amount:.2f} less expensive in combined fare"
    if value > 0:
        return f"${amount:.2f} more expensive in combined fare"
    return "the same combined fare"


def _signed_integer(value: int, unit: str) -> str:
    if value < 0:
        return f"{abs(value)} fewer {unit}"
    if value > 0:
        return f"{value} more {unit}"
    return f"the same number of {unit}"


def _signed_decimal(value: float, unit: str) -> str:
    if value < 0:
        return f"{abs(value):.3f} lower in {unit}"
    if value > 0:
        return f"{value:.3f} higher in {unit}"
    return f"equal in {unit}"


def _freshness_note(evidence: RecommendationExplanationEvidence) -> str:
    source = {
        RecommendationDataMode.FIXTURE: "fixture/test data",
        RecommendationDataMode.DUFFEL_TEST: "Duffel test data",
        RecommendationDataMode.LIVE: "live provider data",
    }[evidence.freshness.data_mode]
    return (
        f"Based on {source} evaluated at "
        f"{evidence.freshness.evaluated_at.isoformat()} with candidate pool "
        f"{evidence.freshness.candidate_pool_version}."
    )


def _render_no_match(
    evidence: RecommendationExplanationEvidence,
    freshness: str,
) -> NoMatchExplanation:
    reason_codes = {item.reason_code for item in evidence.exclusions}
    guidance = []
    if DestinationExclusionReason.NO_ELIGIBLE_FLIGHT in reason_codes:
        guidance.append(
            "Review the affected travelers' budgets and travel-time limits, or try "
            "different dates or origins."
        )
    if DestinationExclusionReason.NO_COMPATIBLE_FLIGHT_PAIR in reason_codes:
        guidance.append(
            "Try different dates or origins to look for flights that form a "
            "compatible pair."
        )
    if not guidance:
        guidance.append(
            "Change one requested constraint at a time and run the search again."
        )
    return NoMatchExplanation(
        summary=(
            "No candidate destination qualified under both travelers' current verified "
            "constraints."
        ),
        guidance=guidance,
        freshness_note=freshness,
    )
