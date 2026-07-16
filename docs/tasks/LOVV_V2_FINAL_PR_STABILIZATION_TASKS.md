# LOVV V2 Final PR Stabilization Tasks

작성일: 2026-07-15
상태: 구현 및 검증 완료
대상: 현재 PR의 telemetry redaction, modify 안정성, multi-edit 설명 계약
Troubleshooting: `docs/tasks/LOVV_V2_FINAL_PR_STABILIZATION_TROUBLESHOOTING.md`

## 1. 목표

전체 V2 테스트가 통과하더라도 실제 SDK 및 LangGraph E2E에서 남아 있는 네 가지 merge blocker를 제거한다.

이번 작업은 기능 확장이 아니라 다음 계약을 최종 안정화하는 작업이다.

- span에는 sanitize되지 않은 예외 문자열을 남기지 않는다.
- checkpoint가 없는 수정 요청은 500이 아니라 public clarification으로 종료한다.
- 여러 장소를 교체하면 변경된 장소 전체를 설명 대상으로 보존한다.
- LLM이 설명 대상 전체를 실제로 작성한 경우에만 설명 완료로 기록한다.

## 2. 재현된 기준선

2026-07-15 현재 production 코드를 수정하지 않고 최소 재현한 결과다.

| blocker | 실제 관측 결과 | 판정 |
|---|---|---|
| invocation span 원문 예외 노출 | 실제 OpenTelemetry SDK span에 exception event 2개가 생기고, 하나와 status description에 원문 secret 포함 | 재현 완료 |
| multi-edit 설명 범위 유실 | 2개 replacement가 적용됐지만 `explanation_item_place_ids`에는 마지막 replacement 1개만 존재 | 재현 완료 |
| fresh-thread city change 500 | `intent -> supervisor -> profile` 이후 `SchemaValidationError: missing required field: country` | 재현 완료 |
| 빈/부분 LLM 설명의 완료 오판 | 빈 배열과 일부 target만 포함한 결과가 validator를 통과하고 `used_llm=true`, `completed=true` 기록 | 재현 완료 |

관련 기존 테스트 15건은 모두 통과했다. 따라서 기존 테스트를 수정해 통과시키는 것이 아니라, 위 재현을 먼저 실패 테스트로 추가해야 한다.

## 3. 공통 구현 원칙

1. `src/lovv_agent_v2`를 canonical source로 수정한다.
2. 각 scope가 green이 된 뒤 `app/LovvAgentV2/lovv_agent_v2`에 동일하게 반영한다.
3. 새 테스트는 반드시 수정 전 실패를 확인한 뒤 production 코드를 최소 diff로 수정한다.
4. public response envelope와 기존 `reasonCode`, `optionId`, `helperText` 계약은 변경하지 않는다.
5. local E2E는 `LOVV_MEMORY_ENABLED=false`와 건별 60초 제한을 기본으로 한다.
6. 한 blocker의 해결을 위해 planner, intent, telemetry 전체를 재구성하지 않는다.

## 4. 구현 순서

### 4.1 Scope 1: Invocation telemetry 원문 노출 차단

보안 관련 blocker이므로 가장 먼저 처리한다.

수정 대상:

- `src/lovv_agent_v2/common/telemetry_invocation.py`
- `tests/v2/test_telemetry_invocation.py`
- app mirror의 동일 파일

구현:

1. `LovvAgentInvocation` span 생성 시 다음 옵션을 명시한다.
   - `record_exception=False`
   - `set_status_on_exception=False`
2. 예외 event와 status는 기존 `_record_span_error()`만 기록하게 한다.
3. `GraphInterrupt`는 error status나 exception event로 기록하지 않는다.
4. JSON metric과 span 양쪽에 동일한 sanitize 정책을 유지한다.

실패 우선 테스트:

- fake tracer의 kwargs만 확인하지 않는다.
- 실제 `TracerProvider`와 in-memory exporter를 사용한다.
- `trace_invocation()` operation이 secret/email을 포함한 예외를 발생시키게 한다.
- context manager 종료 후 완성된 span 전체를 검사한다.

수락 기준:

- exception event는 수동 sanitized event 1개만 존재한다.
- event attributes, stacktrace, status description 어디에도 원문 secret/email이 없다.
- success, error, interrupt 모두 기존 반환/전파 동작을 유지한다.

### 4.2 Scope 2: Fresh-thread city change를 clarification으로 종료

checkpoint가 없는 modify는 실행 가능한 trip intent가 없으므로 새 일정처럼 추측하여 재구성하지 않는다.

수정 대상:

- `src/lovv_agent_v2/agents/intent/modify_parser.py`
- `src/lovv_agent_v2/agents/intent/modify_dispatch.py`
- 필요 시 `src/lovv_agent_v2/agents/intent/modify_reanchor.py`
- `tests/v2/test_missing_itinerary_clarification.py`
- `tests/v2/test_modify_city_change_reanchor.py`
- app mirror의 동일 파일

구현:

1. city-change 문장 파싱은 `currentOrder` 요구보다 먼저 유지한다.
2. rule parser와 LLM fallback이 모두 끝난 뒤 공통 invariant로 persisted `intent.city_select_input`의 유효성을 검사한다.
   - rule parser의 missing-itinerary 결과를 LLM city-change 결과가 다시 덮어쓰지 못하게 한다.
   - parser별 분기가 아니라 최종 normalized modify intent에 동일하게 적용한다.
   - 단순히 mapping이 존재하는지만 보지 않고 `trip_intent_from_intent()`가 재사용 가능한 country, month, trip type, themes, festival flag, raw query를 복원하는지 확인한다.
3. 기존 trip context가 없으면 다음 결과로 종료한다.
   - `status=needs_clarification`
   - `reason_code=modify_missing_current_itinerary`
   - `routing_hint=response_packager_wait_user`
4. 기존 trip context가 있으면 `currentOrder`가 없어도 기존 city-change reanchor를 허용한다.
5. `currentOrder`만으로 country, month, trip type, themes, festival preference를 추측하지 않는다.

실패 우선 테스트:

- 새 `MemorySaver` thread에 `도시는 경주로 바꿔줘.`를 바로 전송한다.
- `SchemaValidationError`가 아니라 `END_WAIT_USER` public clarification을 기대한다.
- `clarification.reasonCode=modify_missing_current_itinerary`와 비어 있지 않은 options를 확인한다.
- 기존 생성 checkpoint가 있는 city change는 계속 `planner_direct_anchor`로 진행하는지 확인한다.
- persisted city input은 있지만 `currentOrder`가 없는 city change도 정상 허용되는지 확인한다.
- LLM fallback이 city change를 반환해도 persisted city input이 없으면 missing-itinerary clarification을 유지하는지 확인한다.

수락 기준:

- fresh-thread city change가 profile/planner로 진입하지 않는다.
- 기존 세션의 도시 변경 및 축제 선호 보존 테스트가 깨지지 않는다.
- slot/day edit의 `currentOrder` 필수 정책은 그대로 유지한다.

### 4.3 Scope 3: Multi-edit 설명 대상 전체 누적

Scope 4가 검증할 정확한 target set을 먼저 만든다.

수정 대상:

- `src/lovv_agent_v2/agents/planner/steps/apply_edit/result.py`
- `src/lovv_agent_v2/agents/planner/steps/apply_edit/explanation_scope.py`
- `tests/v2/test_planner_apply_edit_multi.py`
- `tests/v2/test_itinerary_explanation.py`
- app mirror의 동일 파일

구현:

1. sequential fold에서 성공한 현재 batch의 `applied_edits[]` 전체로 explanation place IDs를 만든다.
2. ID는 적용 순서를 유지하며 중복 제거한다.
3. 부분 성공이면 성공한 replacement만 포함한다.
4. `apply_edit_node` 진입 시 transient edit 결과를 초기화하여 현재 invocation만의 batch를 만든다.
   - 초기화: `applied_edit`, `failed_edit`, `applied_edits`, `failed_edits`
   - 유지: `reserve_pool`, persisted `memory.modify_history`
   - request id 누락이나 재사용 여부에 의존해 batch 경계를 판단하지 않는다.
5. 새 edit가 적용될 때 이전 설명 완료 marker를 초기화한다.
   - `modification_explanation_completed`
   - `modification_explanation_attempted`

실패 우선 테스트:

- 같은 day의 2개 slot 교체 후 두 replacement ID가 모두 남는지 확인한다.
- 서로 다른 day의 2개 slot 교체도 동일하게 확인한다.
- 성공 1개, 실패 1개인 경우 성공 replacement만 남는지 확인한다.
- 같은 place ID가 중복 입력돼도 explanation target은 한 번만 남는지 확인한다.
- 이전 request의 edit history가 새 request target에 포함되지 않는지 확인한다.
- composer request의 `copy_target_item_refs`가 두 변경 항목 모두를 포함하는지 확인한다.

수락 기준:

- `applied_edits`와 `explanation_item_place_ids`의 현재 batch coverage가 일치한다.
- multi-edit의 모든 성공 replacement가 LLM copy 대상이 된다.
- 변경되지 않은 일정 항목은 설명 재생성 대상에 포함되지 않는다.

### 4.4 Scope 4: Planner copy exact coverage 및 완료 판정

Scope 3에서 만든 target set과 LLM 응답을 정확히 비교한다.

수정 대상:

- `src/lovv_agent_v2/agents/response_packager/planner_copy_composer.py`
- `src/lovv_agent_v2/agents/response_packager/explain_itinerary.py`
- `src/lovv_agent_v2/agents/supervisor/explanation_routing.py`
- `tests/v2/test_itinerary_explanation.py`
- `tests/v2/test_supervisor_graph.py`
- app mirror의 동일 파일

구현:

1. `target_item_refs`가 명시된 수정, day regenerate, weather alternative에서만 `item_copies[].item_ref`가 expected target refs와 정확히 일치하도록 검사한다.
   - 일반 일정 생성은 기존 설명 생성 계약을 유지하여 partial output 검증 강화로 인한 전체 fallback 증가를 막는다.
   - validator에 explicit-scope 여부를 전달하여, 내부에서 전체 itinerary ref로 fallback한 경우와 호출자가 변경 scope를 지정한 경우를 구분한다.
2. 다음 결과를 schema failure로 처리한다.
   - 빈 `item_copies`
   - 일부 target 누락
   - target 중복
   - 허용되지 않은 target 추가
3. `planner_copy_generation_used_llm`은 유효한 copy가 실제 적용된 경우에만 `true`로 둔다.
4. `modification_explanation_completed`는 모든 target item에 `copy_source=llm_planner_copy`가 적용된 경우에만 `true`로 둔다.
5. LLM 호출은 완료됐지만 invalid output으로 fallback한 경우를 별도로 기록한다.
   - `modification_explanation_attempted=true`
   - `modification_explanation_completed=false`
   - `planner_copy_generation_used_llm=false`
6. attempted fallback이 supervisor에서 무한 explain 재시도를 만들지 않도록 routing 계약을 보강한다.
7. 다음 새 modify 요청이 오면 Scope 3에서 attempted/completed marker를 다시 초기화한다.
8. weather alternative가 새 explanation scope를 만들 때도 attempted/completed marker를 초기화한다.

실패 우선 테스트:

- expected 1개에 empty output을 반환한다.
- expected 2개에 1개만 반환한다.
- 같은 ref를 두 번 반환한다.
- expected refs 전체를 정확히 한 번씩 반환한다.
- fallback 후 deterministic copy가 유지되고 완료가 false인지 확인한다.
- fallback 후 supervisor가 explain node를 반복하지 않고 response로 진행하는지 확인한다.
- 정확한 multi-edit copy 2개 적용 후 두 item 모두 `copy_source=llm_planner_copy`인지 확인한다.
- 일반 일정 생성의 기존 LLM copy 성공/fallback 동작이 유지되는지 확인한다.
- weather alternative가 이전 modify explanation marker 때문에 설명을 건너뛰지 않는지 확인한다.

수락 기준:

- 실제 copy coverage와 validation marker가 모순되지 않는다.
- invalid LLM output은 deterministic fallback으로 안전하게 종료된다.
- invalid output으로 인한 supervisor/explain loop가 없다.
- 다음 수정 요청에서는 설명 생성이 다시 정상 실행된다.

## 5. Source/App 동기화

네 scope가 각각 green이 된 뒤 canonical source를 app mirror에 반영한다.

검증:

1. 관련 파일의 normalized content가 모두 동일해야 한다.
2. 최종 단계에서는 줄바꿈을 포함한 byte-level mirror 차이도 제거한다.
3. pytest는 `src`를 import하므로, app mirror 자체에 대해 compile/import smoke를 별도로 실행한다.
4. 배포 경로 `agentcore/agentcore.json -> app/LovvAgentV2`를 다시 확인한다.

## 6. 검증 순서

### 6.1 Scope별 focused test

```powershell
$env:PYTHONPATH='src'
$env:LOVV_MEMORY_ENABLED='false'
$env:UV_CACHE_DIR='.cache/uv'

uv run pytest `
  tests/v2/test_telemetry_invocation.py `
  tests/v2/test_missing_itinerary_clarification.py `
  tests/v2/test_modify_city_change_reanchor.py `
  tests/v2/test_planner_apply_edit_multi.py `
  tests/v2/test_itinerary_explanation.py `
  tests/v2/test_supervisor_graph.py -q
```

### 6.2 V2 전체 회귀

- `tests/v2` 전체를 workspace 내부 basetemp로 실행한다.
- 현재 기준선인 `449 passed, 2 subtests passed`보다 테스트 수가 증가해야 한다.
- 기존 테스트 삭제 또는 assertion 완화로 green을 만들지 않는다.

### 6.3 Local memory-off E2E

실행 전 안전 조건:

- shell과 payload 구성 전에 `LOVV_MEMORY_ENABLED=false`를 명시한다.
- `.env`를 읽는 runner라면 dotenv 로딩을 먼저 끝낸 뒤 `LOVV_MEMORY_ENABLED=false`로 다시 덮어쓰고, 그 이후에 entrypoint/harness 모듈을 import한다.
- `_cached_live_harness()`가 이미 생성된 warm process에서 환경변수만 바꾸지 않는다. 각 검증 run은 새 process를 사용하거나 테스트 전 cache를 명시적으로 초기화한다.
- harness가 실제로 local `MemorySaver`를 선택했는지 시작 로그 또는 runtime 설정으로 확인한다.
- memory mode를 확인할 수 없거나 AgentCoreMemorySaver가 선택되면 테스트를 즉시 중단한다.
- 테스트 runner는 memory 사용을 명시적으로 opt-in하지 않는 한 AgentCore Memory를 생성하거나 호출하지 않는다.
- 각 case는 독립 session ID를 사용하되, create -> modify 연속 시나리오만 동일 application thread를 유지한다.

최소 시나리오:

1. fresh-thread city change -> missing-itinerary clarification
2. 정상 생성 -> city change -> 정상 수정
3. 정상 생성 -> 같은 day 2개 slot replace -> 두 변경 항목 모두 LLM copy
4. 정상 생성 -> 서로 다른 day 2개 slot replace -> 두 변경 항목 모두 LLM copy
5. invalid planner copy fixture -> deterministic fallback, no route loop

검증값:

- response status와 clarification reason
- changed item IDs와 explanation target IDs
- 각 changed item의 `copy_source`, `body`, `reason`
- `planner_copy_generation_used_llm`
- `modification_explanation_attempted`
- `modification_explanation_completed`
- supervisor visited node와 route count
- memory mode가 `local_memory_saver`인지 여부

### 6.4 배포 전 smoke

- app mirror import/compile 성공
- 새 session ID로 create 1건
- 같은 application thread에서 city change 1건
- multi-edit 1건
- CloudWatch/trace에서 원문 예외가 노출되지 않는 synthetic error 1건
- 각 invocation은 60초 timeout을 적용한다.

## 7. 최종 수락 기준

- 네 blocker의 수정 전 재현 테스트가 모두 red이고 수정 후 green이다.
- 실제 SDK span에 원문 예외가 존재하지 않는다.
- fresh-thread city change가 500 없이 public clarification으로 종료된다.
- multi-edit의 모든 성공 replacement가 설명 대상 및 LLM copy 결과에 포함된다.
- empty, partial, duplicate planner copy output이 완료로 기록되지 않는다.
- invalid copy fallback 이후 supervisor loop가 발생하지 않는다.
- `src`와 배포 대상 `app`이 동일하다.
- V2 전체 테스트와 local memory-off E2E가 통과한다.
- local E2E 증거에 `LOVV_MEMORY_ENABLED=false`와 `local_memory_saver`가 명시된다.

## 8. 이번 Final 수정에서 제외

- checkpoint actor/session isolation 정책 변경
- AgentCore `PROD` custom endpoint 및 자동 rollback 구성
- day regenerate 기능 확장
- unsupported modify operation 추가 구현
- unrelated 문서 및 smoke evidence 정리
- planner/city-select 전면 리팩터링

위 항목은 이번 네 blocker를 해결하는 데 필요하지 않으므로 별도 작업으로 유지한다.

## 9. 구현 및 검증 결과

2026-07-15 기준 네 blocker의 수정과 검증을 완료했다.

- invocation span은 OpenTelemetry context manager의 자동 예외 기록을 끄고 sanitized event만 남긴다.
- fresh-thread city change는 `modify_missing_current_itinerary` public clarification으로 종료된다.
- 같은 day와 서로 다른 day의 multi-edit 모두 성공한 replacement 전체를 설명 대상으로 보존한다.
- scoped planner copy는 empty, partial, duplicate, unknown target을 완료로 인정하지 않는다.
- invalid scoped copy는 deterministic copy를 유지하고 supervisor 재진입 없이 종료한다.
- canonical `src`와 배포 대상 `app`의 변경 Python 파일 11개는 SHA-256 기준 동일하다.

검증 결과:

- focused regression: `73 passed`
- V2 full regression: `461 passed, 2 subtests passed`
- app mirror compile/import smoke: 통과
- local E2E memory mode: `LOVV_MEMORY_ENABLED=false`, `local_memory_saver`

Local memory-off E2E 측정:

| scenario | elapsed | result |
|---|---:|---|
| fresh-thread city change | 2.098s | `modify_missing_current_itinerary` clarification |
| anchored create | 13.703s | 6 items, LLM copy 적용 |
| same-day two-slot edit | 5.643s | 2/2 적용, 두 항목의 copy/body/reason 확인 |
| cross-day two-slot edit | 21.776s | 2/2 적용, 두 항목의 copy/body/reason 확인 |
| city change | 8.749s | `KR-37-12`, 정상 수정 종료 |

첫 live run에서는 multi-edit의 `planner_copy_generation_used_llm=true`에도
`modification_explanation_completed=false`가 남는 문제가 관측됐다. 원인은 기존 생성 때 이미
LLM copy가 적용된 변경 외 항목까지 완료 판정 집합에 포함한 것이었다. 완료 판정의 `copied_refs`를
현재 `target_item_refs` scope로 제한하고 동일 E2E를 재실행해 두 multi-edit 모두 `completed=true`를 확인했다.

모든 live invocation은 60초 이내였고 planner copy 누락이나 schema retry 지연은 재현되지 않았다.
따라서 사전에 논의한 scoped retry 1회 제한 등의 추가 완화책은 이번 변경에 포함하지 않았다.
