# Travel AI - Project Timeline

**Cadence:** 6-8 hours per person each weekend. Plan work before Saturday,
implement and integrate during the weekend, review each other's changes, and
merge only when the week's acceptance criteria pass.

**Schedule:** Retain the 12-week plan: core demo by Week 10, portfolio package
in Week 11, and protected buffer in Week 12. Week numbers are project milestones,
not newly assigned calendar dates.

## Replanned checkpoint — 2026-09-26

The deterministic recommendation API and fixture-backed planning sessions are
implemented. Sessions support clarification, corrections, normalized review,
explicit confirmation, and repeated-confirmation result reuse. The extraction
contract exists, but extraction still uses scripted fixtures, not a live LLM.
The Duffel test-mode adapter exists separately; the recommendation workflow
currently accepts fixture providers only. A versioned evaluation runner and
report are still needed; passing unit tests does not replace this milestone.

The original Week 4 LLM milestone has slipped. Weeks 5-6 below prioritize a
working LLM-to-fixture-recommendations flow and its evaluation. Full Duffel
workflow integration moves to an optional Week 8 task. Itinerary generation,
lodging, and a learned ranker are not required for the V1 release.

**Extension decision:** No extension beyond Week 12 is planned now. Check the
Week 6 exit criteria together: if they are incomplete, use Week 7 for core
integration/evaluation and defer richer explanations and optional provider work.
At the end of Week 8, reassess against available hours. If core failures still
threaten deployment and the evaluation report, agree on a bounded 1–2 week
extension with named unfinished deliverables; do not silently push dates.

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

**Historical note:** The initial cheapest-reference-pair / three-option design
below was superseded by separate pair and destination scores and up to four
deduplicated flight-option categories. See `flight-search-and-pairing.md` and
`recommendation-response-contract.md` for the current contracts.

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

## Week 4 - Deterministic integration and planning-session foundation

**Status:** Implemented foundation; real LLM extraction carries into Week 5.

- Expanded candidate-pool-aligned flight fixtures and connected constraints,
  pair selection, preference features, ranking, and the recommendation API.
- Defined the extractor interface and partial request/issue contracts.
- Implemented fixture-backed sessions with stable IDs, optional display names,
  saved-field preservation, origin resolution, and validation before review.
- Added structured confirmation, result reuse, and renewed confirmation after
  changes, with regression tests for the agreed planning-session behavior.

**Boundary:** This is a working scripted API flow, not general language
understanding. Sessions are in memory and fixture origins are Boston/New York.

## Week 5 - Real LLM extraction and first end-to-end conversation

**Goal:** Replace scripted extraction with a validated LLM adapter while keeping
flight data and ranking deterministic.

**Winnie, in order**

1. Implement a DeepSeek-backed `PreferenceExtractor` behind dependency injection;
   keep the fixture extractor for offline tests and development.
2. Validate structured output, allowed issue paths, supported preference tags,
   and server-owned traveler IDs. Invalid output must not corrupt saved state.
3. Add timeouts and bounded retry/repair behavior. On failure, preserve the
   draft and return a controlled error; never invent missing values.
4. Connect the adapter to planning sessions, not directly to `/recommendations`.
5. Record prompt/model version, validation outcome, token usage, latency, and
   estimated cost without secrets or unnecessary personal data.

**Ivy, in parallel**

- Draft labeled extraction/conversation and ranking evaluation cases.
- Review expected tags, constraints, pair compatibility, and exclusion reasons.
- Define the baseline: lowest combined airfare among valid pairs/cities,
  enforcing the same hard constraints and deterministic tie-breakers.

**Exit criterion:** A Postman or command-line conversation using ordinary text
can collect details, clarify one missing value, apply a correction, show review,
and return fixture recommendations only after explicit confirmation. Mocked
provider tests cover malformed output, timeout, and failure. No UI, production
flight data, persistent storage, or broad origin coverage is required.

## Week 6 - Working planning session and first evaluation report

**Goal:** Demonstrate and measure the full LLM-to-fixture-recommendations path.
Start the evaluation data in Week 5 rather than leaving it all for this week.

**Winnie**

1. Finish any Week 5 integration gaps and verify multi-turn corrections,
   unsupported/ambiguous input, confirmation, and `no_match` end to end.
2. Add a single evaluation entry point with offline and explicit opt-in LLM
   modes. Routine CI stays offline; actual model evaluation is a separate,
   cost-bounded run using environment credentials.
3. Save per-case results and a summary with dataset/prompt/model versions,
   extraction accuracy, clarification outcomes, failures, latency, and cost.
   Record the actual LLM run; scripted results are not evidence of LLM quality.

**Ivy**

1. Finalize the versioned dataset with at least 50 cases. Suggested split:
   30 extraction/multi-turn scenarios and 20 deterministic recommendation cases.
2. Cover normal, missing, ambiguous, contradictory, impossible, boundary,
   fairness, provider-failure, unsupported-preference, and prompt-injection cases.
3. Compare ranking with the agreed baseline; report hard-constraint violations,
   expected exclusions, and ranking agreement where human labels exist.

**Shared exit checklist — required by the end of Week 6**

- [ ] Real LLM extraction works through the planning-session API with fixture
  flights; a frontend is not required.
- [ ] Complete, incomplete, corrected, and no-match conversations work; no
  recommendation runs before confirmation and repeat confirmation reuses results.
- [ ] One command runs at least 50 versioned cases and saves per-case results
  plus category summaries; a separate opt-in run measures real LLM extraction.
- [ ] A baseline comparison and failure taxonomy are saved. Known material
  failures have regression tests or tracked issues; results are not cherry-picked.
- [ ] The deterministic evaluation has zero hard-constraint violations and
  confirmation-gate failures. Report observed LLM accuracy; agree on a release
  threshold after this first measured run rather than inventing a success claim.
- [ ] Both contributors can reproduce the demo and offline evaluation.

**Not required:** Duffel workflow integration, arbitrary origin geocoding,
database-backed sessions, polished UI, itinerary generation, or lodging.

## Week 7 - Grounded recommendation explanations

**Goal:** Make results clear without introducing unsupported facts.

- Pass only verified score, cost, travel, preference, and freshness data to
  the explanation step.
- Validate that explanations remain within that evidence.
- Improve explanation templates, tradeoff language, and no-result guidance.
- Add regression cases for unsupported claims and misleading fairness wording.

**Exit criterion:** Users can understand why destinations ranked as they did,
and explanation quality is measured rather than assumed.

## Week 8 - Evaluation fixes and optional Duffel test-mode workflow

**Goal:** Close measured V1 gaps before expanding the data path.

- First fix material extraction, session, constraint, and ranking failures from
  the evaluation report; expand toward 75–100 cases by portfolio release.
- Only if Week 6 acceptance is met, wire the existing Duffel test adapter into
  the workflow with explicit provider mode, origin resolution, timeouts, bounded
  retries, rate-limit handling, and response validation.
- Keep CI offline. Test failures and fallback behavior without network calls;
  never silently present fixture fallback as current provider prices.
- Label Duffel sandbox schedules/prices as test data, not realistic estimates.

**Exit criterion:** Material V1 failures are resolved or explicitly bounded. Any
enabled external-data mode has controlled failures and visible source metadata.
Provider integration is optional and must not delay the evaluated core demo.

**Deferred to V2:** Itinerary generation/verifier and lodging. These are no
longer Week 8 acceptance criteria.

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
