# NbTravelAI

**NbTravelAI** means **No Boundaries, No Bias Travel AI**. It is a
portfolio-focused Applied AI project by Winnie and Ivy that helps two people
who live in different places choose a fair destination for a trip together,
balancing cost, travel time, and preferences.

The first version returns three eligible destinations with transparent score
breakdowns and tradeoffs. A later version will generate and verify a detailed
itinerary for a destination the travelers select.

## At a glance

- **Live model evaluation:** [30/30 cases and 78/78 steps passed](evals/session_runs/live/live-control-guard-v3/summary.md) in a saved DeepSeek run. The [offline suite](evals/session_runs/offline/runner-offline-v4/summary.md) also passed 78/78 steps with mocked responses.
- **Try it:** Run the [local API](#run-the-api-locally) and open its interactive `/docs` page. A public demo URL is not currently configured.
- **Architecture:** Natural language → validated preferences → fixture or provider flight data → deterministic constraints and ranking → explainable recommendations. The v2 prototype adds activity retrieval → itinerary draft → deterministic verifier → bounded revision loop.

The v2 **agent loop** is implemented as a provider-neutral draft/revise callback in `run_itinerary_agent_loop`; a live itinerary model and current activity provider are not yet connected. The current catalog is illustrative fixture data, including opening-day assumptions.

## Project documents

- [Design decisions](docs/design-decisions.md) - accepted architecture decisions,
  rationale, implementation status, and follow-up work.

- [Project proposal](docs/project-proposal.md) - product scope, architecture,
  ranking approach, ownership, and evaluation strategy.
- [Project timeline](docs/project-timeline.md) - completed kickoff work,
  week-by-week deliverables, and acceptance criteria.
- [LLM selection](docs/llm-selection.md) - structured-preference-extraction
  options, selection, benchmark gate, and logging requirements.
- [API outline](docs/api-outline.md) - implemented endpoints, planned
  conversation flow, and internal service boundaries.
- [Flight-offer selection and provider research](docs/flight-offer-selection-and-provider-research.md)
  - Duffel response mapping, flight fixture guidance, and deterministic rules
  for scoring and returning flight choices. Lodging is deferred beyond V1.
- [Preference and request contract](docs/preference-and-request-contract.md)
  - hard constraints, per-traveler preferences, normalization, clarification,
  and preference-scoring rules.
- [Flight search and pairing](docs/flight-search-and-pairing.md) - origin and
  airport resolution, provider-search boundaries, synchronized-arrival pairing,
  and four-category flight selection.
- [Duffel test-mode provider](docs/duffel-flight-provider.md) - sandbox
  configuration, normalization boundary, manual smoke test, and failure policy.
- [Planning origin resolution](docs/planning-origin-resolution.md) - opt-in
  Duffel Places setup, stable location IDs, and OurAirports snapshot refresh.
- [Recommendation response contract](docs/recommendation-response-contract.md)
  - public destination, score, recommended-pair, flight-option, exclusion, and
  metadata fields.

## Current direction

- Exactly two travelers; 3-7 day leisure trips; an initial U.S. city pool.
- Python, FastAPI, Pydantic, pytest, Ruff, Docker, and GitHub Actions.
- Versioned JSON fixtures first, followed by provider interfaces and one live
  provider with a fixture fallback.
- LLMs handle language understanding and grounded explanations only;
  deterministic code handles facts, constraints, calculations, and ranking.

## Run the API locally

Use Python 3.11 or later:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
uvicorn travel_ai.main:app --reload
```

Open `http://127.0.0.1:8000/docs` to try the generated API documentation.

Run quality checks with:

```bash
python -m ruff format --check .
python -m ruff check .
python -m pytest
```

## DeepSeek extraction and planning sessions

The DeepSeek adapter converts messages into validated sparse trip updates. Set
`EXTRACTION_PROVIDER=deepseek` and supply `DEEPSEEK_API_KEY` in the environment
to enable natural-language planning sessions. The default is `fixture`. See
[session configuration and testing](docs/deepseek-planning-sessions.md) and
[adapter behavior](docs/deepseek-preference-extractor.md).

After exporting `DEEPSEEK_API_KEY`, explicitly opt in to the synthetic live cases:

```bash
python -m travel_ai.scripts.deepseek_extract --live
```

Automated extraction tests use mocked HTTP responses and make no network calls.
For repeatable live evaluations, saved results, and comparisons after prompt or
model changes, see the [evaluation guide](evals/preference_extraction/README.md).

## Try the fixture recommendation workflow

With the API running, send this request. It uses the versioned test flights for
June 10–14, 2099; these are mock prices and schedules, not live availability.

```bash
curl -X POST http://127.0.0.1:8000/recommendations \
  -H 'Content-Type: application/json' \
  -d '{"start_date":"2099-06-10","end_date":"2099-06-14","travelers":[{"traveler_id":"alice","origin_id":"boston_ma","budget_usd":500,"max_one_way_travel_minutes":600},{"traveler_id":"bob","origin_id":"new_york_ny","budget_usd":500,"max_one_way_travel_minutes":600}]}'
```

The response contains up to three ranked cities, flight options and category
labels for both travelers, pair-price comparisons, and exclusion reasons.
Dates without fixture flights return `no_match`; unsupported origins return 422.
The endpoint defaults to fixtures and makes no external API calls. Conversational
trip sessions can use fixture extraction or the configured DeepSeek adapter.

## Activity lookup and itinerary prototype

`POST /activities/search` filters illustrative activity fixtures by city, weekday,
tag, neighborhood, and maximum price. Each response carries `fixture_only: true`
and a venue source URL. Fixture hours and prices are **not live availability**;
check them before using the activity in a real trip. Retrieval cases and the
bounded draft → verify → revise agent loop are covered in
`tests/test_activity_itinerary.py`. The verifier rejects unknown activities,
duplicates, and activity-budget overruns, and stops after at most three attempts.
`POST /itineraries/preview` exposes a fixture-only planner using that loop; it
returns activity IDs and verification status, not a timed daily schedule.

## Local AI-call tracing

Set `ENABLE_LOCAL_AI_DASHBOARD=1` before starting the API, then open
`/observability/dashboard` for the local dashboard or
`GET /observability/ai-calls` for its data: recent calls, latency, token counts, and
failure status. This process-local view keeps the last 500 calls and is disabled
by default. It records input/output fingerprints instead of raw traveler text.
Estimated cost is `null` until a verified pricing configuration is added.

## Conversation evaluation and Postman

See the [Postman walkthrough](docs/postman-conversation-walkthrough.md) for the
12-case collection, local execution, and desktop import. The
[evaluation results](evals/conversations/README.md) record the live baseline
and the date-clarification failure with its post-fix verification.

Run the session evaluations offline with one command:

```sh
.venv/bin/python -m travel_ai.scripts.evaluate_sessions
```

See [evaluation runner configuration and report formats](evals/evaluation-runner.md)
for explicit live mode, call limits, and version metadata. Offline passes measure
mocked adapter/session behavior, not model accuracy.
