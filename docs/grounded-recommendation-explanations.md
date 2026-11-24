# Grounded recommendation explanation contract

**Status:** Explanation contracts, verified evidence assembly, deterministic text
generation, claim validation, and API/session wiring are implemented.

Recommendation explanations are downstream of deterministic eligibility,
flight-pair selection, and destination ranking. They may describe a result but
must never change its scores, selected flights, eligibility, or rank.

## User-facing contract

A ranked destination explanation contains:

- a concise summary;
- up to four ranking tradeoffs;
- an optional fairness note; and
- a required freshness note.

A no-match explanation contains a summary, one to four bounded next steps, and
a freshness note. These models reject unknown fields, blank list items, and
duplicate statements. Generated prose is rendered only after typed claims are validated against the
allowlisted evidence.

## Allowlisted evidence

`build_explanation_evidence()` accepts only a validated `TripRequest` and its
validated `RecommendationResponse`. It produces a
`RecommendationExplanationEvidence` containing:

- exact trip dates;
- each traveler's origin, budget, one-way time limit, and requested preferences;
- destination rank, score, and the published score breakdown;
- selected-pair prices, travel minutes, connections, alignment, and time together;
- selected flight facts and derived budget utilization for each traveler;
- signed score, price, travel-time, preference, and fairness comparisons between
  returned destinations;
- public destination exclusion reasons; and
- evaluation timestamp, candidate-pool version, and fixture/live data mode.

Unknown fields are forbidden throughout the evidence tree. The builder fails if
a recommended traveler or selected offer cannot be reconciled with the confirmed
request and response.

## Preference boundary

The confirmed request proves which preferences a traveler asked for. The current
recommendation response proves only the aggregate destination preference-match
score. It does not publish the exact interest tags that matched a destination.

Consequently, the evidence keeps `requested_preferences` separate from the
verified `preference_match` score. A future explanation may say that one city has
a stronger verified preference match than another. It must not claim that a city
matches a particular requested tag until exact matched-tag evidence is added to
the deterministic ranking output.

## Comparison signs

Each destination comparison is calculated as `this destination - other
destination`. A negative price or travel-time difference means this destination
is cheaper or requires less combined travel. A positive score, preference, or
fairness difference means this destination has the higher verified value.

## Generation and validation

The V1 generator emits typed claims for ranks, scores, comparisons, fairness,
freshness, and exact exclusions. Claims with unknown fields, unsupported fact types,
missing destinations, or unrecorded comparisons are rejected. A custom or future
model-backed generator that returns unsafe claims falls back to the deterministic
generator; renderers always read values from evidence rather than generated text.
If evidence assembly or rendering fails, the response returns the validated
ranking with `explanations: null`.

Fairness wording is explicitly bounded to budget burden, travel-time burden, and
arrival timing. No-match guidance suggests possible constraint changes without
promising that a change will produce a result. Fixture and live freshness wording
remain distinct.

## Evidence-based evaluation

The versioned offline suite in [evals/explanations](../evals/explanations/README.md)
covers ranked tradeoffs, constrained results, empty preferences, no-match guidance,
and rejection of an unsupported safety claim. The saved V1 run passed 5/5 cases
and 61/61 checks. Its JSON report retains each request, exact evidence, generated
text, check results, source hashes, and fixture-only run metadata.

Reproduce it from the repository root:

    .venv\Scripts\python.exe -m travel_ai.scripts.evaluate_explanations

This establishes grounding for the covered synthetic cases. It does not measure
human persuasiveness, destination desirability, live-provider freshness, LLM
quality, or production reliability.

## Out of scope for V1

- generating explanation claims with an LLM; and
- human preference or persuasion evaluation.
