# V2 Weather Alternative Itinerary Implementation Tasks

Status: implementation directive - remaining work after first weather-risk slice
Date: 2026-07-05

This document tracks the remaining implementation scope for weather-aware alternative itineraries.
The source directive is `docs/reports/v2/V2_32_ALTERNATIVE_ITINERARY_WEATHER_DIRECTIVE.md`.

## 1. Current Baseline

Implemented in the first slice:
- Planner has a `weather_alternative` post-assembly step.
- Weather risk is loaded from `city_monthly_weather_risks.json` by `(city_id, travel_month)`.
- Threshold logic is isolated in a policy module so ratios and notice rules can be changed later.
- Itinerary items preserve `indoor_outdoor` internally and expose additive `indoorOutdoor` in public item payloads.
- Missing weather-map coverage is non-fatal:
  - `weather_audit.status = unavailable`
  - `weather_audit.unavailable_reason = city_weather_map_missing`
- Response packager asks `weather_alternative_available` when the weather audit says a backup can be offered.
- `use_weather_alternative` resume generates a same-city backup at request time.

Not implemented yet:
- Weather-aware live smoke matrix.

## 2. Design Constraints

The primary itinerary must not be silently mutated.

Weather alternatives should be generated on demand, not precomputed on every normal response.
Reason:
- many users will not choose the backup;
- reserve/route checks add latency to the happy path;
- the backup should be generated against the checkpointed current itinerary the user is responding to;
- failure to build a backup can be explained at the moment the user asks for it.

Weather handling is a backup surface:
- same city only;
- same trip type and day count;
- preserve seed/festival items unless explicitly unsafe and intentionally replaceable;
- replace only weather-sensitive non-seed slots;
- do not use alternative-city fallback for weather.

Weather map gaps must not block generation.
If the city is outside the weather map, record audit only and return the normal itinerary.

## 3. Remaining Implementation Tasks

### 3.0 Proposed module boundary

Keep the weather decision policy separate from candidate replacement.

Logical units:

| unit | responsibility |
|---|---|
| `weather_alternative.policy` | weather risk level, exposure ratio, notice/offer decision |
| `weather_alternative.exposure` | `indoor_outdoor` counting and sensitive-slot detection |
| `weather_alternative.reserve_pool` | read reserve candidates from planner state without knowing weather policy |
| `weather_alternative.indoor_search` | run same-city fallback retrieval when reserve candidates are insufficient |
| `weather_alternative.replacement` | choose indoor/mixed replacements and preserve day/order shape |
| `weather_alternative.route_check` | affected-day feasibility check using the same constraints as slot replace |
| `response_packager` | expose `alternativeItinerary` and ask whether to view it |

The policy module should not know where candidates came from.
The replacement module should not decide whether the weather risk is high enough to ask the user.

### 3.1 Request-time reserve-based alternative generation

Use existing planner candidate reserves before doing any new retrieval.
This step runs only after the user chooses `use_weather_alternative`.

Candidate source priority:
1. `state.planner.modify_context.reserve_pool`
2. `planner_output.validation_result.itinerary_structure.reserve`
3. selected-but-unused same-city planner pool if exposed later
4. same-city fallback retrieval with indoor-first selection

Reserve candidate contract:

```json
{
  "placeId": "attraction#...",
  "title": "...",
  "city_id": "KR-...",
  "theme_tags": ["..."],
  "indoor_outdoor": "indoor|outdoor|mixed|unknown",
  "latitude": 0.0,
  "longitude": 0.0,
  "distance": 0.0
}
```

Required fields for replacement:
- `placeId` or `contentId`
- `city_id`
- `latitude`
- `longitude`
- `indoor_outdoor`

Candidates missing coordinates are ignored for route-safe replacement.

Replacement policy:
- target only outdoor/mixed non-seed items;
- keep an existing seed when it is already `indoor`;
- if the seed is weather-sensitive, choose the replacement seed first by day-center medoid distance, then search feasible combinations for the remaining targets;
- prefer `indoor`;
- allow `mixed` only when there are not enough indoor candidates;
- add a user notice when `mixed` replacements are included;
- never use `unknown` as a weather-safe replacement in the first slice;
- keep the original day/order shape;
- require same city id;
- exclude current itinerary content ids.
- exclude already used replacement ids while building the backup.
- preserve festival/seed slots unless a later policy explicitly allows replacing them.

Output:
- `state.planner.weather_alternative_result`
- `planner_output.alternative_itinerary` only in the response produced after user confirmation
- `validation_result.weather_audit.alternative_generation`

Alternative generation audit:

```json
{
  "status": "not_needed|generated|no_candidate|route_infeasible",
  "target_slot_count": 3,
  "replaced_slot_count": 2,
  "candidate_source": "modify_context.reserve_pool|validation_result.reserve|same_city_retrieval",
  "rejected_counts": {
    "current_itinerary": 0,
    "wrong_city": 0,
    "missing_coordinates": 0,
    "not_weather_safe": 0,
    "route_infeasible": 0
  }
}
```

Failure mode:
- if reliable reserve candidates are insufficient, silently run same-city retrieval without theme filtering;
- select fallback candidates as `indoor` first, then `mixed` if needed;
- if fallback retrieval also cannot produce feasible replacements, return a user-visible no-backup notice;
- do not fabricate indoor replacements.
- primary itinerary remains unchanged.

### 3.2 Affected-day route feasibility

Alternative replacements must pass route feasibility for the affected day.

Use the same route constraints already used by slot replace:
- hard leg threshold;
- walk-specific stricter leg threshold;
- affected day only.

If a replacement fails feasibility:
- try the next indoor/mixed candidate combination before giving up;
- if none pass, record `alternative_generation = route_infeasible`;
- keep primary itinerary unchanged.

Route check scope:
- only the day containing the replaced slot is recalculated;
- other days remain byte-for-byte equivalent except metadata/audit additions;
- hard leg threshold follows the current planner hard-leg rule;
- walk-specific threshold applies only when `transport_pref=walk`.

This mirrors slot replace: weather backup is a local patch, not full itinerary regeneration.

### 3.3 Indoor-first retrieval fallback

This fallback is part of the request-time generation path.
Do not ask the user before running it.

Fallback retrieval should:
- search within the same city;
- ignore original themes if reserve candidates are insufficient;
- rank `indoor` first and allow `mixed` only as a shortage fallback;
- prefer weather-resilient indoor subtypes from `attraction_subtypes.json` when ranking;
- exclude current itinerary content ids and already used replacement ids;
- still pass affected-day route feasibility;
- avoid raw weather reason codes in user-facing text.

Indoor-first fallback result states:

| status | meaning |
|---|---|
| `not_needed` | reserve candidates were enough |
| `searched` | same-city fallback retrieval was attempted |
| `generated` | fallback produced feasible replacements |
| `no_candidate` | retrieval returned no usable indoor/mixed candidates |
| `route_infeasible` | candidates existed but could not fit affected-day route constraints |

Only `no_candidate` and `route_infeasible` should produce the final no-backup notice.

### 3.4 Weather clarification and resume

Weather alternatives are not precomputed before asking the user.
The normal response only detects risk and asks whether the user wants a backup.

Target UX:

```text
평년 기준 날씨 리스크가 높은 달이라 야외 일정 비중이 큽니다.
날씨 대체 일정을 보시겠습니까?
```

If the user answers yes:
- read checkpointed `planner_output.itinerary`, `weather_audit`, and reserve pool;
- generate a same-city weather backup at that moment;
- if reserve candidates are insufficient, run same-city retrieval without another user question;
- if feasible, show the backup as `alternativeItinerary` or as the visible itinerary depending on final product UX;
- if reserve plus fallback retrieval are both infeasible, return a clear notice that no reliable weather backup could be made.

If the user answers no:
- keep the primary itinerary unchanged.

Clarification shape:
- `reason_code = weather_alternative_available`
- `then = weather_alternative`
- `options[]`:
  - `use_weather_alternative`
  - `keep_primary_itinerary`

Public option text:

```json
{
  "weather_alternative_available": {
    "_prompt": "평년 기준 날씨 리스크가 높은 달이라 야외 일정 비중이 큽니다. 날씨 대체 일정을 보시겠습니까?",
    "use_weather_alternative": {
      "label": "대체 일정 보기",
      "helperText": "현재 일정을 기준으로 실내 중심 대체 일정을 만들어 보여줍니다."
    },
    "keep_primary_itinerary": {
      "label": "현재 일정 유지",
      "helperText": "대체 일정은 적용하지 않고 현재 일정을 유지합니다."
    }
  }
}
```

Prompt should be shown only if `weather_audit.status = alternative_available` and the checkpoint has enough itinerary context to attempt a backup.

Checkpoint requirements:
- preserve `planner_output.itinerary`;
- preserve `validation_result.weather_audit`;
- preserve reserve candidates or enough same-city planner context to attempt request-time replacement;
- preserve enough response context to repackage after request-time generation.

Implementation split:
- First implement the clarification prompt and checkpoint-safe resume marker.
- Then implement `then=weather_alternative` as request-time backup generation.
- Do not compute backup routes in the normal create/modify response.

Current branch target:
- create `weather_alternative_available` clarification when risk/exposure warrant it;
- ensure checkpoint keeps primary itinerary and reserve context;
- implement `weather_alternative` resume as the entrypoint for actual backup generation.

Current expected behavior:
- normal response asks whether the user wants a weather backup;
- yes triggers request-time backup generation;
- no keeps the primary itinerary.

### 3.5 Policy configurability

Keep all tunable ratios in the weather policy module.

Currently fixed defaults:
- medium notice ratio: `0.40`
- high notice ratio: `0.25`
- high alternative ratio: `0.50`

Future extension:
- move ratios to config/env only if smoke data shows runtime tuning is needed;
- otherwise keep code-level policy constants for reviewability.

### 3.6 Smoke and analysis

Add a small smoke set before expanding.

Required cases:
- high-risk city-month with outdoor-heavy itinerary;
- high-risk city-month with mostly indoor itinerary;
- medium-risk city-month around threshold boundary;
- low-risk city-month;
- city missing from weather map;
- festival seed included.

Metrics to record:
- weather map coverage rate;
- known exposure ratio;
- weather-sensitive ratio;
- notice level;
- request-time alternative generation status;
- route feasibility failures.

### 3.7 Implementation progress 2026-07-05

Implemented in the current scope:
- `weather_audit.status=alternative_available` now produces `weather_alternative_available` clarification;
- `use_weather_alternative` resume generates the backup at request time;
- backup generation uses indoor reserve candidates first, then mixed candidates if indoor is insufficient;
- same-city fallback retrieval runs without a theme filter and selects indoor first, mixed second;
- mixed replacements add a user-facing notice that some places are indoor/outdoor mixed;
- indoor seeds are preserved; weather-sensitive seeds are replaced first with a day-center medoid candidate and keep their seed flag;
- generated backup slots pass affected-day travel-time hard-leg feasibility before being returned;
- route-infeasible backup combinations are skipped before the primary itinerary is preserved;
- `keep_primary_itinerary` returns the primary itinerary as `modification_pending` without a stale clarification block;
- if indoor/mixed candidates remain insufficient, the primary itinerary is preserved with a failure notice;
- map-missing weather cases remain audit-only and do not produce user-facing weather clarification.

Live smoke evidence:
- `20260705T150402Z_weather-donghae-create.json`
  - input: July 2026, Donghae, `바다·해안`, anchored create;
  - observed: primary response kept the outdoor-heavy coast itinerary and returned `weather_alternative_available`;
  - evidence: public items preserved `indoorOutdoor=outdoor`, proving exposure tags survive to response packaging.
- `20260705T150511Z_weather-donghae-alternative.json`
  - input: `use_weather_alternative` resume for the same Donghae session;
  - observed: primary itinerary was preserved because indoor-only replacement candidates were insufficient in that earlier slice;
  - evidence: no fabricated indoor backup was returned.
- `20260705T152115Z_weather-donghae-mixed-create.json`
  - input: July 2026, Donghae, same coast request after `mixed` fallback support;
  - observed: create still returned `weather_alternative_available`;
  - evidence: weather prompt remained stable after allowing `mixed` as a shortage fallback.
- `20260705T152202Z_weather-donghae-mixed-alternative.json`
  - input: `use_weather_alternative` resume after `mixed` fallback support;
  - observed: primary itinerary was still preserved because usable indoor/mixed candidates were insufficient;
  - evidence: failure path remained conservative even after broadening from indoor-only to indoor+mixed.
- `20260705T150740Z_weather-gangneung-create.json`
  - input: July 2026, Gangneung, anchored coast create;
  - observed: primary response returned `weather_alternative_available`;
  - evidence: weather clarification is not Donghae-specific and works for another mapped coastal city.
- `20260705T150814Z_weather-gangneung-alternative.json`
  - input: `use_weather_alternative` resume for Gangneung;
  - observed: response returned 6 replacement items, all `indoorOutdoor=indoor`;
  - evidence: request-time backup generation can produce a visible indoor-centered itinerary when same-city candidates are available.

Live verification conclusion:
- Create path: weather risk detection and clarification offer are working for mapped high-risk coastal cities.
- Resume path: successful backup generation works for Gangneung; conservative no-backup preservation works for Donghae when candidates are insufficient.
- Response contract: `indoorOutdoor` is present in public itinerary items and weather backup responses stay backward compatible.

Still open in this scope:
- fallback candidate ranking is currently exposure-first only and does not yet use subtype duration/resilience weights;
- weather backup smoke coverage is still limited to a few city-month cases.

## 4. Acceptance Criteria

The remaining implementation is complete when:
- primary itinerary remains unchanged in all weather cases;
- weather audit is present for every planner output;
- map-missing cities return normal itineraries without user-visible weather notice;
- high-risk outdoor-heavy cases ask whether the user wants a weather backup;
- choosing yes attempts backup generation from checkpointed itinerary/reserve context;
- reserve shortage triggers same-city fallback retrieval without an extra question;
- choosing no preserves the primary itinerary;
- if reserve plus fallback retrieval both fail, the response explains that no reliable weather-safe backup was found;
- normal create/modify responses do not precompute route-safe backup itineraries;
- response payload shape remains backward compatible;
- targeted unit tests and at least one live smoke batch pass.
