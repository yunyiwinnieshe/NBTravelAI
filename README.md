# Travel AI

Travel AI is a portfolio-focused Applied AI project by Winnie and Ivy. It
helps two people who live in different places choose a fair destination for a
trip together, balancing cost, travel time, and preferences.

The first version returns three eligible destinations with transparent score
breakdowns and tradeoffs. A later version will generate and verify a detailed
itinerary for a destination the travelers select.

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
The endpoint defaults to fixtures and makes no external API calls. Live provider
integration and conversational trip sessions remain follow-up work.
