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
   major commercial airport. Join by IATA code to a versioned airport-reference
   snapshot and keep only records with scheduled service whose type is
   `large_airport` or `medium_airport`.
5. If multiple places are plausible, ask the traveler to choose one.
6. Rank an explicitly entered airport first. Otherwise rank large before medium
   airports, then shorter geographic distance when reference coordinates are
   available, city association, and stable IATA code.
7. Use no more than three airports. If multiple places are plausible before
   airport ranking, ask the traveler to choose rather than silently resolving
   the wrong city.
8. Cache the resolved result so later turns and repeated candidate searches do
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

Duffel Places supplies search relevance and geographic airport records, but its
response does not include a major-airport rank, passenger count, or explicit
scheduled-commercial-service flag. V1 therefore supplements Duffel candidates
with a versioned reference snapshot derived from OurAirports. The selected
fields are `iata_code`, `type`, and `scheduled_service`; the data version must be
recorded because this is external reference data. The application, not the LLM,
performs the join, filtering, distance calculation, and stable ranking.

The generated V1 snapshot belongs at
`src/travel_ai/fixtures/airport_reference.json`. A repeatable generation script
should retain U.S. airports with an IATA code and scheduled service whose type
is `large_airport` or `medium_airport`. The generated file records its source
date and schema version. Refreshing it is a deliberate release task rather than
a runtime API call.

V1 accepts an explicit airport/IATA code or a city plus state. It does not
accept arbitrary street addresses and does not require a geocoder. If Duffel
returns multiple plausible places, the LLM may present those verified choices
and ask a clarification question, but it must not choose a place or invent
coordinates. Address and arbitrary-town geocoding are deferred.

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
18 per city for two travelers.

For live V1 searches, prefer one Duffel offer request using the unambiguous
origin and destination metropolitan city codes when both are available. The
adapter normalizes the actual airports returned and discards offers outside the
approved airport groups. Fall back to explicit airport-pair searches when a
city code is unavailable, the traveler selected an exact airport, or the
city-code search returns no approved offers. This optimization does not change
the internal `FlightOffer` contract.

Each provider result is normalized into a provider-independent `FlightOffer`.
Travel AI retains both nonstop and connecting offers. Searching only nonstop
would remove the required fallback when nonstop service is unavailable or too
expensive.

Provider latency and rate limits, rather than pair calculations, are the main
performance concern. The live provider should use bounded concurrency, cache
identical searches, deduplicate returned offers, record provider latency, and
handle partial failures. If at least one explicit airport-pair search succeeds,
use its offers and attach a structured warning for every failed search. Fail
the destination only when every required search attempt fails. The fixture
provider remains deterministic and does not make network calls.

## 3. Filter individual offers

Before comparing two travelers, remove any offer that:

- does not match the traveler, resolved airport groups, destination, dates, or
  economy cabin;
- exceeds that traveler's airfare budget;
- exceeds that traveler's maximum one-way travel time;
- lacks a valid USD round-trip price;
- or is unavailable.

`expires_at` remains useful provider metadata, but V1 is a research and
comparison experience rather than a booking guarantee. Expiration does not
affect ranking. Results show when they were retrieved, and any future booking
handoff must run a fresh search.

## 4. Build compatible flight pairs

Arrival compatibility is not a property of one `FlightOffer`. It is computed
by comparing one eligible offer for Traveler A with one eligible offer for
Traveler B.

For small fixture sets, compare every eligible `A offer × B offer` pair. Before
pairing large live result sets, deduplicate and retain a bounded set of useful
offers for each traveler. A starting cap of 20 offers per traveler produces at
most 400 in-memory comparisons per city, which is inexpensive compared with
the provider requests. The bounded set should be a deterministic union of
low-price, short-travel, and few-connection results rather than simply the 20
cheapest offers.

For every pair, derive:

```text
combined_price_usd = A.total_amount + B.total_amount
arrival_gap_minutes = abs(A.outbound_arrival - B.outbound_arrival)
return_departure_gap_minutes = abs(A.return_departure - B.return_departure)
shared_trip_start = max(A.outbound_arrival, B.outbound_arrival)
shared_trip_end = min(A.return_departure, B.return_departure)
shared_trip_minutes = max(0, shared_trip_end - shared_trip_start)
total_connections = A.total_connections + B.total_connections
combined_travel_minutes = A.total_travel_minutes + B.total_travel_minutes
```

Compare timestamps as timezone-aware instants. A pair with no positive shared
trip time is invalid. For V1, both travelers in a pair must arrive at the same
destination airport because the system does not yet model ground transfers
between airports.

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

Score every valid pair. Do not discard a pair merely because its combined price
is a fixed percentage above the cheapest pair. Each individual offer must still
remain inside its traveler's budget.

The V1 pair-selection score is:

```text
pair_selection_score = 0.35 * price_score
                     + 0.25 * arrival_alignment_score
                     + 0.20 * travel_time_score
                     + 0.10 * connection_score
                     + 0.10 * shared_trip_score
```

The component values are normalized within the valid pairs for one city:

```text
price_score = cheapest_pair_price / pair_price
travel_time_score = shortest_pair_travel_minutes / pair_travel_minutes
connection_score = 1 / (1 + pair_total_connections)
shared_trip_score = pair_shared_trip_minutes / longest_shared_trip_minutes
```

The connection formula is an initial product heuristic, not a Duffel or
industry standard. Under this curve, one total connection scores `0.5`. The
team must validate whether this penalty is too strong before calling the
weights final.

Arrival alignment gives full credit when the travelers arrive within two hours,
declines linearly between two and six hours, and gives zero credit at six hours
or more. These two- and six-hour values are initial product hypotheses, not
external standards. They remain soft-score boundaries and must be checked
against labeled pair-selection examples.

```text
arrival_alignment_score = 1.0                         when gap <= 120 minutes
arrival_alignment_score = (360 - gap) / (360 - 120) when 120 < gap < 360
arrival_alignment_score = 0.0                         when gap >= 360 minutes
```

Arrival alignment and shared trip measure different effects. Arrival alignment
measures how close the outbound arrivals are. Shared trip measures the usable
overlap from the later outbound arrival until the earlier return departure, so
it captures the effect of both travelers' arrival and return schedules. The
return-departure gap is still returned for explanation, but V1 does not add a
separate return-alignment weight because that would partly double-count shared
trip time.

The pair with the highest score is recommended. Equal scores are resolved by:

1. lower combined cost;
2. shorter combined travel time;
3. smaller arrival-time difference;
4. fewer combined connections;
5. longer shared trip time; then
6. lexicographically smaller stable offer IDs.

This scoring step answers which two flights work best together for one city. It
does not rank destinations. The destination ranker later uses the selected
pair's raw price, travel-time, arrival, and burden values together with city
preferences. It does not use `pair_selection_score` as a destination-score
component.

"Normalized within one city" means that Chicago pairs are compared with other
Chicago pairs and Denver pairs with other Denver pairs. A score of `0.90` for
a Chicago pair is therefore not directly better than `0.85` for a Denver pair.
The pair score selects the flights representing each city; the separate
destination score compares cities using consistently normalized destination
features.

## 6. Return up to four distinct options per traveler

After the recommended pair has been chosen, begin each traveler's display list
with that pair's offer. Then consider eligible offers in this order:

1. lowest price;
2. shortest total round-trip travel time; and
3. fewest total connections.

Each category uses the other attributes as deterministic tie-breakers:

- lowest price: price, travel time, connections, then offer ID;
- shortest travel: travel time, price, connections, then offer ID; and
- fewest connections: connections, price, travel time, then offer ID.

Deduplicate by stable internal offer ID when the recommended offer or another
offer wins more than one category. Return the offer once with every truthful
label. Do not backfill an arbitrary alternative merely to reach four options;
the response may therefore contain fewer than four distinct offers. Reserving
the first slot for the recommended pair ensures that the synchronized choices
are always visible.

The API returns each `FlightOffer` once and identifies the recommended
combination using the two stable offer IDs. Travelers may choose a different
combination from their independent lists; the client or service then
recalculates combined price, arrival gap, and shared trip time without reranking
the destination.

## 7. Implementation order

1. Finish and merge the normalized `FlightOffer` contract, fixture provider,
   scored flight-pair selector, and four-category option selector.
2. Reconcile the three-airport constraint from the destination-fixture branch.
3. Add a `ResolvedLocation` contract and Duffel Places adapter.
4. Implement individual eligibility filters.
5. Connect the pair and option selectors to the recommendation service.
6. Expose the recommended pair and individual option lists in the
   recommendation response.
7. Add the live Duffel offer adapter with caching, bounded concurrency, logging,
   and fixture fallback.
