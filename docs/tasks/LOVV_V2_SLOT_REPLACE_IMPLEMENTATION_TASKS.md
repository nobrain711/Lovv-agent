# V2_45 Slot Replace Implementation Directive

Status: implemented baseline - slot replace and day regenerate live verified
Date: 2026-07-04

This document freezes the implementation direction for the first slot-replace slice.
It should be read before editing planner modify code.

## 1. Scope

Implement slot replacement, including small multi-slot replacement batches.

In scope:
- One or more target itinerary item replacements.
- One day-level regeneration request.
- `currentOrder` as the canonical latest itinerary order.
- Planner-owned replacement execution.
- Reserve-pool first path for queryless replace.
- Retrieval fallback when reserve pool is empty.
- Query-only retrieval path when `modifyQuery` has replacement conditions.
- Route feasibility check after replacement.
- Sequential fold for multi-edit: each op sees the order/reserve/exclusion state produced by previous ops.

Out of scope for this slice:
- Parallel slot application.
- Atomic rollback for multi-edit.
- Add/remove/reorder/trip length/booking execution.
- City-change execution.
- Full-trip regeneration.

## 2. Confirmed Decisions

### 2.1 `currentOrder` is canonical

For modify requests, frontend-provided `currentOrder` is the latest itinerary truth.

Priority:
1. `request.currentOrder`
2. `state.currentOrder`
3. planner output fallback
4. response payload fallback

Planner/response fallback exists only for local smoke or legacy checkpoint recovery.

### 2.2 Planner owns slot replacement

Intent only parses the edit plan.
Supervisor only routes.
Planner performs candidate choice, route feasibility checks, itinerary mutation, and planner output refresh.

Accepted modify intent shape:
- `status=ok`
- `kind=slot_replace`
- one or more `edit_ops[]`
- `routing_hint=planner_apply_edit`

Unsupported/clarification shapes continue to route to response packager.

### 2.3 Use a separate `apply_edit` planner step

Do not reuse `retry_alternative_city`.

`retry_alternative_city` is city-level fallback.
Slot replace is itinerary editing inside the selected city.

Target planner flow for single slot replace:

```text
intent
  -> supervisor
  -> planner.apply_edit
  -> explain_itinerary
  -> response_packager
```

The existing generation flow remains:

```text
retrieve_places -> route_days -> assemble_itinerary
```

### 2.4 Multi-edit uses sequential fold

Do not apply slot edits in parallel.

Reason:
- each op rewrites the planner output;
- candidate exclusion and reserve consumption are shared;
- route feasibility for a day depends on previous replacements.

Policy:
- process `edit_ops[]` in parser order;
- pass the updated `currentOrder`, planner output, reserve pool, exclusion set, and edit memory to the next op;
- allow partial success;
- do not rollback earlier successful ops when a later op fails.

Output:
- successful ops are recorded in `applied_edits[]`;
- failed ops are recorded in `failed_edits[]`;
- single-op compatibility fields `applied_edit` / `failed_edit` may still expose the latest single result;
- if all ops fail, use the existing failed clarification path;
- if at least one op succeeds, return the updated itinerary and a notice such as `2개 수정 중 1개를 반영했습니다.`

## 3. Slot Replace Behavior

### 3.1 Target resolution

Each target must resolve to exactly one `currentOrder` item.

Supported target forms:
- day/order: `1일차 두 번째 장소`
- title mention: supported by parser, but live smoke samples should prefer day/order.

Ambiguous or missing target:
- `needs_clarification`
- `reason_code=modify_target_unresolved` or `modify_target_ambiguous`

### 3.2 Queryless replace

Example:

```text
1일차 두 번째 장소 바꿔줘.
```

Policy:
1. Look at the current fold's reserve pool.
2. Exclude current itinerary item ids and the target content id.
3. Prefer same city.
4. Prefer extracted replacement theme, then active themes, then target item theme.
5. If reserve pool is empty, run retrieval again inside the same city.

Retrieval fallback should be conservative:
- same `destinationId` / selected city id
- target item theme or active themes
- no invented soft preference

Destination city source priority:
1. `request.destinationId` / intent modify destination id
2. `state.intent.city_select_input.destination_id`
3. `currentOrder[].cityId` from the target/current itinerary
4. response/planner destination fallback for smoke or legacy checkpoint recovery only

### 3.3 Query-based replace

Example:

```text
1일차 두 번째 장소를 조용한 자연 산책지로 바꿔줘.
```

Policy:
1. Do not prioritize old reserve pool.
2. Retrieve with the replacement query only.
3. Do not hard-filter by theme during retrieval.
4. If parser extracted a replacement theme, use it as a soft priority only.
5. If no theme exists, rank by raw replacement-query similarity after city and existing-item exclusion.
6. Exclude all current itinerary content ids plus already consumed candidates.

Reason:
The user gave a new edit condition, so the replacement candidate should be grounded in that condition rather than in the previous generation reserve.

### 3.4 Seed target policy

Follow the seed policy from `V2_34_MODIFY_INTENT_SCHEMA.md`.

Policy:
- non-seed target: replace normally.
- seed target with same-theme request: replace only with a same-theme candidate.
- seed target with different-theme, city-changing, or broad reset request: do not execute in this slice.

Intent should mark this with `edit_ops[].seed_policy`.
Planner must enforce it again before candidate selection.

Accepted planner policy values:
- `not_seed`
- `same_theme_required`

If a seed target cannot be replaced under the required same-theme policy:
- return `failed_edit`.
- do not silently replace it with an off-theme place.
- do not keep the old seed while reporting success.

## 4. Route Feasibility

After candidate insertion:
- Recompute route for the affected day only.
- Reject candidates that violate hard leg policy.
- Try the next candidate if route is invalid.

Slot replacement must preserve all non-target days and all non-target slots.
Do not rerun full `route_days`, do not move other places across days, and do not reorder other days.

Seed replacement follows the same route rule:
- the replacement inherits the seed role for that slot.
- the affected day is rerouted with the replacement and the other existing places in that day.
- hard leg checks apply between the replacement and the rest of the affected-day places.
- if every same-theme seed replacement candidate violates hard leg policy, return `failed_edit`.

Current intended hard policy:
- car/transit hard leg: 120 minutes
- walk policy may be stricter and should preserve existing walking warnings

If every candidate fails:
- produce modification failure notice
- do not silently keep the old item as if the edit succeeded

## 5. Planner State Contract

Add or use:

```text
state.planner.modify_context.reserve_pool
state.planner.modify_context.applied_edit
state.planner.modify_context.failed_edit
state.planner.modify_context.applied_edits
state.planner.modify_context.failed_edits
```

`reserve_pool` should contain candidate places not selected in the latest generation/regeneration.
`failed_edit` / `failed_edits[]` should include enough information for the response layer to ask a useful follow-up or show a partial-apply notice.

Recommended `failed_edit` fields:
- `reason_code`
- `target`
- `tried_candidate_count`
- `failed_route_candidate_count`
- `current_theme`
- `requested_theme`
- `suggested_theme_expansion_options`

The existing `validation_result.itinerary_structure.reserve` is an audit surface, not the long-term modify state contract.
Prefer `state.planner.modify_context.reserve_pool` for edit execution.

## 6. Slot Replace Memory Contract

Use `memory` for session-level slot replacement history that must survive planner/response refreshes.
This is not long-term preference memory; it is current-thread edit memory.

Add or use:

```text
state.memory.modify_history.replaced_content_ids
state.memory.modify_history.replaced_place_ids
state.memory.modify_history.edit_events
```

### 6.1 Replaced attraction history

Slot replacement must remember removed attractions so later replacements do not reinsert them.

Candidate exclusion must include:
- current `currentOrder` content ids / place ids
- target item content id / place id
- `modify_intent.condition.avoid_content_ids`
- `memory.modify_history.replaced_content_ids`
- `memory.modify_history.replaced_place_ids`

### 6.2 Clarification payload guarantee

Frontend sends clarification responses as clarification payloads, not as modify payloads.
Therefore, a pending clarification followed by slot replacement is not a supported ambiguous input case for this slice.

`memory.pending_clarification` remains the resume source for clarification entry points only.
Modify entry points should not try to merge old pending clarification with new slot edits.

## 7. Day Regenerate Behavior

Example:

```text
1일차 전체 바꿔줘.
```

Policy:
- Treat this as a planner edit op distinct from slot replace.
- Regenerate only the requested day.
- Preserve all non-target days.
- Use `currentOrder` as the canonical itinerary order.
- Queryless path uses the current reserve pool first, then conservative same-city residual retrieval.
- Query path retrieves with the day-level replacement query.
- Candidate selection uses medoid-first ordering and hard-leg feasibility.
- Existing itinerary content ids and previous replacement history are excluded.

Important boundary:
- Normal service modify requests should run with the same `threadId/sessionId` so checkpointed `planner_output`, reserve pool, and memory are available.
- If checkpoint state is missing but `currentOrder` is present, the implementation falls back to `currentOrder` to avoid empty itinerary responses. This is a defensive behavior, not the primary service path.

## 8. Response Contract

Successful slot replace response:
- `response_status=modification_pending`
- destination preserved
- itinerary updated with replacement item
- include modification metadata if available:
  - target item
  - replacement item
  - changed slot
  - notice/reason

Successful multi slot replace response:
- `response_status=modification_pending`
- updated itinerary includes every successful op;
- `explainability.userNotice` states how many requested edits were applied;
- failed ops are summarized without hiding successful ops.

Failed slot replace response:
- no fake success
- ask the user whether to expand or relax the replacement theme/scope.
- include clear options when available, for example:
  - keep the current place
  - try a broader theme
  - search with active themes only
  - ask the user for a more specific query
- do not silently broaden the theme without user confirmation.

Clarification scope for this slice:
- build the structured `END_WAIT_USER` clarification payload from `failed_edit`.
- rely on the existing LangGraph interrupt/resume plumbing to pause and receive a resume value.
- `broaden_replace_theme` resumes slot replace with relaxed theme constraints.
- `keep_current_itinerary` preserves the current itinerary as `modification_pending`.
- other natural-language clarification answer handling remains later scope.

## 9. Implementation Tasks

1. Update current order resolver.
   - request `currentOrder` first.
   - preserve coordinates and public fields from frontend payload.

2. Route slot replace edit ops to planner.
   - allow one or more `edit_ops[]`.
   - keep add/remove/reorder/trip length/booking out of this slice.

3. Add supervisor route for `planner_apply_edit`.
   - only for `kind=slot_replace`, `status=ok`, one or more ops.

4. Add planner `apply_edit` step.
   - for multi-edit, fold over `modify_intent.edit_ops[]` in order.
   - read canonical `currentOrder`.
   - enforce each op's `seed_policy`.
   - select replacement candidate.
   - update planner output.

5. Add reserve pool state.
   - preserve latest generation reserves in `state.planner.modify_context.reserve_pool`.

6. Add modify history memory.
   - preserve removed attractions in `replaced_content_ids` / `replaced_place_ids`.
   - exclude memory history when picking future candidates.

7. Add candidate selection.
   - queryless: reserve first, retrieval fallback.
   - query-based: retrieval only.
   - theme from modify query: soft priority, not retrieval filter.

8. Add route feasibility retry.
   - reject hard-leg violations.
   - try next candidate.

9. Add response packaging support.
   - expose successful replacement as `modification_pending`.
   - expose failed replacement as `END_WAIT_USER` clarification when theme/scope expansion is possible.
   - include theme expansion options from `failed_edit`.
   - for partial multi-edit success, return the updated itinerary with a partial-apply notice instead of discarding successful edits.
   - stop at payload/interrupt readiness; do not execute resume answers yet.

10. Add smoke samples.
   - `v2_mod_01_slot_replace_with_query.json`
   - `v2_mod_02_slot_replace_no_query.json`
   - `v2_mod_03_multi_slot_replace.json` for sequential multi-edit verification
   - Live verification must first create the base itinerary from
     `docs/tasks/results/v2_intent_mocks/generation/v2_gen_04_history_2d1n.json`,
     because these modify samples were built from that generated itinerary.

11. Add day regenerate baseline.
   - parse one-day full replacement requests.
   - route `kind=day_regenerate` to planner apply-edit.
   - regenerate only the requested day.
   - preserve non-target days.
   - use checkpoint planner state when present and `currentOrder` fallback only as a defense.

## 10. Related Files

Intent:
- `src/lovv_agent_v2/agents/intent/modify_parser.py`
- `src/lovv_agent_v2/agents/intent/modify_slots.py`
- `src/lovv_agent_v2/agents/intent/modify_current_order.py`

Supervisor:
- `src/lovv_agent_v2/agents/supervisor/router.py`

Planner:
- `src/lovv_agent_v2/agents/planner/subgraph.py`
- `src/lovv_agent_v2/agents/planner/state_adapter.py`
- `src/lovv_agent_v2/agents/planner/steps/`

Response:
- `src/lovv_agent_v2/agents/response_packager/`

Samples:
- `docs/tasks/results/v2_intent_mocks/modify/`

## 11. Final Progress Update - 2026-07-06

Implemented:
- deterministic and LLM-assisted slot target parsing, including Korean ordinal forms;
- same-day multi-slot replace with sequential fold;
- queryless slot replace reserve-first path with same-city residual retrieval fallback;
- query-based slot replace with no theme hard filter and optional theme soft priority;
- existing itinerary item exclusion for newly retrieved candidates;
- seed same-theme enforcement and route-infeasible failure handling;
- day regenerate for one requested day, preserving other days;
- currentOrder fallback for day regenerate when checkpoint planner output is missing;
- supervisor guards for stale modify responses and day-regenerate routing;
- empty-itinerary weather audit completion to avoid supervisor/weather loops.

Live evidence:
- `docs/tasks/results/v2_general_live_smoke/20260705T175519Z_residual-slot-queryless.json`
  - queryless slot replace: `영해향교 -> 축산항`;
  - response stayed 2 days / 6 items.
- `docs/tasks/results/v2_general_live_smoke/20260705T181943Z_residual-dayregen-queryless.json`
  - day 1 regenerated to `축산항`, `철암산 화석산지 (경북 동해안 국가지질공원)`, `부흥해변`;
  - day 2 preserved;
  - response stayed 2 days / 6 items.

Focused verification:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\v2\test_planner_slot_replace_backfill.py tests\v2\test_planner_day_regenerate.py tests\v2\test_planner_apply_edit.py tests\v2\test_planner_apply_edit_multi.py tests\v2\test_planner_apply_edit_theme_priority.py tests\v2\test_planner_apply_edit_seed_policy.py tests\v2\test_weather_alternative.py::test_weather_node_marks_empty_itinerary_as_processed_after_explain tests\v2\test_modify_intent_dispatch.py::test_resolve_modify_intent_keeps_rule_day_regenerate_without_prompt -q
```

Result: `18 passed`.
