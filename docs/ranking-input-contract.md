# Confirmed Trip Request and Ranking Input Contract

This document separates the confirmed, normalized user request from the
provider and fixture data assembled for deterministic ranking. V1 recommends
destinations using flights, candidate-city attributes, and monthly climate.
Lodging search, lodging fixtures, lodging cost, and hotel selection are
deferred to a later version.

## Confirmed trip request

### Trip

- `start_date`: Confirmed departure date in ISO `YYYY-MM-DD` format.
- `end_date`: Confirmed return date in ISO `YYYY-MM-DD` format.
- `travelers`: Exactly two travelers. They may have the same or different
  origins.

Trips must last 3-7 calendar days, and the start date must not be in the past.

### Traveler

- `traveler_id`: Stable identifier within the request.
- `origin_id`: Internal reference to a confirmed metro-area or airport location.
  The planned live resolver will persist and reuse generated location IDs;
  lookup supplies the approved airport or city codes. Readable IDs in the example
  are deterministic test identifiers. See [the origin-ID decision](design-decisions.md).
- `budget_usd`: Maximum round-trip airfare for this traveler. Lodging and all
  other trip costs are outside the V1 budget calculation.
- `max_one_way_travel_minutes`: Maximum one-way flight itinerary duration,
  including layovers and excluding ground travel to or from airports.
- `preferences.temperature_range`: Optional confirmed daytime-temperature
  range in Celsius.
- `preferences.interest_tags`: Zero or more of `beach`, `mountain`, `food`,
  `museums`, `nightlife`, `nature`, `outdoor_activities`, and `shopping`.

Vibe preferences are intentionally excluded from V1 because the team does not
yet have an objective, consistently labeled destination dataset for them.
These are the only V1 preference inputs: `City.interest_tags` supports interest
matching, and `MonthlyClimate.average_daytime_temperature_celsius` supports
temperature matching.

## Example

```json
{
  "start_date": "2026-10-09",
  "end_date": "2026-10-13",
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
        "temperature_range": null,
        "interest_tags": ["mountain", "nature"]
      }
    }
  ]
}
```

## Ranking assumptions

Before ranking begins:

- Origins are resolved and unambiguous.
- Dates, budgets, and travel-time limits are valid.
- Qualitative temperatures are converted to confirmed Celsius ranges.
- Interest tags use the controlled vocabulary and contain no duplicates.
- Unsupported preferences have been disclosed and resolved with the user.
- All monetary values presented to the ranker are in USD and use decimal-safe
  arithmetic rather than binary floating-point calculations.

The ranking input does not contain raw user messages, qualitative temperature
terms, unresolved origins, unsupported interests, vibe preferences, lodging
requirements, or LLM reasoning.

## Duffel flight-search mapping

The confirmed trip request remains provider-independent. A flight-provider
adapter combines it with each candidate city's airport codes to create Duffel
Offer Requests. For each traveler and candidate city, the adapter maps:

- the traveler's resolved `origin_id` to one or more supported origin IATA
  airport or city codes;
- the candidate city's `metro_airport_codes` to Duffel destinations;
- `start_date` to the outbound slice's `departure_date`;
- `end_date` to the return slice's `departure_date`; and
- the fixed V1 passenger and cabin policy to one adult in economy class.

V1 creates a separate round-trip search for each traveler and candidate city.
Optional baggage, seats, ancillary services, private fares, airline credits,
and booking data are outside the request and budget calculation. Connection
limits and provider timeouts are adapter configuration, not user preferences,
and must be consistent across a ranking run.

## Complete workflow input

The recommendation workflow needs more than the confirmed user request.
After flight searches or fixture loading, the recommendation service assembles:

- the confirmed trip request;
- the versioned candidate-city catalog and the relevant monthly-climate
  records;
- normalized `FlightOffer` records for each traveler and candidate city;
- an evaluation timestamp; and
- candidate-data and flight-offer snapshot/source metadata.

Conceptually:

```text
RecommendationWorkflowInput
├── confirmed_trip_request
├── candidate_cities
├── monthly_climate
├── flight_offers
├── evaluated_at
└── data_snapshot_metadata
```

The recommendation service may pass these as separate typed arguments rather
than one large Pydantic object, but their contracts and versions must be
explicit. The ranker never receives raw Duffel JSON and never calls Duffel
directly.

## Flight-only V1 implications

- Hard affordability filtering compares each traveler's selected round-trip
  flight total with that traveler's `budget_usd`.
- Cost fairness compares the two travelers' flight-cost burdens; it does not
  claim to represent total-trip fairness.
- A city is eligible only when both travelers have at least one valid flight
  that satisfies dates, route, availability, maximum one-way travel time, and
  flight budget.
- The result may return up to four distinct flight offers per
  traveler. There is no flight-and-lodging package or reference lodging offer
  in V1.
- Customer-facing explanations must label costs as estimated round-trip
  airfare and state that accommodation and other trip expenses are excluded.

## Per-destination scoring contract

`DestinationRankingInput` is the smaller input for scoring one already-eligible
city. It contains the destination ID, exactly two travelers, their selected
`ScoredFlightOfferPair`, the two referenced offers, and `CityPreferenceFeatures`.
The workflow owns trip dates, city and climate datasets, source versions, and
response evaluation timestamps. It filters offers for both travelers, builds
compatible pairs, selects one pair per city, and computes preference features
before calling ranking. Ranking does not call providers or replace constraints.
`calculate_city_preference_features()` requires explicit `traveler_ids`, in the
same order as `traveler_preferences`, so features retain the request identities.

The scorer checks traveler/destination references, preference-feature traveler
identity, offer origins and availability, budget/time limits, and that the pair's
derived metrics match its offers. These consistency checks run when scoring;
constructing the Pydantic input alone does not establish eligibility. Pair
selection scores are not added to destination scores or recalculated from just
the selected two offers, since they depend on the city's candidate pairs.

## Destination scoring formulas

For each traveler, budget burden is round-trip airfare divided by their budget.
Time burden is the longer one-way journey divided by their maximum one-way time.
Both burdens must be between zero and one after constraints.

- Affordability: average of `1 - budget_burden` for the two travelers.
- Travel time: average of `1 - time_burden` for the two travelers.
- Duration balance: `1 - abs(time_burden_A - time_burden_B)`.
- Budget-burden balance: `1 - abs(budget_burden_A - budget_burden_B)`.
- Arrival alignment: 1 for gaps up to 120 minutes, 0 for gaps of at least
  360 minutes, and `(360 - gap_minutes) / 240` in between.
- Travel fairness: 50% duration balance, 30% budget-burden balance, and
  20% arrival alignment.

Duration balance measures relative burden, not equal elapsed hours: a two-hour
journey with a four-hour limit and a five-hour journey with a ten-hour limit
have equal time burdens. Raw duration differences can be reported separately.

The destination weights are 35% affordability, 30% travel fairness, 20%
preference match, and 15% travel time. Preference match uses the precomputed
combined preference score, including climate when requested. If neither
traveler has preferences, its weight and contribution are zero; the remaining
weights become 43.75%, 37.5%, and 18.75%, respectively. The inactive preference
component uses value 1 with weight 0, not a claim of a measured perfect match.

Component values and contributions are rounded to six decimal places. The
final score is the sum of rounded contributions, rounded to six decimal places.
Destinations sort by descending score, then ascending combined round-trip
price, combined round-trip travel minutes, and destination ID. The ranker returns
all candidates; the workflow selects up to three and constructs the public
response. An empty candidate list returns an empty ranking. Expiration remains
metadata and does not affect eligibility or scoring in V1.
