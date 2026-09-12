# Duffel Test-Mode Flight Provider

**Status:** Provider and mocked tests implemented; recommendation-service
integration remains a later task  
**Scope:** Place suggestions and round-trip flight searches through Duffel test
mode only

## Boundary

`DuffelFlightOfferProvider` implements the provider-independent
`FlightOfferProvider` interface. It performs this translation:

```text
FlightSearchQuery
    → one Duffel Offer Request per approved airport pair
    → validate the response fields Travel AI consumes
    → normalize each result into FlightOffer
    → deduplicate, sort deterministically, and retain at most 20 offers
```

Neither the recommendation service nor ranking code receives raw Duffel JSON.
The fixture provider remains the default until the service workflow is wired.

`DuffelAirportPlaceProvider` uses `GET /places/suggestions` with either a text
query or latitude, longitude, and radius. It expands airports nested under city
results, includes standalone airport results, keeps the configured country, and
deduplicates by IATA code. Those records are still only candidates. The
provider-independent airport selector joins them to commercial-service
reference data, removes noncommercial facilities, ranks large before medium
airports and then by distance, and retains at most three.

## Configuration

Create a local `.env` if useful, but do not commit it. The application does not
automatically load `.env`, so export the values in the shell before running the
manual command:

```bash
export DUFFEL_ACCESS_TOKEN="your test token"
export DUFFEL_BASE_URL="https://api.duffel.com"
export DUFFEL_SUPPLIER_TIMEOUT_MS="10000"
```

The token must remain outside source code, committed fixtures, command output,
screenshots, and logs. Rotate any token that has previously been shared.

## Manual sandbox search

Choose future dates supported by the Duffel sandbox and start with one airport
pair:

```bash
python -m travel_ai.scripts.duffel_search \
  --origin-id boston_ma \
  --destination-id chicago_il \
  --origin-airports BOS \
  --destination-airports ORD \
  --departure-date 2027-02-09 \
  --return-date 2027-02-13
```

Comma-separated airport groups are also accepted, up to the three-airport
limits enforced by `FlightSearchQuery`. A `3 × 3` query makes nine offer
requests, so one pair is preferable for initial testing.

The command prints normalized `FlightOffer` JSON. It never prints the access
token and is not executed by pytest or GitHub Actions.

## Current policies

- One adult passenger in economy class is searched for each traveler.
- Origin city text may be resolved through Duffel Places even when the city is
  not in the destination candidate pool.
- Duffel place results do not decide which airports are major or commercial;
  deterministic reference-data filtering remains a separate service step.
- Configuration rejects tokens that do not start with `duffel_test_` so the
  project cannot accidentally access Duffel live mode.
- A round trip is sent as outbound and return slices.
- Duffel returns segment times as airport-local datetimes without UTC offsets.
  The provider attaches each airport's IANA `time_zone` before comparisons.
- Only USD offers enter the normalized V1 contract.
- Duplicate Duffel offer IDs are returned once.
- At most 20 offers continue to pairing, ordered by price, travel time,
  connections, and stable internal offer ID.
- Authentication, rate-limit, transport, HTTP, and response-shape failures use
  separate controlled exceptions.
- Airport-pair requests currently run sequentially and fail the overall search
  if any request fails.
- CI tests use `httpx.MockTransport` and never call Duffel.

Duffel test mode exercises the real HTTP integration but may return unrealistic
prices and schedules. Travel AI therefore continues to use curated fixtures for
deterministic ranking tests and demonstrations.
