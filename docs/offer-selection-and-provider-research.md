# Travel AI Offer-Selection and Provider Research

**Reviewed:** 2026-08-29  
**Purpose:** Define Travel AI's provider-field mapping, normalized offer
contracts, and deterministic rules for choosing, scoring, and returning flight
and lodging offers. Duffel is the current flight-provider research example;
lodging uses fixtures until an approved provider is available.

## Decision summary

Duffel returns a variable number of flight and accommodation results. Travel
AI will not expose that unbounded response directly. The product response is
capped at:

- three ranked cities;
- three flight offers for Traveler A per city;
- three flight offers for Traveler B per city; and
- three lodging options for the pair per city.

That is at most nine offer records per city and 27 offer records in the final
three-city response. The API does not need to display all 27 possible
flight-A, flight-B, and lodging combinations for one city. It can calculate
valid combinations internally, rank the city with one reference package, and
return the separate choices rather than a fixed flight-and-hotel bundle. The
customer selects one flight per traveler and one shared lodging option; the
client then recalculates totals, budget status, and fairness for that selected
combination.

If fewer than three eligible offers exist in a category, return the available
offers rather than inventing or duplicating an option.

## Approved V1 offer-selection rules

This section is the implementation source of truth. The API ranks cities, not
fixed flight-and-hotel packages.

### Data source and normalization

- The fixture MVP uses versioned `FlightOffer` and `LodgingOffer` JSON data.
  Sanitized Duffel test responses inform flight fixtures; they are not copied
  into Git as raw provider payloads.
- Live lodging-provider access is not required for V1. Lodging fixtures must
  declare `provider: "fixture"`, `is_fixture: true`, and their source/freshness
  metadata so the UI does not imply a live quote.
- A future provider adapter validates its response and maps it into the same
  internal contracts before the constraint engine or ranker reads it.

### Individual-offer eligibility

A flight offer is eligible only when it matches the traveler, origin,
destination, requested outbound and return dates, allowed cabin class, and
maximum travel time; it must also be available and unexpired when it is a live
quote. A lodging offer is eligible only when it matches the city, stay dates,
one room, and two adult guests, and has an available total stay price and
currency.

V1 has no star-rating threshold. A lodging offer may omit a review score,
review count, or refund data and remain eligible, but it cannot win a display
category that requires the missing field.

### Package eligibility and reference package

The service forms combinations of one eligible flight for Traveler A, one
eligible flight for Traveler B, and one eligible shared lodging offer. A
combination is budget-valid only when:

```text
traveler_A_total = flight_A_total + lodging_total / 2 <= traveler_A_budget
traveler_B_total = flight_B_total + lodging_total / 2 <= traveler_B_budget
```

A city qualifies when at least one budget-valid combination exists. Its
**reference package** is the lowest-total-cost valid combination. If totals
tie, choose shorter combined flight duration, then fewer combined stops, then
the lexicographically smallest stable internal offer IDs. The reference
package alone supplies the city-level affordability, fairness, and travel-time
features for initial ranking.

### Customer options after city ranking

For each of the three highest-ranked cities, return separate, independently
selectable options:

- up to three flights for Traveler A: lowest price, shortest travel time, and
  fewest stops;
- up to three flights for Traveler B using the same rules; and
- up to three lodging options: lowest total price, best reviewed among
  properties that participate in at least one budget-valid package, and most
  flexible cancellation among those properties.

Remove duplicate winners and backfill in the documented deterministic order.
Always include the reference-package offer in its relevant returned list. The
customer may mix any displayed options. The client recalculates each person's
total, combined total, budget status, and fairness for the selected
combination; a budget warning does not change the original city rank.

### Required behavior for missing and stale data

- Exclude a live flight or lodging quote that is expired, unavailable, or has
  no usable total price.
- Keep fixtures usable until their explicit fixture version is replaced; label
  them as estimates, not live prices.
- If an eligible city has fewer than three qualifying options, return the
  available distinct options.
- If no budget-valid combination remains, exclude the city and record a
  machine-readable reason.

### Ranking features still requiring team approval

The city-score weights are approved: 35% affordability, 30% travel fairness,
20% preference match including climate, and 15% travel time. Before Week 3
implementation, Winnie and Ivy must define the exact normalized formulas for
affordability and travel fairness, including whether fairness combines
differences in budget usage, flight duration, or both.

## Duffel flight-provider research

The travelers start in different places, so their flights cannot be searched
as passengers on the same Duffel itinerary. For every candidate city, Travel
AI makes:

1. one round-trip Flight Offer Request for Traveler A; and
2. one round-trip Flight Offer Request for Traveler B.

The flight responses are normalized and joined with fixture lodging offers
using Travel AI's `city_id`, trip dates, traveler ID, and stable internal
offer IDs.

## Flight search

### Duffel endpoint

`POST https://api.duffel.com/air/offer_requests`

Duffel describes an Offer Request as the flight-search resource. A round trip
has two `slices`: outbound and return. Each returned offer represents a priced
set of flights satisfying the requested slices. See the official
[Offer Requests API](https://duffel.com/docs/api/v2/offer-requests) and
[flight getting-started guide](https://duffel.com/docs/guides/getting-started-with-flights).

### Input Travel AI must provide

For each traveler and candidate city:

- origin IATA airport or city code;
- destination IATA airport or city code;
- outbound date;
- return date;
- one adult passenger; and
- cabin class, initially `economy`.

Example provider request for one traveler:

```json
{
  "data": {
    "slices": [
      {
        "origin": "SFO",
        "destination": "ORD",
        "departure_date": "2026-10-09"
      },
      {
        "origin": "ORD",
        "destination": "SFO",
        "departure_date": "2026-10-13"
      }
    ],
    "passengers": [{"type": "adult"}],
    "cabin_class": "economy"
  }
}
```

Traveler B needs a separate request with their origin. Names, birth dates,
email addresses, phone numbers, and payment information are booking inputs and
are not required for Travel AI's search-only V1.

### Duffel response fields relevant to Travel AI

The Offer Request response contains an ID, the echoed slices and passengers,
and a list of offers. From each offer, retain only fields needed for comparison
and explanation:

- `id`: stable provider offer ID for this short-lived offer;
- `total_amount` and `total_currency`: total for all passengers, including
  taxes but excluding optional services;
- `tax_amount` and `tax_currency`, when present;
- `created_at`, `updated_at`, and `expires_at`;
- `owner` and the operating carrier displayed for every segment;
- `slices`: outbound and return journeys;
- slice duration, origin, destination, and segment list;
- segment departure/arrival times, duration, airports, carrier, and flight
  number;
- passenger baggage information when available; and
- fare conditions needed to explain change/refund limitations.

Duffel says offers typically expire within about 30 minutes, with the exact
time in `expires_at`. The selected offer should be retrieved again before any
future checkout or booking flow. See the official
[Offers API](https://duffel.com/docs/api/offers/get-offers).

### Normalized `FlightOffer` fixture

The Week 2 fixture should represent Travel AI's contract rather than a complete
copy of Duffel's response:

```json
{
  "offer_id": "flight_fixture_sfo_ord_001",
  "provider": "duffel",
  "provider_offer_id": "off_example_001",
  "traveler_id": "traveler_a",
  "city_id": "chicago_il",
  "origin_code": "SFO",
  "destination_code": "ORD",
  "cabin_class": "economy",
  "total_amount": "260.00",
  "currency": "USD",
  "total_travel_minutes": 505,
  "total_connections": 0,
  "slices": [
    {
      "direction": "outbound",
      "departure_at": "2026-10-09T08:00:00-07:00",
      "arrival_at": "2026-10-09T14:10:00-05:00",
      "duration_minutes": 250,
      "segments": 1,
      "operating_carriers": ["Example Air"]
    },
    {
      "direction": "return",
      "departure_at": "2026-10-13T15:00:00-05:00",
      "arrival_at": "2026-10-13T17:15:00-07:00",
      "duration_minutes": 255,
      "segments": 1,
      "operating_carriers": ["Example Air"]
    }
  ],
  "baggage_summary": "carry-on included; checked baggage unknown",
  "retrieved_at": "2026-08-29T12:00:00Z",
  "expires_at": "2026-08-29T12:30:00Z",
  "is_fixture": true
}
```

Use decimal strings for provider money and convert them to `Decimal` in
Python. Do not use binary floating-point values for prices.

## Future lodging-provider shape (Duffel Stays example)

Duffel Stays access currently requires provider approval and is not part of
the V1 integration. This section records its documented request/response shape
so fixtures and a later lodging adapter use realistic fields. No V1 code
should depend on a successful Duffel Stays request.

### Duffel endpoints

The search and detail flow is:

1. `POST https://api.duffel.com/stays/search`
2. `POST https://api.duffel.com/stays/search_results/{search_result_id}/actions/fetch_all_rates`

The initial search returns available properties and a cheapest-rate amount.
Room and rate details may be incomplete at that stage. Fetching all rates for
a selected search result returns its complete room and rate information. See
the official [Stays Search API](https://duffel.com/docs/api/v2/search),
[Fetch All Rates API](https://duffel.com/docs/api/v2/search-result/fetch-all-rates),
and [Stays concepts](https://duffel.com/docs/api/overview/stays-key-concepts).

### Input Travel AI must provide

For each candidate city:

- check-in date;
- check-out date;
- two adult guests;
- one room; and
- either city-center latitude, longitude, and search radius, or known
  accommodation IDs.

Location search is the better match for the candidate-city approach:

```json
{
  "data": {
    "rooms": 1,
    "location": {
      "radius": 8,
      "geographic_coordinates": {
        "latitude": 41.8781,
        "longitude": -87.6298
      }
    },
    "check_in_date": "2026-10-09",
    "check_out_date": "2026-10-13",
    "guests": [
      {"type": "adult"},
      {"type": "adult"}
    ]
  }
}
```

The search radius must be a documented product constant so identical fixture
inputs produce identical results.

### Initial Stays Search response fields

Keep the following from each search result:

- search-result `id` and `expires_at`;
- `check_in_date`, `check_out_date`, guests, and rooms;
- `cheapest_rate_total_amount` and `cheapest_rate_currency`;
- accommodation `id`, name, address, and geographic coordinates;
- star `rating`, aggregated `review_score`, and `review_count`;
- photos and amenities needed for the customer display.

Duffel documents the star rating as 1-5 when available and the review score as
1.0-10.0 when available. These fields can be missing, so the normalized schema
must allow `null`. See the official
[Accommodation schema](https://duffel.com/docs/api/v2/accommodation) and
[Search Result schema](https://duffel.com/docs/api/v2/search-result).

### Full room/rate fields for displayed options

For properties chosen for the final result, Fetch All Rates and retain:

- room ID, name, bed configuration, and photos;
- rate ID and rate name;
- total, base, tax, and due-at-property amounts with currencies when present;
- board type and benefits such as included breakfast;
- cancellation timeline or a derived refundability summary; and
- the search-result expiry time.

Creating a Duffel Stay Quote confirms availability and total price, but it is a
pre-booking action and is outside the current V1. See the official
[Quote API](https://duffel.com/docs/api/v2/quotes/create-quote).

### Normalized `LodgingOffer` fixture

Store one selected room/rate per lodging offer:

```json
{
  "offer_id": "lodging_fixture_chicago_001",
  "provider": "duffel",
  "provider_search_result_id": "srr_example_001",
  "provider_accommodation_id": "acc_example_001",
  "provider_rate_id": "rat_example_001",
  "city_id": "chicago_il",
  "property_name": "Example Chicago Hotel",
  "latitude": 41.881,
  "longitude": -87.63,
  "check_in_date": "2026-10-09",
  "check_out_date": "2026-10-13",
  "rooms": 1,
  "adult_guests": 2,
  "room_name": "Standard King Room",
  "bed_summary": "1 king bed",
  "total_amount": "540.00",
  "currency": "USD",
  "rating": 3,
  "review_score": 8.4,
  "review_count": 336,
  "board_type": "room_only",
  "refundability": "fully_refundable_before_deadline",
  "amenities": ["wifi"],
  "retrieved_at": "2026-08-29T12:00:00Z",
  "expires_at": "2026-08-29T12:30:00Z",
  "is_fixture": true
}
```

## Deterministic option-selection rules

Duffel may return many offers, in a changing order. Travel AI applies fixed
rules after schema validation and before returning customer results.

### Flight options per traveler and city

Return up to three distinct eligible offers:

1. **Lowest price:** total amount, then duration, connections, offer ID.
2. **Shortest travel time:** duration, then price, connections, offer ID.
3. **Fewest connections:** connections, then duration, price, offer ID.

Remove duplicates when the same offer wins more than one category. Backfill
from the remaining offers ordered by price, duration, connections, and offer
ID until three distinct choices are present.

### Lodging options per city

Return up to three distinct eligible properties, with one chosen rate per
property:

1. **Lowest total price:** stay total, then review score, property ID.
2. **Best reviewed:** among properties that participate in at least one
   budget-valid package, review score, review count, price, property ID.
3. **Best refundable option:** among properties that participate in at least
   one budget-valid package, latest full-refund deadline, review score, price,
   property ID.

If review or cancellation data is unavailable, that property cannot win the
corresponding category but can still win lowest price. Remove duplicates and
backfill by price.

### City eligibility and scoring

A city is eligible when at least one combination of one flight for each
traveler and one shared lodging offer satisfies both travelers' hard budget
and maximum-travel-time constraints. The deterministic reference package is
the lowest-total-cost eligible combination. It drives city scoring but is not
the only choice shown to the users.

Alternative selections can change the final per-person total. The response
must provide all component prices so the client can recalculate:

```text
traveler_total = selected_flight_total + selected_lodging_total / 2
```

The client must revalidate each final combination against both budgets rather
than implying that every possible cross-combination is affordable.

The reference package's flight and lodging records must appear in the returned
option lists and be labeled as the components used for the city score. Other
returned choices are independent alternatives, not offers attached to a
specific hotel or flight.

## Recommended staged provider workflow

For the fixture MVP, load all data locally. For a future live flight adapter
and an approved live lodging adapter:

1. Search each traveler-to-city route and the lodging market for all 10
   candidate cities.
2. Validate and normalize the responses.
3. Use each city's cheapest eligible flight pair and initial cheapest lodging
   amount to identify eligible cities and calculate preliminary rankings.
4. For the top three cities, fetch complete rates for the lodging properties
   that may be displayed.
5. Recalculate eligibility and city scores from the detailed selected rates.
6. Return the top three cities with three flight choices per traveler and
   three lodging choices when available.

This avoids fetching full room/rate data for every property in every city while
still using detailed information in the final customer response.

## Fixture and testing guidance

Create internal fixture files from the normalized contracts, not by making the
application depend directly on Duffel's full JSON shape. Separately keep a few
redacted provider-response samples for adapter contract tests if Duffel's terms
permit storing them.

Include fixture cases for:

- direct and connecting flights;
- one traveler with a much higher price or duration;
- expired offers and search results;
- fewer than three flight or lodging choices;
- missing hotel rating or review score;
- refundable and non-refundable rates;
- a price that changes after detailed rate retrieval;
- no available lodging or no flight for one traveler; and
- a city where only one flight-and-lodging combination fits both budgets.

Duffel test mode is appropriate for integration behavior, but its flight
schedules and prices are not realistic. The fixed fixture values should
therefore be plausible test scenarios rather than claims about current market
prices. See Duffel's official
[test-mode documentation](https://duffel.com/docs/api/overview/test-mode/duffel-airways).

## Out of scope

Travel AI V1 will not call Duffel order, booking, payment, passenger-detail, or
Stay Quote endpoints. It searches and compares estimates only. Before any
future booking integration, the team must separately review price refresh,
required carrier display, customer-data handling, payment, cancellation, and
legal-display requirements.
