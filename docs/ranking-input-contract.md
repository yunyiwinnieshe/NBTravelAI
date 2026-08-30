# Ranking Input Contract

This contract defines the confirmed, normalized input passed to the
deterministic ranking system after clarification and user confirmation.

## Fields

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
- `budget_usd`: Maximum round-trip airfare plus half of one shared hotel room.
- `max_one_way_travel_minutes`: Maximum one-way flight itinerary duration,
  including layovers and excluding ground travel to or from airports.
- `preferences.temperature_range`: Optional confirmed daytime-temperature
  range in Celsius.
- `preferences.interest_tags`: Zero or more supported interest tags.

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

The ranking input does not contain raw user messages, qualitative temperature
terms, unresolved origins, unsupported interests, vibes, or LLM reasoning.
