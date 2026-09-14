# Travel AI Flight-Offer Selection and Provider Research

**Reviewed:** 2026-09-01  
**Status:** Approved V1 design  
**Purpose:** Define the Duffel field mapping, normalized `FlightOffer`
contract, and deterministic rules for selecting the flight choices used to
rank and explain candidate cities.

## V1 scope decision

V1 recommends cities using round-trip flight offers for exactly two
travelers. It does not search, model, filter, score, or return lodging.
Lodging is deferred because the team does not currently have dependable
developer access to a lodging-price API and realistic lodging fixtures would
substantially expand the current milestone.

For each of the three ranked cities, the response contains:

- up to three flight offers for Traveler A; and
- up to three flight offers for Traveler B.

This is at most six offers per city and 18 offers across the final response.
Flights remain independent choices: Travel AI does not create a fixed bundle
for the two travelers. If fewer than three eligible offers exist for a
traveler, return the available distinct offers rather than inventing or
duplicating options.

## Approved V1 selection rules

### Data source and normalization

- The fixture MVP uses versioned `FlightOffer` JSON data.
- Sanitized Duffel test responses inform the fixtures, but application code
  does not expose Duffel's raw response to the constraint engine or ranker.
- A future live adapter validates Duffel's response and maps it into the same
  internal contract used by fixtures.
- Prices from fixture mode must be labeled as estimates. Live offers must
  include their retrieval and expiry timestamps.

### Individual flight eligibility

A flight offer is eligible only when it:

- belongs to the correct traveler and candidate city;
- matches the requested origin, outbound date, and return date;
- uses the supported cabin class, initially `economy`;
- has a usable round-trip total price and currency;
- does not exceed that traveler's airfare budget;
- does not exceed that traveler's maximum travel time under the team's
  approved duration definition; and
- is available and unexpired when it represents a live quote.

If either traveler has no eligible flight for a city, exclude that city and
return a machine-readable reason.

### Reference flight pair

A city is eligible when both travelers have at least one eligible flight. For
each eligible city, select one deterministic **reference flight pair**: one
offer for Traveler A and one for Traveler B with the lowest combined airfare.

```text
combined_airfare = traveler_A_flight_total + traveler_B_flight_total
```

If combined prices tie, choose the pair with:

1. shorter combined travel time;
2. fewer combined connections; then
3. lexicographically smaller stable internal offer IDs.

The reference pair supplies the airfare, fairness, and travel-time features
used to rank the city. Its two offers must also appear in the customer-facing
option lists and be identified by `reference_flight_offer_ids`.

### Customer flight options

For each traveler in each returned city, select up to three distinct eligible
offers:

1. **Lowest price:** price, then duration, connections, offer ID.
2. **Shortest travel time:** duration, then price, connections, offer ID.
3. **Fewest connections:** connections, then duration, price, offer ID.

Remove duplicates when one offer wins multiple categories. Backfill from the
remaining offers ordered by price, duration, connections, and offer ID until
three distinct options are present. If the reference flight is not already a
winner, include it and remove the last backfilled option when necessary.

Choosing an alternate flight does not rerank the city. The client can
recalculate the displayed airfare and travel burden for the selected offers
and warn when a choice exceeds a traveler's original constraints.

## Duffel flight-provider mapping

Because the travelers have different origins, Travel AI performs two separate
round-trip searches per candidate city: one for Traveler A and one for
Traveler B.

### Search endpoint

`POST https://api.duffel.com/air/offer_requests?return_offers=true`

Duffel represents a round trip with an outbound and return `slice`. See the
official [Offer Requests API](https://duffel.com/docs/api/v2/offer-requests)
and [flight getting-started guide](https://duffel.com/docs/guides/getting-started-with-flights).

### Input required for each traveler and city

- origin IATA airport or city code;
- destination IATA airport or city code;
- outbound date;
- return date;
- one adult passenger; and
- cabin class, initially `economy`.

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

Names, birth dates, contact details, and payment information are booking
inputs and are not required for V1 search and comparison.

### Response fields Travel AI retains

From each Duffel offer, retain only fields needed for eligibility,
comparison, freshness, and explanation:

- offer `id`, `created_at`, `updated_at`, and `expires_at`;
- `total_amount`, `total_currency`, and tax fields when present;
- owner and operating carriers;
- outbound and return slice durations, endpoints, and segment lists;
- segment departure/arrival times, duration, airports, carrier, and flight
  number;
- fare conditions needed to explain refund or change limitations.

Duffel test mode is suitable for adapter behavior but does not guarantee
realistic schedules or prices. Fixture values should therefore be plausible
test scenarios, not claims about current market prices. See Duffel's official
[test-mode documentation](https://duffel.com/docs/api/overview/test-mode/duffel-airways).

### Normalized `FlightOffer` example

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
  "retrieved_at": "2026-08-29T12:00:00Z",
  "expires_at": "2026-08-29T12:30:00Z",
  "is_fixture": true
}
```

Use decimal strings for provider money and convert them to `Decimal` in
Python. Do not use binary floating-point values for prices.

## Fixture and test cases

Create internal fixtures from the normalized contract. Keep any stored
provider-response samples redacted and use them only for adapter contract
tests when provider terms permit storage.

Cover at least:

- direct and connecting round trips;
- one traveler with much higher airfare or duration;
- an offer exactly at a budget or travel-time boundary;
- expired, unavailable, malformed, and currency-mismatched offers;
- fewer than three distinct eligible offers;
- a city with no eligible flight for one traveler;
- tied prices that exercise every deterministic tie-breaker; and
- the same offers arriving in different provider orders.

## Out of scope

V1 excludes lodging data, lodging fixtures, lodging providers, flight-and-
hotel packages, booking, orders, payments, and passenger-detail collection.
A later scope decision can introduce lodging behind a separate provider and
normalized contract without changing the flight-selection rules.
