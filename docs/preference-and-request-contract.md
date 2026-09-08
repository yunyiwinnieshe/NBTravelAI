# Travel AI Preference and Request Contract

**Owners:** Winnie and Ivy  
**Status:** Approved V1 contract and implemented Pydantic request shape
**Purpose:** Define the canonical trip request, hard constraints, soft
preferences, clarification behavior, and deterministic preference features.

## V1 decisions

- Travel AI supports exactly two travelers with **different resolved metro-area
  or airport origins**. Same-origin requests are outside V1 because they do
  not exercise the fair-meeting-destination problem.
- Dates must be exact and the start date must be today or later. A trip lasts
  three through seven calendar days, inclusive.
- Preferences belong to each traveler, not the trip as a whole. This lets the
  system show each person's preference satisfaction separately.
- Lodging, food, activities, local transportation, booking, and payment are
  outside V1. A budget covers only that traveler's estimated round-trip
  airfare.

## Canonical request shape

The conversational flow may accept free text and qualitative terms. The LLM
normalizes them into this validated structure before deterministic ranking:

```json
{
  "travelers": [
    {
      "origin": "Boston, MA",
      "budget_usd": 2000,
      "max_travel_time_hours": 8,
      "preferences": {
        "temperature_range": {
          "minimum_celsius": 20,
          "maximum_celsius": 30
        },
        "interest_tags": ["food", "museums"]
      }
    },
    {
      "origin": "San Francisco, CA",
      "budget_usd": 1800,
      "max_travel_time_hours": 7,
      "preferences": {
        "temperature_range": {
          "minimum_celsius": 15,
          "maximum_celsius": 23
        },
        "interest_tags": ["nature", "outdoor_activities"]
      }
    }
  ],
  "start_date": "2026-10-09",
  "end_date": "2026-10-13"
}
```

`origin` is initially free text. Before ranking, the system resolves it to a
canonical metro-area or airport ID. It asks a clarification question when an
origin is unresolved or ambiguous, such as Vancouver, British Columbia versus
Vancouver, Washington.

## Hard constraints

Hard constraints are filters, never score penalties. A city is excluded when
the request or every available flight option for either traveler violates one.

### Origins

- Resolve each free-text origin to a canonical airport or metro-area ID.
- Require two distinct resolved origins in V1.
- Ask for clarification rather than guessing an ambiguous origin.

### Dates

- Require exact `start_date` and `end_date`.
- Reject past dates and an end date before the start date.
- Allow only three through seven calendar days, inclusive.

### Per-person budget

- Each budget covers that traveler's estimated round-trip airfare only.
- Each traveler must independently stay within their budget.
- Lodging and all other trip expenses are excluded from this total.

```text
traveler_total = selected_round_trip_flight_total
```

### Maximum travel time

- Measure the duration of each traveler's one-way itinerary.
- Include flight and layover time.
- Exclude travel to and from airports.
- Each traveler must independently stay within their stated maximum.

## Soft preferences

Soft preferences affect the score of an eligible city; they do not reject it.
Each traveler may provide any combination of temperature and interests. Tag
order does not matter and duplicate tags are removed during
normalization.

### Temperature

A traveler may provide a numeric daytime-temperature range or a qualitative
term. The system states the inferred range and lets the traveler confirm or
correct it:

- `cool`: 8–18°C
- `mild`: 15–23°C
- `warm`: 20–30°C
- `hot`: 27–38°C

V1 compares this request with historical monthly average daytime temperature
from fixtures. It is an estimate, not a weather forecast. A destination inside
the range receives a full temperature match; the score declines gradually as
the destination moves outside it. If no temperature preference is provided,
temperature is omitted from that traveler's preference score.

### Interests

The initial controlled interest vocabulary is:

```text
beach, mountain, food, museums, nightlife, nature,
outdoor_activities, shopping
```

All selected interests within a traveler's request have equal weight. Cities
store applicable tags; adding a new tag requires annotating the relevant city
records, not assigning a numeric value to every city.

## Preference scoring and fairness

Calculate a separate preference score for each traveler. Average only the
categories that traveler supplied:

```text
traveler_preference_score = average(
  temperature_match, if provided,
  interest_match, if provided
)
```

A traveler with no preferences has no preference score; the system does not
assign zero. When both travelers have a score:

```text
combined_preference_score = average(preference_score_A, preference_score_B)
preference_gap = abs(preference_score_A - preference_score_B)
preference_fairness = 1 - preference_gap
```

Report each traveler’s score and `preference_gap` separately. Preference
fairness is not travel-time fairness, cost fairness, or the overall city score.
If only one traveler provides preferences, use that person's preferences for
city matching but omit preference-fairness reporting. If neither provides
preferences, omit preference matching and preference fairness.

## Natural-language normalization and clarification

The LLM may map documented synonyms to the controlled vocabulary, for example:

- “great restaurants” → `food`
- “clubbing” → `nightlife`
- “hiking” → `outdoor_activities`
- “parks and scenery” → `nature`

Mappings must be documented and covered by tests. If wording could safely map
to more than one tag, the LLM asks a clarification question. It must not add
new controlled tags or decide eligibility, prices, or scores.

Unsupported preferences are never silently ignored. The system explains that a
preference is unsupported and lets the traveler replace it, remove it, or
continue without it. Ranking begins only after unresolved unsupported
preferences are confirmed as removed or deferred. The conversation state may
retain the original text for transparency, but it does not enter deterministic
scoring.

## Implementation boundary

The implemented `TripRequest` stores preferences inside each traveler. V1
accepts only a confirmed temperature range and controlled interest tags;
vibes and unsupported free-text preferences never enter deterministic scoring.
