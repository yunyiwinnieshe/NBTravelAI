# Design decisions

## 2026-09-16 — Internal IDs for confirmed origin locations

**Status:** Accepted design; live resolver and persistence implementation deferred.

### Decision

In live mode, the application assigns an opaque internal location ID after a
traveler's origin has been resolved and confirmed. `TripRequest.origin_id`
references that saved location; it is not generated from the user's place-name
text, an IATA code, or a Duffel place ID.

The saved record must retain the internal ID, display name, country, provider
name and provider place ID, approved departure airports, and an IATA city code
when available. A later request for the same confirmed place should reuse the
stored location ID rather than generate a new ID for every search. City-level
origins and explicit airport selections must remain distinguishable.

The resolver must disambiguate places before assigning or reusing an ID. Flight
search retrieves the saved location to obtain its airport or city codes. An
LLM may extract text and present verified choices, but must not invent IDs or
airport mappings. OurAirports provides airport-reference facts, not these IDs.

### Rationale

Readable names such as `new_york_ny` are convenient test keys, but names can be
ambiguous or change. Separating internal identity from display names and
provider identifiers keeps requests stable and provider-independent. Reusing
location records also prevents different IDs from making one origin appear to
be two distinct origins.

### Scope and follow-up

- Keep deterministic fixture IDs such as `boston_ma` and `new_york_ny` and the
  existing fixture airport mappings for offline tests.
- Implement ID generation together with live location resolution, persistence,
  lookup, and reuse. Do not replace fixture keys with random IDs in isolation.
- Keep the existing `origin_id` request field for now. `origin_location_id` is a
  possible future contract rename, not part of this documentation change.
- Use `OriginAirportMapping` to describe the mapping from one origin to its
  search airports. The model, `load_origin_airport_mappings()` loader, and
  related provider variables now use mapping terminology.
- Choose the ID format and storage/reuse strategy during implementation. The
  generated format must satisfy the schemas, or schema changes must accompany
  the implementation. No database, ID generator, or new endpoint is added here.

See [Flight search and pairing](flight-search-and-pairing.md),
[Preference and request contract](preference-and-request-contract.md), and
[Ranking input contract](ranking-input-contract.md).
