# Planning-session origin resolution

Fixture mode remains the default. Set `ORIGIN_RESOLUTION_PROVIDER=duffel` to use
Duffel Place Suggestions for planning-session departure origins. This is
independent of `EXTRACTION_PROVIDER`: DeepSeek extracts place text, while
application code verifies the place and selects airports. Duffel test-mode
credentials are required, and the path must be a durable, writable SQLite file:

```sh
mkdir -p var
export ORIGIN_RESOLUTION_PROVIDER=duffel
export ORIGIN_LOCATION_DB_PATH=var/origin_locations.sqlite3
export DUFFEL_ACCESS_TOKEN='<test-mode token>'
```

The database stores only a generated internal location ID, Duffel place ID for
explicit airports or a city/state grouping key for city origins,
display name, country, optional city IATA code, explicit airport choice, and up
to three selected airport codes. It does not store the token or conversation
messages. A unique key on Duffel place ID and explicit airport choice reuses
the same ID after a process restart or across workers. Planning *sessions*
remain in memory; their persistence is a separate V2 task.

## Accepted input and response behavior

- A US city with a state abbreviation or full state name, such as
  `Portland, OR` or `Portland, Oregon`; an exact airport code such as `PWM`;
  or an exact airport name returned by Duffel.
- The resolver uses Duffel's verified city and airport identities, then joins
  airport codes to the versioned OurAirports snapshot. A city/state match must
  have a matching Duffel city place with an associated commercial airport in
  the requested municipality and state, or a matching Duffel airport city name
  with an airport in the requested state. This handles cities for which Duffel
  returns airport suggestions but no city suggestion.
- Only scheduled large or medium airports survive. Cities retain at most three
  ranked airports; an explicit eligible airport is retained alone.
- A missing state, several plausible places, an unverified place, or no
  eligible airport produces a clarification question. The prior draft values
  stay intact. Duffel transport and storage failures also leave the previous
  session draft intact.
- A resolved origin outside the fixture flight provider's coverage receives a
  clear `no_match` message after explicit confirmation. This ticket does not
  connect live flight searches or expand flight fixtures.

The API response keeps the existing draft and `pending_questions` contract.
The origin question has a traveler-specific field path and source message, so
DeepSeek can interpret the next reply without inventing a code. `origin_id` is
the application's saved location ID, never a model-generated or Duffel ID.

## OurAirports snapshot refresh

The bundled [airport reference](../src/travel_ai/fixtures/airport_reference.json)
is schema `v2`, sourced from the public OurAirports CSV on **2026-10-18**. It
contains 502 US airports with scheduled service and large or medium airport
type. Region and municipality fields support conservative city/state matching.
Refresh quarterly and before a tagged demo or release:

```sh
curl -L --fail https://davidmegginson.github.io/ourairports-data/airports.csv \
  -o /tmp/travelai-airports.csv
python -m travel_ai.scripts.build_airport_reference \
  /tmp/travelai-airports.csv --source-date YYYY-MM-DD
python -m pytest tests/test_airport_selection.py tests/test_live_origin_resolution.py
```

Use the actual CSV download date for `--source-date`; review the record count
and diff before committing. The generated snapshot contains no credentials.
The tests use mocked Duffel HTTP responses and make no live requests.

## Live sandbox smoke check

With a Duffel **test-mode** token in `DUFFEL_ACCESS_TOKEN`, run:

```sh
.venv/bin/python -m travel_ai.scripts.duffel_origin_smoke
```

This makes real Place Suggestions requests for `Portland, OR`, `PDX`, and
`Portland`. It checks city/airport resolution, the selected airport limit,
stable ID reuse, and clarification for the city without a state. It prints no
credentials or Duffel response body and uses a temporary location database.
The live check is separate from pytest so offline and CI runs stay reliable.
