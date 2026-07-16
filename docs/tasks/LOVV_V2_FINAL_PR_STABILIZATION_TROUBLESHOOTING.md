# LOVV V2 Final PR Stabilization Troubleshooting

작성일: 2026-07-15
관련 task: `docs/tasks/LOVV_V2_FINAL_PR_STABILIZATION_TASKS.md`
범위: telemetry 예외 redaction, fresh-thread modify, multi-edit 설명 범위, planner copy 완료 판정

## 1. Invocation span에 원문 예외가 중복 기록됨

### 증상

- 수동으로 sanitized exception event를 기록했는데도 실제 OpenTelemetry SDK span에 exception event가 하나 더 생겼다.
- 자동 event와 span status description에는 원문 secret, email, stacktrace가 남을 수 있었다.

### 원인

`start_as_current_span()` context manager가 예외 종료 시 기본값으로 다음 동작을 수행했다.

- `record_exception=True`
- `set_status_on_exception=True`

따라서 내부 `_record_span_error()`의 sanitized 기록과 SDK 자동 기록이 동시에 실행됐다.

### 해결

`LovvAgentInvocation` span 생성 시 두 옵션을 명시적으로 `False`로 설정했다. 예외 event와 status는
기존 sanitize helper만 기록하도록 단일화했다. `GraphInterrupt`는 error로 기록하지 않는다.

### 검증

- fake tracer가 아니라 실제 `TracerProvider`와 in-memory exporter로 완성된 span을 검사했다.
- sanitized exception event 1개만 존재하고 원문 secret과 email이 event, stacktrace, status description에
  남지 않는 것을 확인했다.

### 재발 방지

- span 내부에서 예외를 직접 처리할 때는 context manager의 자동 예외 기록 여부를 함께 검사한다.
- JSON log만 redaction됐다는 이유로 span도 안전하다고 판단하지 않는다.

## 2. Checkpoint가 없는 city change가 planner까지 진행됨

### 증상

새 thread에서 `도시는 경주로 바꿔줘.`를 보내면 city change rule parser는 성공했지만, 재사용할
기존 trip intent가 없었다. 이후 supervisor가 profile/planner로 진행하면서
`SchemaValidationError: missing required field: country`로 종료됐다.

### 원인

- city change는 slot edit과 달리 `currentOrder` 없이도 실행할 수 있도록 설계되어 있었다.
- 하지만 “기존 일정의 `city_select_input`이 실제로 복원 가능한가”라는 공통 invariant가 parser 결과와
  LLM fallback 결과 뒤에 없었다.
- 문장 파싱 성공을 실행 가능한 수정 context 존재로 잘못 간주했다.

### 해결

- city change 문장 파싱은 기존처럼 `currentOrder` 검사보다 먼저 수행한다.
- rule parser와 LLM fallback 이후 공통으로 `trip_intent_from_intent()`를 검사한다.
- 재사용 가능한 trip intent가 없으면 `modify_missing_current_itinerary` public clarification으로 종료한다.
- persisted trip intent가 있으면 `currentOrder`가 없어도 기존 reanchor 경로를 유지한다.

### 검증

- fresh-thread live E2E: 2.098초, `END_WAIT_USER`, `modify_missing_current_itinerary`.
- 기존 생성 checkpoint가 있는 city change는 정상적으로 `KR-37-12`를 선택하고 수정 완료했다.
- rule parser와 LLM fallback 양쪽에 회귀 테스트를 추가했다.

## 3. Multi-edit에서 마지막 변경 장소만 설명 대상으로 남음

### 증상

두 slot 교체가 모두 성공해 `applied_edits`에는 두 replacement가 존재했지만,
`explanation_item_place_ids`에는 마지막 replacement 하나만 남았다.

### 원인

각 operation이 planner output 전체를 다시 만들면서 `_planner_output()`에 현재 `applied_edit` 하나만
전달했다. sequential fold의 누적 결과를 설명 scope 생성에 사용하지 않았다.

### 해결

- 현재 invocation의 `applied_edits[]` 전체로 explanation place IDs를 만든다.
- 적용 순서를 유지하고 place ID를 중복 제거한다.
- 부분 성공에서는 성공한 replacement만 포함한다.
- `apply_edit_node` 진입 시 transient edit 결과를 초기화해 이전 request history가 현재 batch에 섞이지 않게 했다.

### 검증

- 같은 day 두 slot: 2/2 replacement와 LLM copy 확인.
- 서로 다른 day 두 slot: 2/2 replacement와 LLM copy 확인.
- 부분 성공, 이전 request history, day regenerate 경로를 회귀 테스트로 확인했다.

## 4. Empty 또는 partial LLM copy를 완료로 기록함

### 증상

변경 항목 설명 scope가 있는데도 LLM이 `item_copies=[]` 또는 일부 target만 반환하면 deterministic copy가
남았다. 그런데도 `planner_copy_generation_used_llm=true`와
`modification_explanation_completed=true`가 기록될 수 있었다.

### 원인

- scoped target에 대한 exact coverage 검사가 없었다.
- 설명 완료 marker를 실제 copy 적용 결과가 아니라 설명 node 실행 여부에 가깝게 기록했다.

### 해결

- 수정, day regenerate, weather alternative처럼 explicit scope가 있을 때만 exact target coverage를 강제한다.
- empty, partial, duplicate, unknown target output은 schema failure로 처리한다.
- 실제 적용된 item ref 전체가 expected ref와 일치하고 각 항목이 `llm_planner_copy`일 때만 완료로 기록한다.
- 실패 시 deterministic copy를 유지하고 `attempted=true`, `completed=false`, `used_llm=false`로 종료한다.
- supervisor는 attempted fallback을 다시 explain node로 보내지 않는다.

### 검증

- exact coverage unit test와 invalid scoped copy graph E2E를 통과했다.
- invalid fixture는 LLM request 1회 후 deterministic fallback으로 종료되며 route loop가 없다.
- 일반 생성의 기존 partial copy 계약은 유지했다.

## 5. Live에서 `used_llm=true`, `completed=false`가 추가 발견됨

### 증상

첫 memory-off live E2E에서 두 multi-edit 모두 다음 상태가 관측됐다.

- `planner_copy_generation_used_llm=true`
- 변경 대상 2개 모두 LLM copy 적용
- `modification_explanation_completed=false`

### 원인

완료 판정용 `copied_refs`가 전체 itinerary에서 `copy_source=llm_planner_copy`인 항목을 수집했다.
초회 생성에서 이미 LLM copy가 적용된 변경되지 않은 항목까지 포함되어 expected target set보다 커졌다.

즉 LLM 누락이나 재시도 문제가 아니라 완료 판정 scope 오류였다.

### 해결

`copied_refs`를 현재 `target_item_refs`에 포함된 항목으로만 제한했다.

### 검증

| scenario | elapsed | explanation result |
|---|---:|---|
| same-day two-slot edit | 5.643s | 2/2 `llm_planner_copy`, body/reason 확인, completed |
| cross-day two-slot edit | 21.776s | 2/2 `llm_planner_copy`, body/reason 확인, completed |

모든 호출이 60초 안에 끝났고 schema retry 지연이나 target 누락은 재현되지 않았다. 따라서 사전에 검토한
“scoped retry 1회 제한”은 추가하지 않았다.

## 6. Memory-off live 검증 시 주의사항

### 위험

`.env.v2.local`을 읽은 뒤 `LOVV_MEMORY_ENABLED=false`를 설정하지 않거나, harness import 후 환경변수만
바꾸면 이미 만들어진 AgentCoreMemorySaver가 계속 사용될 수 있다.

### 적용한 검증 절차

1. dotenv 값을 먼저 읽는다.
2. `LOVV_MEMORY_ENABLED=false`로 다시 덮어쓴다.
3. 그 이후 entrypoint와 harness를 import한다.
4. `harness.config.memory.enabled is False`를 확인한다.
5. graph checkpointer가 local `MemorySaver`인지 확인한다.
6. 조건이 다르면 live test를 즉시 실패시킨다.

최종 E2E 로그에서 `memoryMode=local_memory_saver`, `memory_enabled=false`를 확인했다.

## 7. 최종 검증 결과

- focused regression: `73 passed`
- V2 full regression: `461 passed, 2 subtests passed`
- app mirror compile/import smoke: 통과
- canonical `src`와 deploy `app` 변경 파일 11개: SHA-256 동일
- `git diff --check`: 오류 없음

## 8. 추가 진행 사항 점검

### 8.1 현재 안정화 범위의 추가 코드 blocker

없음. 네 merge blocker와 live에서 발견한 완료 판정 오류는 모두 회귀 테스트와 E2E로 닫혔다.

### 8.2 배포 전 필수 운영 확인

1. 배포 runtime에서 create 1건, city change 1건, multi-edit 1건을 같은 application thread로 실행한다.
2. synthetic error 1건으로 AgentCore trace에 원문 secret이 노출되지 않는지 확인한다.
3. 배포 환경의 memory backend와 recursion/route guard 설정을 확인한다.
4. 60초 timeout과 `AGENT_INVOCATION_METRIC`의 route/tool latency를 확인한다.

이는 로컬 코드 blocker가 아니라 실제 exporter, runtime identity, checkpointer 설정을 확인하는 운영 gate다.

### 8.3 별도 후속 보안 작업

이번 수정은 invocation span의 자동 원문 예외 기록을 차단했다. 그러나 다음 AWS tool span에는 기존
`span.record_exception(exc)` 직접 호출이 남아 있다.

- `infra/repositories/s3_vectors.py`
- `infra/repositories/dynamodb.py`
- `infra/adapters/bedrock_converse.py`

status description은 sanitize하지만 exception event의 message와 stacktrace는 원문일 수 있다. 동일한
sanitized exception helper로 통일하고 실제 SDK exporter 테스트를 추가하는 작업을 별도 P1으로 권장한다.

### 8.4 의도적으로 분리한 아키텍처 작업

- 인증된 actor identity와 caller-controlled session/thread namespace 분리
- AgentCoreMemorySaver 대체 또는 compact checkpoint backend
- AgentCore custom endpoint와 자동 rollback

이번 안정화 PR의 동작 계약을 흔들 수 있어 별도 설계와 migration test가 필요하다.

### 8.5 관측 후 적용할 선택적 개선

- scoped planner copy schema failure율 또는 60초 초과가 실제 관측될 때만 retry limit 조정
- 반복적인 partial output이 확인될 때 changed-item 전용 prompt 축소
- `modify_parser.py`, `result.py`, `planner_copy_composer.py`는 248~250 pure LOC이므로 다음 기능 추가 전 분리 검토

현재 live 결과만으로는 retry 정책을 추가할 근거가 없다.
