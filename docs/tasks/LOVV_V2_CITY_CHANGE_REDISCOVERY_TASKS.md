# V2_46 City Change Rediscovery Directive

Status: implementation directive draft - after slot replace
Date: 2026-07-04

This document freezes the follow-up direction for city-change modify requests.
It is separate from `V2_45_SLOT_REPLACE_IMPLEMENTATION_DIRECTIVE.md`, which should stay focused on slot replacement.

## 1. Scope

Handle modify requests that ask to change the itinerary city.

In scope:
- explicit target city changes
- targetless "another city" changes
- city exclusion history for the current modify sequence
- rerunning the right generation path after city change

Out of scope:
- slot replacement
- multi-edit transaction handling
- long-term user preference memory

## 2. City Change Modes

### 2.1 Explicit target city

Example:

```text
도시는 경주로 바꿔줘.
```

Intent must resolve:

```text
modify_intent.kind = city_change
modify_intent.city_change.target_city_id
modify_intent.city_change.target_city_name
modify_intent.routing_hint = planner_direct_anchor
```

Routing:

```text
intent -> supervisor -> planner anchored regeneration -> explain_itinerary -> response_packager
```

Policy:
- use the resolved V2 `city_id` as the destination anchor.
- preserve the previous raw query, active themes, trip type, dates, and festival preference.
- clear stale `city_select`, `planner`, and `response` state before regeneration.
- preserve `memory`.

### 2.2 Targetless rediscovery

Example:

```text
다른 도시로 바꿔줘.
```

Intent must not invent or guess a target city.

Target output:

```text
modify_intent.kind = city_change
modify_intent.city_change.target_city_id = null
modify_intent.routing_hint = city_select_rediscovery
```

Routing:

```text
intent -> supervisor -> city_select -> planner generation -> explain_itinerary -> response_packager
```

Policy:
- preserve the previous raw query, active themes, trip type, dates, and festival preference.
- clear `destination_id`, `destination_label`, `city_key`, and `ddb_pk`.
- add the current city and `memory.modify_history.excluded_city_ids` to city exclusions.
- use `city_select_input.disliked_city_ids` as the official city exclusion field.
- do not route directly to planner, because there is no destination anchor.

## 3. City Change Memory Contract

Use `memory` for current-thread city-change history.
This is not long-term preference memory.

Add or use:

```text
state.memory.modify_history.excluded_city_ids
state.memory.modify_history.edit_events
```

`excluded_city_ids` must include cities already used in the same modify sequence so that repeated "another city" requests do not return the same city.

Recommended update points:
- before explicit city-change regeneration, add the previous selected city.
- before targetless rediscovery, add only the previous selected city.
- after successful rediscovery, do not immediately add the newly selected city.
- on the next city-change request, the newly selected city is treated as the current city and excluded then.
- preserve this memory when `city_select`, `planner`, and `response` are cleared.

Rediscovery exclusion input:

```text
city_select_input.disliked_city_ids
  = current_city_id + memory.modify_history.excluded_city_ids
```

Deduplicate while preserving order.

## 4. Frontend Payload Boundary

Frontend does not need to send `selectedCity` separately if `currentOrder` and `destinationId` are present.

Useful inputs:
- `destinationId`: latest itinerary city id when known.
- `currentOrder[]`: latest visible itinerary order.
- `rawModifyQuery`: user text.

Backend can derive the current city from:
1. `request.destinationId`
2. `currentOrder[].cityId`
3. previous response destination
4. previous planner selected city

If none exists, targetless rediscovery should ask clarification rather than silently rerun broad discovery.

## 5. Implementation Tasks

1. Extend Intent city-change parsing.
   - explicit city name -> `planner_direct_anchor`.
   - `다른 도시로 바꿔줘` / `다른 지역으로 바꿔줘` -> `city_select_rediscovery`.
   - no fake target city.

2. Extend state update for city rediscovery.
   - clear destination anchor fields.
   - preserve original query/theme/trip/festival constraints.
   - preserve `memory`.
   - clear stale `city_select`, `planner`, and `response`.
   - set `city_select_input.disliked_city_ids` from current city plus memory exclusions.

3. Route rediscovery through city_select.
   - supervisor must not send targetless city-change directly to planner.
   - city_select must consume `city_select_input.disliked_city_ids`.

4. Add city-change memory updates.
   - store previous city in `excluded_city_ids`.
   - carry `excluded_city_ids` across follow-up modify turns.

5. Add response packaging verification.
   - destination id and name must reflect the new selected city.
   - response should remain `modification_pending` after successful city change.
