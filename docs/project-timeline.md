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

## Week 2 - City recommendation and offer-set design

**Goal:** Make the city-level recommendation contract and its supporting data
unambiguous before building the deterministic vertical slice.

- **Shared — flight-pair decision:** document the approved city-level rule: a
  city qualifies when each traveler has at least one flight that satisfies
  their own airfare budget and travel-time limit. Its lowest-combined-airfare
  pair is the reference pair for scoring. The response separately returns up
  to three flights per traveler. Document deterministic option-selection and
  pair tie-breakers, plus recalculation and warning behavior for alternates.
- **Shared — provider-response research:** inspect and save links to official
  flight-provider responses. Map needed fields into the internal `FlightOffer`
  contract; do not expose raw provider JSON to the ranker. Duffel test data can
  inform fixtures. Record the findings in [the flight-offer selection and
  provider research note](flight-offer-selection-and-provider-research.md).
- **Ivy primary — candidate data:** create the initial 10-city candidate pool,
  including controlled city tags and monthly climate data. Identify the gap
  between the current preference vocabulary and Ivy's revised proposal.
- **Winnie primary — preference contract:** reconcile Ivy's approved
  preference schema with `TripRequest` and the controlled vocabulary. Record
  which fields are hard constraints, which are soft preferences, which need a
  clarification question, and which are deferred. Update the Pydantic schema
  only after both contributors approve the contract.
- **Winnie primary — LLM preference feedback experiment:** prepare 10-15
  natural-language preference examples, use the selected LLM to map them to
  proposed controlled tags, and review the results with potential users. Log
  unknown, ambiguous, and unwanted tags; this is research only, not production
  LLM integration.
- **Shared — fixture contracts:** define the three Pydantic fixture schemas:
  `City`, `MonthlyClimate`, and `FlightOffer`. Include fields required to
  represent multiple flight offers per route, dates, source, freshness, and
  stable IDs. Lodging fixtures and contracts are deferred beyond V1.
- **If the above decisions finish early:** add small fixture files and provider
  loaders, then create one request-to-city-offer-set test. Full deterministic
  ranking remains the next milestone.

**Exit criterion:** The team has an approved city recommendation contract,
revised preference contract, 10-city catalog plan, provider-field mapping, and
fixture schemas. One documented example can show exactly what one returned
city and its selectable flight ranges will look like. No live integration,
production LLM workflow, polished database, or frontend is required.

## Week 3 - Constraint engine and explainable ranking

**Goal:** Make the fairness and eligibility decisions explicit and testable.

- Separate hard filters from soft preferences.
- Implement budget, travel-time, date, region, and required-data checks.
- Build eligible city flight sets, select the deterministic reference flight
  pair, and return independently selectable alternate flight offers.
- Implement selected-flight calculations for each person's airfare, combined
  airfare, budget status, travel burden, and fairness; preserve the original
  city ranking when users change choices.
- Return machine-readable reasons for every excluded city.
- Implement and test the normalized scoring baseline: 35% affordability, 30%
  travel fairness, 20% preference match (including climate), and 15% travel
  time. Define missing-data handling and deterministic tie-breaking.
- Test impossible requests, one-result cases, tied scores, missing fields, and
  unequal traveler burden.

**Exit criterion:** The same input and offer snapshot always return the same
top three cities, reference-pair scores, alternate flight ranges, and
exclusion reasons. Every filtered city has a reason, and the constraint and
ranking suite is deterministic and well covered.

## Week 4 - LLM extraction and clarification

**Goal:** Use the LLM only for natural-language handling.

- Convert free-text requests into the validated canonical schema.
- Ask focused clarification questions for missing or ambiguous fields.
- Reject or repair invalid structured model output before it reaches ranking.
- Generate explanations from verified recommendation data only.
- Record prompt version, model, validation outcome, token usage, and latency.

**Exit criterion:** Complete, incomplete, and contradictory requests follow
controlled paths, and the LLM cannot change facts, eligibility, or ranking.

## Week 5 - Live flight-offer integration

**Goal:** Add real data without sacrificing predictable development and tests.

- Confirm flight-provider account access, pricing, rate limits, and permitted
  use of search results.
- Integrate a live flight-offer adapter behind `FlightOfferProvider`.
- Normalize provider responses into the internal offer schemas rather than
  exposing provider-specific JSON to the recommendation engine.
- Add timeouts, limited retries, response validation, error translation,
  caching, rate-limit handling, and freshness timestamps.
- Record representative flight fixtures for local development and CI.
- Test success, timeout, malformed responses, no result, rate limiting, and
  cached fallback behavior.

**Exit criterion:** Live flight offers enrich the estimate, fixture-only mode
still works, tests make no live calls, price freshness is visible, and
provider failures are controlled. Lodging remains deferred beyond V1.

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
