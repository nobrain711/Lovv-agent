# V2_34 — Modify Intent Schema

> Purpose: contract for the teammate implementing the real Intent Agent modify path.
> Source priority: `V2_31_SESSION_HANDOFF.md` overrides older `V2_11` seed-reject wording. Front request shape remains `V2_30_MODIFY_REQUEST_SCHEMA.md`.

---

## 0. Scope

This document defines the **Intent Agent output** for itinerary modification.

It does not redefine the front request. V2_38 is now the front input source of
truth: request `currentOrder` is the canonical itinerary order for modify target
resolution. Backend checkpoint/state is fallback only when request
`currentOrder` is missing or empty.

The request still sends:

- `entryType: "modify"`
- `threadId`
- `itineraryRevision`
- `rawModifyQuery`

The front does **not** send `edit_ops`.

Intent parses `rawModifyQuery`, resolves target items against request
`currentOrder`, and emits a typed `modify_intent` for Supervisor/Planner.
If request `currentOrder` is unavailable, backend state itinerary context is used
as a fallback.

Current executable scope is intentionally narrow:

1. single `REPLACE` without a new replacement query
2. single `REPLACE` with a new replacement query
3. multiple `REPLACE` ops, each with or without a replacement query
4. city change through rediscovery

Everything else is backlog unless explicitly listed below.

---

## 1. Top-Level Shape

```json
{
  "intent_type": "modification",
  "status": "ok",
  "thread_id": "thread-id",
  "itinerary_revision": "rev-001",
  "raw_modify_query": "경주로 도시를 바꿔줘",
  "kind": "city_change",
  "edit_ops": [],
  "city_change": {
    "target_city_id": "KR-47-130",
    "target_city_name": "경주시",
    "city_preference_query": "경주로 도시를 바꿔줘",
    "carry_over_themes": true,
    "carry_over_festivals": true,
    "avoid_city_ids": []
  },
  "clarification": null,
  "unsupported_reasons": [],
  "routing_hint": "city_select_rediscovery",
  "audit": {}
}
```

### Fields

| field | type | required | meaning |
|---|---:|---:|---|
| `intent_type` | `"modification"` | yes | Discriminator. |
| `status` | `"ok" \| "needs_clarification" \| "unsupported"` | yes | Whether backend may execute. |
| `thread_id` | string | yes | Checkpoint resume key copied from request. |
| `itinerary_revision` | string | yes | Stale-detection token copied from request. |
| `raw_modify_query` | string | yes | Original modify utterance, non-empty. |
| `kind` | `slot_replace \| city_change \| backlog` | yes | Intent class. |
| `edit_ops` | `EditOperation[]` | yes | Non-empty only for `slot_replace`. |
| `city_change` | `CityChangeIntent \| null` | yes | Non-null only for `city_change`. |
| `clarification` | `Clarification \| null` | yes | Non-null when `status=needs_clarification`. |
| `unsupported_reasons` | string[] | yes | Non-empty when `status=unsupported`. |
| `routing_hint` | string | yes | Supervisor hint, not final authority. |
| `audit` | object | yes | Parser trace for tests/debugging. |

---

## 2. Status And Routing

| status | kind | routing_hint | downstream |
|---|---|---|---|
| `ok` | `slot_replace` | `planner_apply_edit` | Planner edit mode. Skip profile/city_select/festival. |
| `ok` | `city_change` | `city_select_rediscovery` | Re-run city discovery with requested city or city preference. |
| `needs_clarification` | any | `response_packager_wait_user` | Ask user; do not execute edit. |
| `unsupported` | `backlog` | `response_packager_notice` | Explain unsupported modify scope. |

`routing_hint` is intentionally a hint. Supervisor still decides the next node from state.

---

## 3. EditOperation

```json
{
  "op_id": "op-1",
  "op": "REPLACE",
  "target": {
    "item_id": "item-2",
    "content_id": "attraction#127691",
    "item_type": "attraction",
    "day": 1,
    "order": 2,
    "target_text": "이이 유적",
    "resolution": "exact"
  },
  "condition": {
    "replacement_query": "조용하고 한적한 자연 산책로를 천천히 걸을 수 있는 장소.",
    "replacement_query_raw": "조용히 산책하기 좋은 자연",
    "query_required": true,
    "theme": "자연·트레킹",
    "mood": "quiet",
    "place_type": "walk",
    "location": null,
    "avoid_content_ids": ["attraction#127691"]
  },
  "seed_policy": {
    "target_is_seed": false,
    "policy": "not_seed"
  }
}
```

### EditOperation Rules

1. `op` is always `"REPLACE"` in V2.0.
2. `target.item_id` is preferred. `content_id` is included for audit and fallback.
3. `target.resolution` is one of:
   - `exact`: one item resolved
   - `ambiguous`: multiple possible items
   - `unresolved`: no item resolved
4. `condition.replacement_query` is nullable.
   - `null`: simple replacement. Planner should use the target slot context, original item theme/subtype, and current itinerary constraints.
   - string: query-constrained replacement. Planner should use this as the slot-local retrieval query.
5. `condition.replacement_query_raw` preserves the short phrase extracted from the user, while `replacement_query` is a HyDE-style retrieval sentence.
6. `condition.query_required=false` means no separate slot-local retrieval query was requested; then both `replacement_query` and `replacement_query_raw` must be `null`.
7. `condition` must describe only the replacement slot, not a full itinerary rewrite.
8. `avoid_content_ids` should include the replaced item so Planner does not immediately pick the same place unless no alternative exists and policy allows fallback.
9. Single vs multiple replace is represented only by `edit_ops.length`.
10. All `edit_ops` in V2.0 use `op="REPLACE"`. There is no `ADD`, `REMOVE`, `MOVE`, or reorder op.

---

## 4. Seed Policy

Latest V2 policy is **not** "seed always rejected".

| target | Intent behavior | Planner behavior |
|---|---|---|
| non-seed item | emit `policy=not_seed` | replace normally |
| seed item, same-theme request | emit `policy=same_theme_required` | may replace only with same theme |
| seed item, different-theme/city-changing request | `needs_clarification` or `unsupported` | do not execute |

Seed policy shape:

```json
{
  "target_is_seed": true,
  "policy": "same_theme_required",
  "required_theme": "역사·전통"
}
```

Intent may set `required_theme` only when it can read the original item theme from checkpoint-enriched context. If not available, omit it and Planner must derive it from checkpoint.

---

## 5. CityChangeIntent

`city_change` is for requests that keep the itinerary-generation goal but change the destination city.

```json
{
  "target_city_id": "KR-47-130",
  "target_city_name": "경주시",
  "city_preference_query": "경주로 바꿔줘",
  "carry_over_themes": true,
  "carry_over_festivals": true,
  "avoid_city_ids": ["KR-42-210"]
}
```

City change rules:

1. City change does not create `edit_ops`.
2. If the user names one supported city and it resolves to a city id, set `target_city_id`.
3. If the user gives only a city preference phrase without a resolvable id, set `target_city_id=null` and keep `city_preference_query`.
4. `carry_over_themes=true` unless the user explicitly changes themes.
5. `carry_over_festivals=true` unless the user explicitly drops festival mode.
6. City change routes to city discovery/anchored rediscovery, not planner edit mode.
7. If the city phrase is ambiguous, return `needs_clarification`.

### 5.1 City Change Adapter Design

City-change execution is not wired in the current step. The adapter should be added
between Supervisor and City Select, not inside Intent.

Adapter input:

- `intent.modify_intent.city_change`
- current checkpoint/session context
- request `currentOrder` as canonical current itinerary order
- backend itinerary order only as fallback
- previous `city_select_input` or equivalent generation request context

Adapter output:

- a fresh `intent.city_select_input`
- `execution_mode = "city_discovery"` unless `target_city_id` is present
- `destination_id = target_city_id` when the user named a specific city
- original themes/query/month/trip type carried over unless the modify utterance changes them
- `preferred_region_ids`/city preference hints derived from `city_preference_query` when no target city is resolved
- `disliked_region_ids` including cities already used in the same session

Important exclusion rule:

When rerunning city discovery for a modify city-change request, exclude both:

1. the current itinerary city, and
2. any city that was added or tried earlier in the same session.

This prevents the rediscovery loop from returning to a city the user already moved
away from, and prevents newly added session cities from being proposed again as a
"different" destination. The exclusion should be carried as city ids, not names.

The adapter may still allow the explicit `target_city_id` if the user directly named
that city. In that case, exclusion applies to alternative/reserve candidates only.

---

## 6. Clarification Cases

Intent must return `status=needs_clarification` when execution would be unsafe.

Required cases:

- target item cannot be resolved
- multiple items match the same target phrase
- same slot receives contradictory conditions
- multiple ops conflict with each other
- user asks to change a seed in a way that is not same-theme
- city name resolves to multiple possible cities

Clarification shape:

```json
{
  "reason_code": "modify_target_ambiguous",
  "prompt": "어떤 장소를 바꿀까요?",
  "options": [
    {
      "option_id": "target:item-2",
      "label": "1일차 2번째 장소",
      "apply": {"target_item_id": "item-2"}
    }
  ]
}
```

---

## 7. Unsupported Backlog Cases

Return `status=unsupported`, `kind=backlog` for recognized but non-V2.0 requests.

Backlog reasons:

- `add_place`
- `remove_place`
- `reorder_only`
- `reset_all_without_city_target`
- `trip_length_change`
- `travel_month_change`
- `transport_mode_replan`
- `whole_itinerary_mood_rebuild`
- `reservation_or_booking`

Important distinction:

- Front drag-and-drop order changes are already represented by `currentOrder`; backend should accept that order as current truth.
- Natural-language reorder-only requests are not V2.0 edit ops.

---

## 8. Examples

### 8.1 Single Replace Without New Query

User:

```text
1일차 오후 장소만 다른 곳으로 바꿔줘.
```

Output:

```json
{
  "intent_type": "modification",
  "status": "ok",
  "thread_id": "thread-1",
  "itinerary_revision": "rev-001",
  "raw_modify_query": "1일차 오후 장소만 다른 곳으로 바꿔줘.",
  "kind": "slot_replace",
  "routing_hint": "planner_apply_edit",
  "edit_ops": [
    {
      "op_id": "op-1",
      "op": "REPLACE",
      "target": {
        "item_id": "item-2",
        "content_id": "attraction#127691",
        "item_type": "attraction",
        "day": 1,
        "order": 2,
        "target_text": "1일차 오후 장소",
        "resolution": "exact"
      },
      "condition": {
        "replacement_query": null,
        "replacement_query_raw": null,
        "query_required": false,
        "theme": null,
        "mood": null,
        "place_type": null,
        "location": null,
        "avoid_content_ids": ["attraction#127691"]
      },
      "seed_policy": {
        "target_is_seed": false,
        "policy": "not_seed"
      }
    }
  ],
  "city_change": null,
  "clarification": null,
  "unsupported_reasons": [],
  "audit": {}
}
```

Planner interprets `replacement_query=null` and `query_required=false` as "replace using the original slot context".

### 8.2 Single Replace With New Query

User:

```text
1일차 오후 이이 유적 말고, 조용히 산책하기 좋은 자연 쪽으로 바꿔줘.
```

Output:

```json
{
  "intent_type": "modification",
  "status": "ok",
  "thread_id": "thread-1",
  "itinerary_revision": "rev-001",
  "raw_modify_query": "1일차 오후 이이 유적 말고, 조용히 산책하기 좋은 자연 쪽으로 바꿔줘.",
  "kind": "slot_replace",
  "routing_hint": "planner_apply_edit",
  "edit_ops": [
    {
      "op_id": "op-1",
      "op": "REPLACE",
      "target": {
        "item_id": "item-2",
        "content_id": "attraction#127691",
        "item_type": "attraction",
        "day": 1,
        "order": 2,
        "target_text": "이이 유적",
        "resolution": "exact"
      },
      "condition": {
        "replacement_query": "조용하고 한적한 자연 산책로를 천천히 걸을 수 있는 장소.",
        "replacement_query_raw": "조용히 산책하기 좋은 자연",
        "query_required": true,
        "theme": "자연·트레킹",
        "mood": "quiet",
        "place_type": "walk",
        "location": null,
        "avoid_content_ids": ["attraction#127691"]
      },
      "seed_policy": {
        "target_is_seed": false,
        "policy": "not_seed"
      }
    }
  ],
  "city_change": null,
  "clarification": null,
  "unsupported_reasons": [],
  "audit": {}
}
```

### 8.3 Multiple Replace

User:

```text
1일차 오후는 다른 곳으로 바꾸고, 2일차 점심 전 장소는 바다 전망 있는 곳으로 바꿔줘.
```

Output:

```json
{
  "intent_type": "modification",
  "status": "ok",
  "thread_id": "thread-1",
  "itinerary_revision": "rev-001",
  "raw_modify_query": "1일차 오후는 다른 곳으로 바꾸고, 2일차 점심 전 장소는 바다 전망 있는 곳으로 바꿔줘.",
  "kind": "slot_replace",
  "routing_hint": "planner_apply_edit",
  "edit_ops": [
    {
      "op_id": "op-1",
      "op": "REPLACE",
      "target": {
        "item_id": "item-2",
        "content_id": "attraction#127691",
        "item_type": "attraction",
        "day": 1,
        "order": 2,
        "target_text": "1일차 오후",
        "resolution": "exact"
      },
      "condition": {
        "replacement_query": null,
        "replacement_query_raw": null,
        "query_required": false,
        "theme": null,
        "mood": null,
        "place_type": null,
        "location": null,
        "avoid_content_ids": ["attraction#127691"]
      },
      "seed_policy": {
        "target_is_seed": false,
        "policy": "not_seed"
      }
    },
    {
      "op_id": "op-2",
      "op": "REPLACE",
      "target": {
        "item_id": "item-5",
        "content_id": "attraction#2501001",
        "item_type": "attraction",
        "day": 2,
        "order": 2,
        "target_text": "2일차 점심 전 장소",
        "resolution": "exact"
      },
      "condition": {
        "replacement_query": "탁 트인 바다 전망을 감상할 수 있는 해안 장소.",
        "replacement_query_raw": "바다 전망 있는 곳",
        "query_required": true,
        "theme": "바다·해안",
        "mood": null,
        "place_type": null,
        "location": null,
        "avoid_content_ids": ["attraction#2501001"]
      },
      "seed_policy": {
        "target_is_seed": false,
        "policy": "not_seed"
      }
    }
  ],
  "city_change": null,
  "clarification": null,
  "unsupported_reasons": [],
  "audit": {}
}
```

### 8.4 City Change

User:

```text
도시는 경주로 바꿔줘.
```

Output:

```json
{
  "intent_type": "modification",
  "status": "ok",
  "thread_id": "thread-1",
  "itinerary_revision": "rev-001",
  "raw_modify_query": "도시는 경주로 바꿔줘.",
  "kind": "city_change",
  "edit_ops": [],
  "city_change": {
    "target_city_id": "KR-47-130",
    "target_city_name": "경주시",
    "city_preference_query": "경주로 바꿔줘",
    "carry_over_themes": true,
    "carry_over_festivals": true,
    "avoid_city_ids": ["KR-51-150"]
  },
  "clarification": null,
  "unsupported_reasons": [],
  "routing_hint": "city_select_rediscovery",
  "audit": {}
}
```

### 8.5 Backlog

User:

```text
2박 3일 말고 3박 4일로 늘려줘.
```

Output:

```json
{
  "intent_type": "modification",
  "status": "unsupported",
  "kind": "backlog",
  "edit_ops": [],
  "city_change": null,
  "unsupported_reasons": ["trip_length_change"],
  "routing_hint": "response_packager_notice"
}
```

---

## 9. Implementation Checklist

- Parse front request into this schema only after checkpoint/current itinerary context is available.
- Resolve targets to `item_id`; do not let Planner guess vague text.
- Preserve `thread_id`, `itinerary_revision`, and `raw_modify_query`.
- Emit `slot_replace` with one or more `REPLACE` ops.
- Emit `city_change` without `edit_ops` for destination city changes.
- Mark seed targets with `same_theme_required` instead of rejecting by default.
- Return clarification for ambiguous or contradictory executable edits.
- Return unsupported/backlog for add/remove/reorder-only/date/length/reset-all requests.
- Never write long-term profile from modify utterances.
