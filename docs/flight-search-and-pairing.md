# Travel AI Flight Search and Pairing

**Status:** Flight contracts and selectors implemented; service/API integration
remains a follow-up task  
**Scope:** Airport resolution, provider searches, flight eligibility, pair
selection, and customer-facing flight options

## 1. Resolve a traveler's origin

The destination candidate pool and the origin resolver serve different
purposes. The candidate pool restricts which cities Travel AI may recommend.
A traveler's origin does not need to be in that pool.

The LLM may extract a place name from the conversation, but it must not invent
airport codes or coordinates. A deterministic location resolver performs that
work:

1. Send the extracted city or airport text to Duffel Place Suggestions.
2. Retain U.S. city or airport matches for V1.
3. Prefer an unambiguous city result and retain its IATA city code for live
   flight search. If the traveler entered an airport code, retain that exact
   airport instead.
4. Treat returned airports as candidates, not proof that every result is a
   major commercial airport. Apply the curated V1 airport priority before
   constructing an explicit airport group.
5. If multiple places are plausible, ask the traveler to choose one.
6. Use no more than three airports. For a known metro area, use its curated
   airport priority. If more than three airports remain and no priority is
   available, ask the traveler which airports are acceptable rather than
   silently choosing.
7. Cache the resolved result so later turns and repeated candidate searches do
   not resolve the same origin again.

Duffel's airport records can supply the name, IATA code, associated IATA city
code, latitude, longitude, and time zone. A city result may have null
coordinates, as it does in the tested Boston response. Latitude and longitude
are therefore not required in `TripRequest`; when present, they belong to the
resolved airport record produced by the resolver.

An illustrative internal contract is:

```json
{
  "location_id": "new_york_ny",
  "display_name": "New York City, NY",
  "country_code": "US",
  "iata_city_code": "NYC",
  "airports": [
    {
      "iata_code": "JFK",
      "latitude": 40.6413,
      "longitude": -73.7781,
      "time_zone": "America/New_York"
    }
  ],
  "source": "duffel_places"
}
```

### Verified Boston response

The tested `query=Boston` response returned:

- a city result with `id=cit_bos_us`, `iata_code=BOS`, and null city
  coordinates;
- city-associated airport candidates `BNH`, `BOS`, and `PSM`; and
- a separate `MHT` airport result.

This confirms that place resolution and major-airport selection are separate
steps. `BNH` is a seaplane base, so copying the city result's first three
airports would not implement the intended product rule. For live Duffel search,
use the resolved IATA city code when possible and let returned offers identify
the actual departure airport. For fixture mode or explicit-airport searches,
use the curated airport group and its maximum of three codes.

If V1 later accepts an address or raw coordinates, a geocoder first converts
the input to latitude/longitude and Duffel Place Suggestions can then search
within a radius. That address-level behavior remains outside the city-input V1
contract.

The destination catalog already stores `metro_airport_codes`. When Ivy's
destination-fixture branch is reconciled, that field must also enforce the V1
maximum of three codes. Coordinates may be added to destination records later
for display or ground-distance features, but flight search requires validated
IATA codes rather than city coordinates.

Google Maps uses proprietary place search, geocoding, geographic indexes, and
relevance ranking to resolve locations quickly. Travel AI follows the same
separation on a smaller scale: language extraction identifies the user's text,
a place service resolves the location, and deterministic code selects the
approved airport group. Google Geocoding or Places can be added later if V1 is
expanded from city names to arbitrary street addresses.

## 2. Search all approved airport pairs

Fixture and explicit-airport searches build the Cartesian product of the
resolved origin airports and the destination's metro airports. With the V1 cap,
there are at most `3 × 3 = 9` origin/destination airport pairs per traveler and
18 per city for two travelers. A live Duffel adapter may instead send the
resolved IATA city codes in one offer request and normalize the actual airports
from the returned offers. This optimization does not change the internal
`FlightOffer` contract.

Each provider result is normalized into a provider-independent `FlightOffer`.
Travel AI retains both nonstop and connecting offers. Searching only nonstop
would remove the required fallback when nonstop service is unavailable or too
expensive.

Provider latency and rate limits, rather than pair calculations, are the main
performance concern. The live provider should use bounded concurrency, cache
identical searches, deduplicate returned offers, record provider latency, and
handle partial failures. The fixture provider remains deterministic and does
not make network calls.

## 3. Filter individual offers

Before comparing two travelers, remove any offer that:

- does not match the traveler, resolved airport groups, destination, dates, or
  economy cabin;
- exceeds that traveler's airfare budget;
- exceeds that traveler's maximum one-way travel time;
- lacks a valid USD round-trip price;
- is unavailable; or
- is expired when it represents a live quote.

## 4. Build compatible flight pairs

Arrival compatibility is not a property of one `FlightOffer`. It is computed
by comparing one eligible offer for Traveler A with one eligible offer for
Traveler B.

For small fixture sets, compare every eligible `A offer × B offer` pair. Before
pairing large live result sets, deduplicate and retain a bounded set of useful
offers for each traveler. A starting cap of 20 offers per traveler produces at
most 400 in-memory comparisons per city, which is inexpensive compared with
the provider requests.

For every pair, derive:

```text
combined_price_usd = A.total_amount + B.total_amount
arrival_gap_minutes = abs(A.outbound_arrival - B.outbound_arrival)
shared_trip_start = max(A.outbound_arrival, B.outbound_arrival)
shared_trip_end = min(A.return_departure, B.return_departure)
shared_trip_minutes = max(0, shared_trip_end - shared_trip_start)
total_connections = A.total_connections + B.total_connections
combined_travel_minutes = A.total_travel_minutes + B.total_travel_minutes
```

Compare timestamps as timezone-aware instants. A pair with no positive shared
trip time is invalid.

An illustrative internal contract is:

```json
{
  "traveler_a_offer_id": "offer_a_001",
  "traveler_b_offer_id": "offer_b_004",
  "combined_price_usd": "780.00",
  "arrival_gap_minutes": 45,
  "shared_trip_minutes": 5160,
  "total_connections": 0,
  "combined_travel_minutes": 690
}
```

## 5. Select the recommended pair

First identify the cheapest valid pair. Only pairs whose combined price is no
more than 50% above that baseline remain candidates for the recommended pair;
each individual offer must still remain inside its traveler's budget.

Within that protected price range, select deterministically by:

1. smaller arrival gap;
2. fewer combined connections;
3. longer shared trip time;
4. shorter combined travel time;
5. lower combined price; then
6. lexicographically smaller stable offer IDs.

This makes arriving together the primary convenience goal without allowing an
unbounded airfare premium. Arrival alignment is a soft selection rule, not a
hard constraint, so an otherwise useful city is not excluded solely because
the travelers arrive several hours apart.

The independently highlighted offer for one traveler uses the same 50% price
tolerance to prefer a round-trip nonstop over that traveler's cheapest eligible
offer. This does not create a `nonstop_only` request field and does not make
connecting flights ineligible.

## 6. Return category-selected options per traveler

After the recommended pair has been chosen, begin each traveler's display list
with that pair's offer. Then consider eligible offers in this order:

1. lowest price;
2. shortest total round-trip travel time; and
3. fewest total connections.

Deduplicate by stable internal offer ID when the recommended offer or another
offer wins more than one category. Keep every applicable label on that single
option and do not backfill with an unrelated alternative. The response therefore
contains between one and four distinct options, depending on how many category
winners are different. Reserving the first slot for the recommended pair
ensures that the two synchronized choices are always visible.

The API returns a smaller public `FlightOption` rather than every internal
`FlightOffer` field. Each option has one or more labels: `recommended_pair`,
`lowest_price`, `shortest_travel`, or `fewest_connections`. The recommended
pair's two offers are always present in their respective lists. Travelers may
choose a different combination from their independent lists; the client or
service then recalculates combined price, arrival gap, and shared trip time
without reranking the destination.

The recommended pair—not the cheapest valid pair—is used for the city's score.
The cheapest pair remains an internal affordability anchor. The response
publishes its combined price and the recommended pair's dollar and percentage
premium, but does not expose a second pair of baseline offer IDs.

## 7. Implementation order

1. Finish and merge the normalized `FlightOffer` contract, fixture provider,
   flight-pair selector, and four-category selector.
2. Reconcile the three-airport constraint from the destination-fixture branch.
3. Add a `ResolvedLocation` contract and Duffel Places adapter.
4. Implement individual eligibility filters.
5. Connect the pair and option selectors to the recommendation service.
6. Expose the recommended pair and individual option lists in the
   recommendation response.
7. Add the live Duffel offer adapter with caching, bounded concurrency, logging,
   and fixture fallback.
