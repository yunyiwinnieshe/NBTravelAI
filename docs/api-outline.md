# Travel AI - API Outline

**Status:** `GET /health` is implemented. The request and response contracts
for `POST /recommendations` are finalized, but recommendation generation still
returns `501 Not Implemented` until the provider and ranking services are
connected. The conversation endpoints are also explicit `501` stubs until
session storage and the LLM workflow are added.

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

Accepts a complete structured trip request and will return up to three
deterministically ranked destinations. It currently validates the request and
then returns `501 Not Implemented`; it does not return a fake successful result.

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
      "origin_id": "san_francisco_ca",
      "budget_usd": 1800,
      "max_one_way_travel_minutes": 420,
      "preferences": {
        "interest_tags": ["nature", "outdoor_activities"]
      }
    }
  ],
  "start_date": "2026-10-09",
  "end_date": "2026-10-13"
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

The next implementation connects fixture providers, constraints, pair
selection, and ranking to the finalized response. The session endpoints and
LLM integration remain later work after the deterministic flow is working.
