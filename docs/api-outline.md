# Travel AI - API Outline

**Status:** `GET /health` and fixture-backed `POST /recommendations` are
implemented. Conversation endpoints remain explicit `501` stubs until session
storage and the LLM workflow are added. Live recommendation integration is pending.

## Design principle

The conversational interface is the user-facing planning flow. It calls the
LLM internally to extract and clarify preferences, then calls deterministic
recommendation code once the request is complete. The frontend never calls an
LLM-provider API directly.

The direct recommendation endpoint remains useful for automated evaluation,
API testing, and a future structured form. It accepts only a complete,
validated `TripRequest` whose origins have already been resolved to canonical
IDs. The conversation flow owns free-text origin clarification and resolution.
The planned live resolver will assign and persist internal location IDs after
confirmation, reusing the record for the same place. This storage integration
is not implemented yet. Readable origin IDs in examples remain test identifiers;
see [the origin-ID decision](design-decisions.md).

## Implemented endpoints

### `GET /health`

Returns whether the API process is running. Deployment platforms and local
checks use this endpoint; it is not part of travel planning.

```json
{"status": "ok"}
```

### `POST /recommendations`

Accepts a complete structured trip request and returns up to three ranked
destinations using the real constraint engine, pair selector, and destination
ranker over fixtures. Both success and no-match results return HTTP 200. Invalid
requests or unsupported fixture origins return HTTP 422. Provider/data failures
are not converted into a misleading no-match result.

Fixture searches support Boston (`boston_ma`) and New York (`new_york_ny`) for
June 10–14, 2099. Other valid dates return no matches. Traveler IDs are
request-specific and need not be `traveler_a` or `traveler_b`.

```json
{
  "travelers": [
    {
      "traveler_id": "traveler_a",
      "origin_id": "boston_ma",
      "budget_usd": 2000,
      "max_one_way_travel_minutes": 480,
      "preferences": {
        "temperature_range": {
          "minimum_celsius": 20,
          "maximum_celsius": 30
        },
        "interest_tags": ["food", "museums"]
      }
    },
    {
      "traveler_id": "traveler_b",
      "origin_id": "new_york_ny",
      "budget_usd": 1800,
      "max_one_way_travel_minutes": 420,
      "preferences": {
        "interest_tags": ["nature", "outdoor_activities"]
      }
    }
  ],
  "start_date": "2099-06-10",
  "end_date": "2099-06-14"
}
```

The canonical hard-constraint and preference rules are in the
[preference and request contract](preference-and-request-contract.md). This
example represents the implemented confirmed request contract.

The finalized success/no-match response shape is defined in the
[recommendation response contract](recommendation-response-contract.md).

## Planned conversation endpoints

### `POST /trip-sessions`

Starts a travel-planning conversation. The response will create a server-owned
`session_id` that identifies later messages from the same planning session.
The contract accepts an optional first message. The endpoint is currently a
`501 Not Implemented` stub because storage is not part of the current backend
milestone.

### `POST /trip-sessions/{session_id}/messages`

Receives one natural-language user message and returns the next turn of the
conversation. The endpoint is currently a `501 Not Implemented` stub. When
implemented, it will internally:

1. Loads the session's existing preference draft.
2. Uses the preference-extraction service when language interpretation is
   needed.
3. Validates the resulting draft against the canonical trip schema.
4. Returns a clarification, a review request, deterministic results, or a
   no-match explanation.

The response has one concise state:

- `collecting`: required information is still missing or ambiguous.
- `review`: the system parsed the request and asks the user to verify it.
- `results`: a complete request produced ranked destinations.
- `no_match`: no destination satisfies the hard constraints.

Example clarification response:

```json
{
  "session_id": "trip_session_123",
  "state": "collecting",
  "assistant_message": "What dates are you considering, and what is each person's budget and maximum travel time?",
  "missing_fields": ["start_date", "end_date", "budget_usd", "max_travel_time_hours"]
}
```

Example result response:

```json
{
  "session_id": "trip_session_123",
  "state": "results",
  "assistant_message": "Here are the destinations that best balance cost and travel fairness.",
  "recommendations": [
    {"destination_id": "san_diego_ca", "destination_name": "San Diego", "score": 0.84}
  ]
}
```

## Internal interfaces, not public HTTP endpoints

The following are Python services or provider interfaces, not URLs the client
calls directly:

```text
PreferenceExtractionService → LlmClient
RecommendationService → DestinationCatalogProvider
RecommendationService → FlightOfferProvider
RecommendationService → ClimateProvider
RecommendationService → ConstraintEngine → Ranker
```

This keeps language understanding, external data access, and deterministic
ranking independently testable and replaceable.

## Next implementation boundaries

The fixture workflow connects providers, constraints, pair selection, preference
calculation, and ranking to the finalized response. Remaining work is live origin
resolution/storage, live provider warning/error handling, and conversation/LLM
integration. `get_recommendation_service` is an overridable FastAPI dependency;
the default service is cached and uses fixtures without network calls.

## API integration coverage

`tests/test_recommendations_api.py` sends requests through FastAPI's in-process
`TestClient` and runs the real fixture workflow. With June 10–14, 2099 dates and
a 600-minute one-way limit, per-person budgets of $500, $300, $260, and $1 yield
three, two, one, and zero eligible cities, respectively.

The suite verifies response-schema validation, consecutive ranks, eligible
counts, traveler and pair exclusion reasons, and HTTP 422 for malformed
requests before workflow execution. A fixed injected clock permits exact JSON
comparison across repeated requests, including an interleaved no-match request.
In normal execution, `metadata.evaluated_at` changes on each evaluation.

The module blocks Duffel operations, real HTTP transports, and outbound socket
connections. A separate test exercises the default service dependency with no
Duffel credentials. These tests require no live API access; the existing
router and dependency wiring are reused.

### Provider boundary and diagnostics

Flight providers declare `data_mode` before any search. This fixture workflow
rejects live providers during construction and rechecks the mode before each
request. It also rejects non-fixture offers returned by a provider that claims
fixture mode. Live providers are not enabled by this interface addition.

For every rejected offer, the service emits an INFO-level
`recommendation_offer_rejected` log record with `traveler_id`, `destination_id`,
`offer_id`, and `reason_codes` as structured attributes. Configure the
`travel_ai.services.recommendation_service` logger at INFO and a formatter that
includes these attributes to collect them. Full requests and provider payloads
are not logged by this event. Public exclusions remain city/traveler-level.

Unexpected provider failures propagate as HTTP 500, not successful `no_match`
responses; internal exception details are not included in the default response.
API coverage verifies this behavior with a failing injected provider.
