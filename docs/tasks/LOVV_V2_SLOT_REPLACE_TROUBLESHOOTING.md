# LOVV V2 Slot Replace Troubleshooting

Date: 2026-07-04
Scope: single slot replacement live verification

This document records implementation-time issues found while running generation -> slot replace live smoke.

## 1. Intent Mock Is Not A Live Create Payload

Observed:
- `docs/tasks/results/v2_intent_mocks/generation/v2_gen_04_history_2d1n.json` failed in `run_general_live_smoke.py`.
- Error: `AgentCore invocation must contain a /recommendations request payload`.

Cause:
- The file is an `intent_output` fixture.
- AgentCore live entrypoint expects a frontend-style create request.

Resolution:
- Added a live create payload derived from the same scenario:
  - `docs/tasks/results/v2_intent_mocks/generation/v2_gen_04_history_2d1n_live_payload.json`
- Live modify tests must use the actual generated itinerary's `currentOrder`, not the static fixture's old city/order.

## 2. Static Modify Samples Can Mismatch Live Generation

Observed:
- The original slot replace samples were based on a Gyeongju current order.
- The live generation from the same high-level history scenario selected Yeongdeok.
- Applying the Gyeongju current order to the Yeongdeok session produced failures such as:
  - `slot_replace_no_candidate`
  - stale target context like `경주 계림`

Cause:
- Slot replace is anchored to the latest `currentOrder`.
- If `currentOrder.destinationId/currentOrder[].cityId` does not match the persisted session itinerary, the planner searches the wrong city/context.

Resolution:
- Build modify payloads from the live generation output before testing slot replace.
- Created live-derived samples:
  - `v2_mod_live_slot_replace_no_query_from_v2_gen_04.json`
  - `v2_mod_live_slot_replace_with_query_from_v2_gen_04.json`

## 3. Stale `failed_edit` Reused Across Requests

Observed:
- After one failed slot replace, the next modify request could immediately route to response packager with the old `failed_edit`.
- The new request never reached planner apply-edit.

Cause:
- `state.planner.modify_context.failed_edit` persisted in checkpoint state.
- Supervisor treated any existing `failed_edit` as current.

Resolution:
- `applied_edit` and `failed_edit` now include the current request id.
- Supervisor only trusts slot replace edit results that match the current request id.
- Regression test:
  - `test_supervisor_ignores_stale_failed_slot_replace_for_new_request`

## 4. Supervisor Loop After Slot Replace Success

Observed:
- A successful slot replace could timeout.
- The graph reached response, but supervisor did not recognize the response as current slot replace completion.

Cause:
- Existing "already has current modify response" guard primarily covered city-change.
- Slot replace response needed the same end condition.

Resolution:
- Supervisor now treats a slot replace response as complete when:
  - response payload recommendation id matches current request id, or
  - current request has matching `applied_edit`.
- Regression test:
  - `test_supervisor_ends_after_slot_replace_response_payload`

## 5. Duplicate Replacement Notice

Observed:
- Repeated slot replace in the same session could return:
  - `요청한 장소를 같은 일정 안에서 대체했습니다. 요청한 장소를 같은 일정 안에서 대체했습니다.`

Cause:
- Previous planner output could hold user notice as an already-joined string.
- Apply-edit appended the replacement notice again after converting the string as an iterable/sequence-like value.

Resolution:
- Apply-edit normalizes string/list/tuple notices before appending the replacement notice.
- Duplicate replacement notice is collapsed to one entry.
- Regression tests:
  - `test_apply_edit_deduplicates_replacement_notice`
  - `test_apply_edit_deduplicates_string_replacement_notice`

## 6. Missing Target Slot Clarification

Observed:
- A modify request may target a slot that is not present in `currentOrder`.
- Example: user asks to replace `4일차 2번째 장소` when the current itinerary has only 2 or 3 days.

Decision:
- Do not silently fail.
- Do not treat this as a no-candidate replacement problem.
- Return structured `END_WAIT_USER` clarification with `reasonCode=modify_target_unresolved`.

Behavior:
- Prompt asks the user to specify which day/order should be changed.
- Options:
  - `revise_slot_target`
  - `keep_current_itinerary`
- `failed_edit.context.requested_target` preserves the unresolved requested slot.

Regression test:
- `test_response_packager_packages_unresolved_slot_clarification`

## 7. Confirmed Live Results

Base generation:
- `20260704T094135Z_slot-replace-base-v2-gen-04-loopfix.json`
- selected city: `영덕군`
- itinerary: 2 days, 6 items

Queryless replace:
- `영해향교` -> `영해 3·1 의거탑`
- result: `20260704T094243Z_slot-replace-mod-live-no-query-loopfix.json`

Query-based replace:
- `영해향교` -> `벌영리 메타세콰이어길`
- final dedup result: `20260704T095132Z_slot-replace-mod-live-with-query-dedup2.json`
- notice: single replacement notice

Additional generation case checks:

1. Coast/vibrant generation
   - base: `20260704T095639Z_slot-replace-base-v2-gen-02.json`
   - selected city: `여수시`
   - query-based slot replace: `20260704T095835Z_slot-replace-gen02-mod-with-query.json`
   - result: `모사금해수욕장` -> `거문도해수욕장`
   - status: success, single replacement notice
   - seed query-based slot replace: `20260704T100220Z_slot-replace-gen02-seed-with-query.json`
   - seed result: `거문도 신선바위` -> `거문도해수욕장`
   - seed flag: replacement preserved `isSeed=true`

2. Art/sense generation
   - base: `20260704T095717Z_slot-replace-base-v2-gen-05.json`
   - selected city: `인제군`
   - queryless slot replace: `20260704T095910Z_slot-replace-gen05-mod-no-query.json`
   - target: `진부령미술관`
   - result: `slot_replace_no_candidate`
   - behavior: correct failure path, returned `END_WAIT_USER` clarification asking whether to broaden the condition or keep the current place.
   - note: `tried_candidate_count=0`, so this case is useful for checking reserve-pool/retrieval fallback coverage for sparse art pools.

Additional queryless replace checks:

3. Nature+coast generation
   - base: `20260704T100533Z_slot-replace-base-v2-gen-07.json`
   - selected city: `동해시`
   - queryless slot replace: `20260704T100831Z_slot-replace-gen07-mod-no-query.json`
   - result: `추암해변` -> `어달해변`
   - status: success, single replacement notice
   - query without theme keyword: `20260704T101809Z_slot-replace-gen07-query-no-theme-active.json`
   - query: `1일차 2번째 장소를 조금 더 한적한 곳으로 바꿔줘.`
   - result after active-theme priority: `추암해변` -> `베틀바위`
   - note: no replacement theme keyword was extracted; planner retrieved by query and preferred the request's active themes rather than only the target slot theme.
   - repeated modify in same session: `20260704T101859Z_slot-replace-gen07-second-no-query.json`
   - second result: `냉천공원` -> `두타산협곡마천루`
   - repeated modify behavior: first replacement remained in the itinerary, second replacement applied, replacement notice stayed de-duplicated.

4. Nature/car generation
   - base: `20260704T100612Z_slot-replace-base-v2-gen-12.json`
   - selected city: `서천군`
   - queryless slot replace: `20260704T100900Z_slot-replace-gen12-mod-no-query.json`
   - target: `국립생태원에코리움`
   - result: `slot_replace_no_candidate`
   - note: `tried_candidate_count=0`, so this is another sparse reserve/retrieval fallback case.

5. Coast+art generation
   - base: `20260704T100649Z_slot-replace-base-v2-gen-15.json`
   - selected city: `신안군`
   - queryless slot replace: `20260704T100930Z_slot-replace-gen15-mod-no-query.json`
   - result: `채일봉 전망대` -> `천사대교`
   - status: success, single replacement notice

6. History+art/vibrant generation
   - base: `20260704T100727Z_slot-replace-base-v2-gen-17.json`
   - selected city: `종로구`
   - queryless slot replace: `20260704T101005Z_slot-replace-gen17-mod-no-query.json`
   - result: `북촌한옥마을` -> `성균관대학교 인문사회과학캠퍼스박물관`
   - status: success
   - note: response notice preserved the existing walk/transit advisory and appended the replacement notice once.

## 8. Verification Commands

Focused tests:

```powershell
.venv\Scripts\python.exe -m pytest tests\v2\test_intent_dispatch_contract.py tests\v2\test_modify_current_order.py tests\v2\test_modify_intent_rule_parser.py tests\v2\test_modify_intent_llm.py tests\v2\test_planner_apply_edit.py tests\v2\test_planner_apply_edit_notice.py tests\v2\test_supervisor_graph.py tests\v2\test_response_packager_node.py -q
```

Graph compile:

```powershell
.venv\Scripts\python.exe -c "from lovv_agent_v2.core.graph import compile_v2_graph; compile_v2_graph(); print('compile_v2_graph ok')"
```

## 9. 2026-07-06 Day Regenerate Timeout Was a Weather Routing Loop

Observed:
- `1일차 전체 바꿔줘` day-regenerate live smoke timed out at about 180 seconds.
- A stream log showed the graph had already passed `intent -> supervisor -> planner -> supervisor -> explain_itinerary`.
- After that, it looped rapidly between:

```text
supervisor -> weather_alternative -> supervisor -> weather_alternative -> ...
```

Cause:
- `weather_alternative_node` returned early when `planner_output.itinerary` was empty.
- That early return did not write `validation_result.weather_audit`.
- Supervisor therefore saw post-explain planner output with no completed post-explain weather audit and routed back to `weather_alternative` forever.

Resolution:
- Empty itinerary now receives a weather audit:
  - `status=unavailable`
  - `evaluation_stage=post_explain`
  - `unavailable_reason=empty_itinerary`
- Supervisor can then continue to response packaging instead of looping.
- Regression test:
  - `test_weather_node_marks_empty_itinerary_as_processed_after_explain`

## 10. 2026-07-06 Checkpoint-less Modify Is a Defense Test, Not the Service Path

Observed:
- A queryless day-regenerate smoke using a fresh session completed after the weather-loop fix, but initially returned `dayCount=0`, `itemCount=0`.

Cause:
- Normal modify requests are expected to use the same `threadId/sessionId` as the original generation.
- The fresh-session smoke had `currentOrder`, but no checkpointed `planner_output`.
- `day_regenerate_update` built the new itinerary from previous planner output only, so there was no base item list to rewrite.

Decision:
- The primary service path remains checkpoint-backed modify.
- `currentOrder` is still a valid frontend truth source and should prevent catastrophic empty responses when checkpoint state is missing or stale.

Resolution:
- `day_regenerate_update` now falls back to full `currentOrder` when previous planner output has no itinerary.
- This is defensive behavior for local smoke and degraded recovery, not a replacement for checkpointer-backed modify.
- Regression test:
  - `test_apply_edit_day_regenerate_uses_current_order_without_checkpoint_output`

Live confirmation:
- `docs/tasks/results/v2_general_live_smoke/20260705T181943Z_residual-dayregen-queryless.json`
- Result:
  - destination: `KR-47-770 / 영덕군`
  - day 1 regenerated
  - day 2 preserved
  - `dayCount=2`, `itemCount=6`
