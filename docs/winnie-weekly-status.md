# Winnie's Travel AI weekly status

This document records the project’s weekly outcomes, key decisions, and remaining work. Update the current week as tasks are completed and add a new section at the start of each week.

## Week 1 — Project foundation

**Status:** completed

- Renamed the project to **Travel AI** and clarified its purpose: help two people travelling from different places find a fair shared destination.
- Defined the MVP, non-goals, ownership, technical direction, and 12-week timeline in the project proposal.
- Chose a deterministic-first design: the LLM extracts and clarifies preferences; code validates data, applies constraints, scores, ranks, and explains verified results.
- Chose DeepSeek as a low-cost option for early structured-preference experiments; it is not part of the deterministic recommendation path.
- Created the FastAPI project skeleton with `/health` and placeholder `/recommendations` endpoints, Pydantic schemas, pytest, Ruff, GitHub Actions CI, and Docker support.

## Week 2 — Contracts, data research, and offer-selection design

**Status:** completed

- Defined the canonical trip-request and preference design, including hard constraints, soft preferences, controlled interest tags, temperature preferences, clarification behavior, and unsupported-preference handling.
- Defined the candidate-pool approach: versioned city and monthly-climate fixture data for supported U.S. destinations.
- Researched Duffel test-mode flight responses, inputs, airport lookup, and normalized internal flight-offer fields.
- Narrowed V1 to **flight-only recommendations**. Lodging remains out of scope until reliable provider access and fixture coverage are available.
- Documented deterministic offer filtering, traveler flight-pair construction, option categories, tie-breaking, and customer mix-and-match behavior.

## Week 3 — Flight contracts and recommendation response

**Status:** completed, except the Duffel provider PR is awaiting merge

- **Trip request contract — merged**
  - Exactly two travelers with distinct origins and IDs.
  - Per-traveler budget, maximum travel time, interests, and temperature preference.
  - Trips must be future-dated and 3–7 days long.

- **Flight offers and pair selection — merged**
  - Added normalized round-trip flight models and a fixture provider.
  - Builds every valid Traveler A × Traveler B pair.
  - Scores pairs using price, arrival alignment, travel time, connections, and time together.
  - Requires both travelers to arrive at the same destination airport.
  - Returns recommended, lowest-price, shortest-time, and fewest-connection options.

- **Recommendation response contract — merged**
  - Defined the public `RecommendationResponse`.
  - Includes ranked destinations, destination score breakdown, recommended pair, flight options, and exclusions.
  - Keeps internal provider fields out of the customer response.

- **Duffel test-mode provider — awaiting merge into `main`**
  - Searches round-trip flights and normalizes Duffel responses.
  - Handles timezone-less Duffel timestamps.
  - Supports airport lookup, partial failures, deduplication, and the 20-offer limit.
  - Its branch is synchronized with `main`, but `origin/main` does not yet contain it.

### Key architectural decision

Travel AI now uses two separate scoring stages:

1. **Flight-pair score:** selects the best compatible pair within one city.
2. **Destination score:** compares cities using affordability, fairness, preferences, and travel time.

## Week 4 — In progress

**Planned focus:** expand flight fixtures, build the fixture-backed recommendation workflow, connect it to FastAPI, and define the LLM extraction contract without integrating a live model.

### Update template

- **Completed:**
- **In review:**
- **Blocked or open decisions:**
- **Next week:**
