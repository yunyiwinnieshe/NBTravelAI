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
- `origin_id`: Resolved metro-area identifier. The origin catalog maps it to
  one or more airports.
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

## Complete ranking input

The deterministic ranking system needs more than the confirmed user request.
After flight searches or fixture loading, the recommendation service assembles:

- the confirmed trip request;
- the versioned candidate-city catalog and the relevant monthly-climate
  records;
- normalized `FlightOffer` records for each traveler and candidate city;
- an evaluation timestamp; and
- candidate-data and flight-offer snapshot/source metadata.

Conceptually:

```text
RankingInput
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
- The result may return up to three independently selectable flight offers per
  traveler. There is no flight-and-lodging package or reference lodging offer
  in V1.
- Customer-facing explanations must label costs as estimated round-trip
  airfare and state that accommodation and other trip expenses are excluded.
