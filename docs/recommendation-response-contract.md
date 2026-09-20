# Travel AI Recommendation Response Contract

**Status:** Pydantic contract implemented; service population remains a
follow-up task
**Scope:** The public success and no-match response from `POST /recommendations`

## Response structure

```text
RecommendationResponse
├── status: success | no_match
├── recommendations: up to 3 DestinationRecommendation objects
│   ├── rank and destination
│   ├── score and score_breakdown
│   ├── recommended_pair
│   │   ├── one offer reference per traveler
│   │   ├── combined price and compatibility metrics
│   │   ├── pair-selection score and component breakdown
│   │   └── comparison with the cheapest valid pair
│   └── flight_options_by_traveler
│       └── 1–4 distinct category-winning FlightOption objects per traveler
├── exclusions
└── metadata
```

The API uses a compact `FlightOption` model. Provider-only details and raw
Duffel payloads stay inside the provider layer.

## Recommended pair and city score

Each destination has one recommended pair containing one eligible round-trip
offer for each traveler. Every valid pair is scored using price, arrival
alignment, travel time, connections, and time together. No fixed percentage
price guardrail removes a pair before scoring. The highest-scoring pair is
selected, followed by deterministic cost, travel-time, arrival-gap, connection,
shared-trip, and stable-ID tie-breakers.

The pair-selection score is published separately from the destination score.
It explains why two flights were paired within one city; it is not added to the
destination score.

The destination's affordability, travel-fairness, preference-match, and
travel-time features are calculated from the recommended pair. Their fixed V1
weights are:

- affordability: 35%;
- travel fairness: 30%;
- preference match: 20%; and
- travel time: 15%.

Travel fairness is itself transparent: 50% duration balance, 30% airfare-budget
burden balance, and 20% arrival alignment. These values compare the two
travelers, while the top-level travel-time score represents their total travel
burden. Duration balance uses each traveler's longer one-way duration divided
by their own time limit, rather than the raw difference in hours. When neither
traveler has preferences, the preference weight is zero and the other weights
are proportionally redistributed. See [Ranking input contract](ranking-input-contract.md)
for exact formulas, rounding, and destination tie-breaks.

The response exposes the recommended pair's combined price. Its
`price_comparison` also provides the cheapest valid combined price and the
recommended pair's premium in dollars and percentage. It does not expose the
cheapest pair's offer IDs because that pair is an explanation baseline, not a
second recommendation. The premium percentage is informational and may exceed
50%; it is not a constraint.

## Four selection categories per traveler

For each traveler, the response evaluates four round-trip flight categories in
this order:

1. the offer used by `recommended_pair`;
2. the lowest-price eligible offer;
3. the shortest-total-travel-time eligible offer; and
4. the fewest-connections eligible offer.

Duplicate winners are returned once and carry multiple labels. The selector
does not backfill another flight merely to reach four results. Consequently,
the response can contain fewer than four distinct options even when additional
eligible offers exist.

For example:

```text
Traveler A
├── A2: recommended_pair + fewest_connections
├── A1: lowest_price
└── A3: shortest_travel
```

Every option publishes its own round-trip price. The recommended pair publishes
the sum of its two selected offer prices. If customers choose a different pair
from the independent lists, the application recalculates the combined price
and compatibility metrics; it does not silently change the destination score.

## Exclusions and metadata

`exclusions` contains stable city-level reason codes. V1 begins with
`no_eligible_flight`; internal offer-level failures remain logs rather than
expanding the public response.

`metadata` records the evaluation timestamp, candidate-pool version, either
`fixture` or `live` data mode, and the number of eligible destinations. These fields make
test results and demonstrations reproducible.

## Endpoint state before service integration

The response contract represents completed recommendation work and therefore
contains only `success` and `no_match`. Until the recommendation service can
populate this contract from real constraints and ranking, the HTTP endpoint
returns `501 Not Implemented` instead of a `200` placeholder response.
