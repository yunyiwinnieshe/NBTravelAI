# Travel AI - Project Timeline

**Cadence:** 6-8 hours per person each weekend. Plan work before Saturday,
implement and integrate during the weekend, review each other's changes, and
merge only when the week's acceptance criteria pass.

**Schedule:** Week 0 kickoff is complete. Weeks 1-10 deliver the core
portfolio project; Weeks 11-12 are buffer time or an optional learned-ranking
extension.

## Week 0 - Kickoff and project decisions (complete)

**Completed decisions**

- Renamed the working project from Rendezvous AI to **Travel AI**.
- Defined the product: help exactly two travelers who live in different places
  select a fair destination based on cost, travel burden, and preferences.
- Limited v1 to 3-7 day leisure trips and a controlled 15-25 city U.S. pool.
- Chose fixture data first, provider interfaces, and a later live provider with
  fixture fallback.
- Established the LLM/deterministic boundary and explicit non-goals.
- Agreed on Python, FastAPI, Pydantic, pytest, Ruff, Docker, and GitHub
  Actions as the current stack.
- Assigned ownership areas and created the initial repository.

**Exit criterion:** The proposal, timeline, ownership, scope, and engineering
principles are recorded in the repository.

## Week 1 - Contracts, fixtures, and service skeleton

**Goal:** Define stable interfaces before making the recommendation intelligent.

- Finalize `TripRequest`, traveler preference, and recommendation-response
  Pydantic schemas.
- Define the controlled candidate pool and JSON fixture-data contracts.
- Create the FastAPI app with `/health` and a placeholder `/recommendations`
  endpoint.
- Add project structure, pytest, Ruff, GitHub Actions, `.env.example`, and an
  initial Docker configuration.
- **Winnie:** document the MVP scope, non-goals, candidate-pool approach,
  preference vocabulary, key decisions, and initial example requests.
- **Winnie:** compare 2-3 LLM options for structured-output support, cost,
  latency, Python SDK ergonomics, and logging. Record the selected model and
  benchmark gate for structured extraction only; do not integrate it yet.

**Ownership:** Winnie leads API and request/response contracts. Ivy leads
destination/provider contracts and ranking-feature definitions. Both review
architecture and acceptance criteria.

**Exit criterion:** Both contributors can clone the repository, run the API,
submit a valid request, receive a useful validation error for an invalid one,
and see CI pass. The documented v1 decisions and LLM selection are reviewed
and approved by both contributors.

## Week 2 - Deterministic top-three recommendation flow

**Goal:** Ship the first end-to-end vertical slice using fixtures only.

- Create initial city, weather, route-estimate, and trip-cost fixture data.
- Reconcile and approve the per-traveler hard-constraint and preference
  contract in [preference-and-request-contract.md](preference-and-request-contract.md)
  before changing Pydantic request schemas.
- Load the controlled candidate pool for each request.
- Filter basic hard-constraint violations.
- Implement normalized baseline features and deterministic top-three ranking.
- Return scores, component breakdowns, per-traveler burden, and rejection
  reasons.
- Add at least five end-to-end test requests.

**Exit criterion:** The same input always returns the same explained top-three
results. No LLM, live provider, polished database, or frontend is required.

## Week 3 - Constraint engine and explainable ranking

**Goal:** Make the fairness and eligibility decisions explicit and testable.

- Separate hard filters from soft preferences.
- Implement budget, travel-time, date, region, and required-data checks.
- Return machine-readable reasons for every excluded city.
- Define normalization, weights, missing-data handling, and deterministic
  tie-breaking.
- Test impossible requests, one-result cases, tied scores, missing fields, and
  unequal traveler burden.

**Exit criterion:** Every recommendation has an auditable score breakdown;
every filtered city has a reason; the constraint and ranking suite is
deterministic and well covered.

## Week 4 - LLM extraction and clarification

**Goal:** Use the LLM only for natural-language handling.

- Convert free-text requests into the validated canonical schema.
- Ask focused clarification questions for missing or ambiguous fields.
- Reject or repair invalid structured model output before it reaches ranking.
- Generate explanations from verified recommendation data only.
- Record prompt version, model, validation outcome, token usage, and latency.

**Exit criterion:** Complete, incomplete, and contradictory requests follow
controlled paths, and the LLM cannot change facts, eligibility, or ranking.

## Week 5 - One live provider with fixture fallback

**Goal:** Add real data without sacrificing predictable development and tests.

- Select and integrate one practical provider (for example, weather, route, or
  airport data) behind an internal adapter.
- Add timeouts, limited retries, response validation, error translation,
  caching, rate-limit handling, and freshness timestamps.
- Record representative provider fixtures for local development and CI.
- Test success, timeout, malformed responses, no result, rate limiting, and
  cached fallback behavior.

**Exit criterion:** One live provider enriches the system, fixture-only mode
still works, tests make no live calls, and provider failures are controlled.

## Week 6 - Evaluation suite and baseline comparison

**Goal:** Measure quality instead of relying on a polished demo.

- Build a versioned evaluation set with at least 50 cases; target 75-100 by
  the portfolio release.
- Cover normal, ambiguous, impossible, boundary, provider-failure, fairness,
  prompt-injection, and unsupported-claim cases.
- Measure extraction quality, hard-constraint violations, ranking agreement,
  unsupported claims, reliability, latency, and estimated cost.
- Compare the system against at least one simple baseline.
- Create a failure taxonomy and turn material failures into issues or
  regression tests.

**Exit criterion:** A single command runs the evaluation set and produces
saved results plus a category-level summary.

## Week 7 - Grounded recommendation explanations

**Goal:** Make results clear without introducing unsupported facts.

- Pass only verified score, cost, travel, preference, and freshness data to
  the explanation step.
- Validate that explanations remain within that evidence.
- Improve explanation templates, tradeoff language, and no-result guidance.
- Add regression cases for unsupported claims and misleading fairness wording.

**Exit criterion:** Users can understand why destinations ranked as they did,
and explanation quality is measured rather than assumed.

## Week 8 - Itinerary generation and deterministic verifier

**Goal:** Add the v2 direction only after the recommendation decision is solid.

- Let users choose one recommended destination.
- Generate a structured daily itinerary from verified activity data.
- Verify date alignment, schedule overlap, budget, travel plausibility,
  availability assumptions, and evidence links.
- Permit at most one controlled regeneration after a verifier failure.
- Clearly label partial verification or remaining warnings.

**Exit criterion:** Intentionally invalid itinerary examples are caught, and
unsupported activities or claims are rejected or warned about.

## Week 9 - Reliability, tracing, and safe fallbacks

**Goal:** Demonstrate production-minded operation.

- Trace extraction, provider calls, constraints, ranking, explanation, and
  response stages.
- Record latency, errors, cache behavior, retries, model/provider versions,
  token usage, estimated cost, and validation results.
- Add safe degradation: structured input when extraction fails, fixture/cache
  fallback for live data, score-only results when explanations fail, and clear
  no-result guidance.
- Run failure-injection tests and ensure logs avoid secrets or unnecessary
  personal data.

**Exit criterion:** A request can be followed through all stages and expected
model or provider failures do not crash the service.

## Week 10 - Demo UI and deployment

**Goal:** Make the tested system easy for a recruiter to try.

- Build a minimal interface for request entry, extracted-field confirmation,
  top-three comparison, scores, warnings, and destination selection.
- Finalize a production Dockerfile, environment configuration, health checks,
  and deployment.
- Add basic rate limiting, spending limits, and a clean-browser test.
- Verify accessible loading, error, source, and estimate states.

**Exit criterion:** A new user can complete the core workflow in the deployed
demo and the documented commit matches what is running.

## Week 11 - Portfolio package

**Goal:** Turn the implementation into a credible interview artifact.

- Complete the README, architecture diagram, decision log, evaluation report,
  API documentation, example requests/responses, and limitations.
- Record a 2-3 minute demo video and capture screenshots.
- Write individual contribution statements and evidence-backed resume bullets.
- Prepare interview explanations for LLM boundaries, ranking, evaluation,
  provider failures, and production tradeoffs.

**Exit criterion:** A recruiter can understand the problem and engineering
approach quickly, while a technical interviewer can reproduce the claims.

## Week 12 - Buffer or optional learned-ranker experiment

**Default:** Use this week as buffer if any core milestone needs work.

**Optional Ivy-led extension, only if the core release is stable:**

- Build a versioned pairwise-preference dataset.
- Compare logistic regression or gradient-boosted trees with the explainable
  weighted baseline using held-out requests, pairwise accuracy, and NDCG@3.
- Track data, feature, code, hyperparameter, and model versions.
- Serve any model behind the existing ranking interface with deterministic
  fallback and a model card.

**Exit criterion:** Either the core project is strengthened with buffer time,
or the learned ranker is reproducible, evaluated fairly, and adopted only if
it demonstrably improves the baseline.

## Priority if the schedule slips

Protect work in this order:

1. Typed end-to-end API.
2. Fixture-based recommendation flow.
3. Deterministic constraints and explainable ranking.
4. Structured LLM extraction.
5. Automated evaluation.
6. Grounded explanations.
7. Deployment and documentation.
8. Itinerary generation.
9. Live providers.
10. Learned ranker.

A smaller system that is deployed, evaluated, measurable, and reliable is
more valuable to the portfolio than a broader but unfinished travel product.
