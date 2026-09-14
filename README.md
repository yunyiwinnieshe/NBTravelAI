# Travel AI

Travel AI is a portfolio-focused Applied AI project by Winnie and Ivy. It
helps two people who live in different places choose a fair destination for a
trip together, balancing cost, travel time, and preferences.

The first version returns three eligible destinations with transparent score
breakdowns and tradeoffs. A later version will generate and verify a detailed
itinerary for a destination the travelers select.

## Project documents

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
