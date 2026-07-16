# LOVV V2 Observability Implementation Tasks

작성일: 2026-07-08
기준 코드: `src/lovv_agent/`, `src/lovv_agent_v2/`

## 1. 목표

V1 `lovv_agent`에 적용된 OpenTelemetry 기반 관측성을 V2 런타임에 맞게 적용한다.

V2는 LangGraph interrupt/resume, multi-turn modify, weather clarification, AgentCoreMemorySaver 비용 리스크가 V1보다 커졌으므로 단순 로그가 아니라 아래 세 가지를 함께 봐야 한다.

- 요청 단위 correlation: `requestId`, `threadId`, `actorId`, `agent_run_id`
- node/tool 단위 성능: supervisor route, city_select, planner, response_packager, AWS tool latency
- 안전/비용 guard: recursion, checkpointer event 폭증, END_WAIT_USER/resume loop

## 2. 현재 적용 상태 점검

### 2.1 V1에 이미 적용된 기준선

V1에는 아래 observability 요소가 있다.

| 영역 | V1 구현 |
|---|---|
| telemetry 초기화 | `lovv_agent.telemetry.init_telemetry()` |
| invocation span | `trace_invocation()`이 `LovvAgentInvocation` span 생성 |
| node span/metric | `trace_node()`, `trace_graph_envelope_node()` |
| node metric stdout | `AGENT_NODE_METRIC` JSON log 출력 |
| trace state | `TraceState.recommendation_request_id`, `agent_run_id`, `node_timings` |
| graph visit 기록 | `trace.node_timings.visited_nodes` |
| LLM usage | `record_llm_usage()`, `metrics_since()` |
| AWS tool spans | Bedrock Converse, S3 Vectors, DynamoDB repository span |
| 안전 처리 | `sanitize_text()`로 error/query 노출 최소화 |

### 2.2 V2에 이미 들어온 부분

V2에도 일부는 포팅되어 있다.

| 영역 | V2 상태 |
|---|---|
| telemetry 모듈 | `lovv_agent_v2.common.telemetry` 존재 |
| LLM usage metrics | `common.telemetry_metrics` 존재 |
| text sanitize | `common.telemetry_safety` 존재 |
| AWS repository spans | `infra.repositories.s3_vectors`, `infra.repositories.dynamodb`에 span 있음 |
| Bedrock Converse span | `infra.adapters.bedrock_converse`에 span 있음 |
| state trace group | `UnifiedAgentState.trace` top-level group 존재 |
| AgentCore request id 추출 | `agentcore_entrypoint.extract_request_id()` 존재 |
| checkpointer local fallback | memory off 시 `MemorySaver` 사용 |

### 2.3 V2 누락/부분 적용

현재 V2에서 중요한 누락은 다음이다.

| 영역 | 현재 문제 |
|---|---|
| invocation wrapper | `LovvLangGraphV2Harness.invoke()`가 `trace_invocation()`으로 감싸지지 않음 |
| node wrapper | `core.graph.compile_v2_graph()`가 `trace_node()`/`trace_graph_envelope_node()`를 적용하지 않음 |
| trace id 주입 | `trace.recommendation_request_id`, `trace.agent_run_id`를 일관되게 채우지 않음 |
| visited_nodes | V2 graph visit 기록이 없음 |
| supervisor route metric | next node, route reason, loop count 관측이 약함 |
| modification lifecycle | `modification_pending`, city_change, slot_replace, day_regenerate 결과 metric 없음 |
| clarification lifecycle | `END_WAIT_USER`, reasonCode, optionId, then, resume 결과 metric 없음 |
| weather alternative | weather risk, alternative 생성/실패/keep_primary 선택 metric 없음 |
| checkpointer cost guard | AgentCoreMemorySaver event 폭증 탐지/경고 metric 없음 |
| runtime tool latency summary | AWS span은 있으나 request-level 요약 metric과 연결이 약함 |

## 3. 적용 원칙

- public request 원문과 사용자 자연어 전체를 그대로 로그에 남기지 않는다.
- node metric에는 길이, count, enum, id 정도만 남긴다.
- `requestId`, `threadId`, `actorId`는 correlation 용도로 남기되 actor 값은 backend에서 pseudonymous id를 넘기는 전제를 유지한다.
- S3 Vector 결과의 전체 후보명/텍스트는 남기지 않고 count, cityIds sample, distance range 정도만 남긴다.
- checkpointer event 수와 graph step count는 별도 guard metric으로 남긴다.
- local live smoke는 memory off + local `MemorySaver`를 기본으로 두어 AgentCore Memory 과금 재발을 막는다.

## 4. 구현 Task

### 4.1 V2 invocation trace 연결

- `src/lovv_agent_v2/harness.py`에서 graph invoke를 `trace_invocation()`으로 감싼다.
- payload에서 `trace`를 제거하지 않고, 없으면 harness/entrypoint에서 최소 trace group을 주입한다.
- `requestId`, `threadId`, `actorId`, `entryType`을 span attribute와 metric summary에 포함한다.

완료 기준:

- V2 harness invoke 시 `LovvAgentInvocation` span이 생성된다.
- stdout metric에서 동일 request id로 node metric을 묶을 수 있다.

### 4.2 V2 graph node trace 연결

- `core.graph.compile_v2_graph()`의 주요 node를 `trace_node()`로 감싼다.
- 대상 node:
  - `intent`
  - `supervisor`
  - `profile`
  - `festival_verifier`
  - `city_select`
  - `planner`
  - `explain_itinerary`
  - `weather_alternative`
  - `response_packager`
- subgraph node는 우선 top-level node span으로 묶고, 필요 시 planner/city_select 내부 step span은 후속으로 분리한다.

완료 기준:

- 각 node별 `AGENT_NODE_METRIC`이 출력된다.
- error 발생 시 span status가 error이고 sanitize된 message만 남는다.

### 4.3 Trace state 보강

- V2 state의 `trace`에 아래 field를 표준화한다.
  - `recommendation_request_id`
  - `agent_run_id`
  - `thread_id`
  - `actor_id`
  - `visited_nodes`
  - `route_count`
- entrypoint가 thread/actor/request id를 추출한 직후 graph state에 반영한다.

완료 기준:

- smoke 결과 state에서 visited node 순서를 확인할 수 있다.
- 같은 thread의 create -> modify -> clarify/resume 흐름을 trace id로 묶을 수 있다.

### 4.4 Supervisor routing 관측

- supervisor decision마다 다음 값을 metric summary에 포함한다.
  - `entryType`
  - `nextNode`
  - `routeReason`
  - `responseStatus`
  - `clarificationReasonCode`
  - `modifyAction`
- route count 또는 recursion step count가 임계치를 넘으면 warning metric을 남긴다.

완료 기준:

- infinite/near-infinite routing 의심 시 어떤 node 사이에서 반복됐는지 로그만으로 알 수 있다.

### 4.5 Modify/clarification lifecycle 관측

- 수정 flow에서 아래 이벤트를 남긴다.
  - city_change rediscovery start/end
  - slot_replace start/end/failure
  - day_regenerate start/end/failure
  - reserve_pool 사용 여부
  - 추가 retrieval 여부
  - changed slot count, failed slot count
- clarification flow에서 아래 이벤트를 남긴다.
  - reasonCode
  - option count
  - selected optionId
  - then
  - action 적용 결과

완료 기준:

- 한 번의 수정 요청이 city_select 재탐색인지, planner edit인지, response-only인지 로그로 구분된다.

### 4.6 Weather alternative 관측

- weather risk 계산 결과를 metric으로 남긴다.
  - weather map hit/miss
  - risk level
  - primary sensitive item count
  - alternative item count
  - indoor/mixed/outdoor count
  - route feasibility success/failure
- 사용자가 `keep_primary_itinerary` 또는 weather alternative를 선택했는지 resume metric에 남긴다.

완료 기준:

- weather clarification이 왜 발생했는지와 대체 일정 생성이 왜 실패했는지 로그로 설명 가능하다.

### 4.7 AWS tool latency summary

- 이미 있는 repository/adapter span을 유지한다.
- request-level metric에는 각 tool 호출 count와 aggregate latency를 요약한다.
  - S3Vectors query count
  - DynamoDB Get/BatchGet/Query count
  - Bedrock embedding/converse count
  - ORS route matrix/route request count
- 고비용/고지연 후보:
  - planner raw/soft 병렬 retrieval
  - route_days ORS 계산
  - explain itinerary LLM copy generation
  - AgentCore Memory checkpointer

완료 기준:

- “City select가 느린지, planner routing이 느린지, LLM copy가 느린지”를 한 요청 로그에서 구분할 수 있다.

### 4.8 Checkpointer 비용 guard

- memory mode를 metric에 남긴다.
  - `local_memory_saver`
  - `agentcore_memory_saver`
- AgentCore Memory enabled일 때는 아래 값을 경고 기준으로 삼는다.
  - graph step count
  - interrupt/resume count
  - repeated node pair count
  - same thread rapid retry count
- local smoke script는 기본 memory off를 유지하고, AgentCore Memory 사용 시 명시 flag를 요구한다.

완료 기준:

- 과거처럼 local live smoke가 AgentCore Memory event를 대량 발생시키는 상황을 기본값으로 재현할 수 없다.

## 5. 테스트/검증 Task

- telemetry wrapper 단위 테스트:
  - success metric 출력
  - error metric 출력
  - sanitize 적용
- V2 harness 테스트:
  - trace group이 없는 payload에 request id/run id가 생김
  - Command resume에서도 correlation id가 보존됨
- graph routing 테스트:
  - visited node 또는 node metric에 supervisor loop가 기록됨
- AgentCore entrypoint 테스트:
  - `threadId`, `actorId`, `requestId`가 trace에 반영됨
- smoke 검증:
  - create 1건
  - modify city_change 1건
  - slot_replace 1건
  - festival clarification 1건
  - weather clarification 1건

## 6. 우선순위

1. `trace_invocation` + node wrapper 적용
2. trace id/thread/actor/run id 주입
3. supervisor route/loop metric
4. clarification/modify lifecycle metric
5. checkpointer cost guard
6. AWS tool latency summary
7. weather alternative 상세 metric

## 7. 진행 기록

### 2026-07-08 1차 적용

적용 완료:

- `LovvLangGraphV2Harness.invoke()` dict payload 경로를 `trace_invocation()`으로 감쌌다.
- `core.graph` top-level node에 `trace_node()`를 적용했다.
- `city_select`, `planner` subgraph는 얇은 callable adapter로 감싸 top-level node metric이 남도록 했다.
- `response_packager` interrupt는 error가 아니라 `status=interrupt` node metric으로 기록하도록 분리했다.

검증:

- `tests/v2/test_harness.py`
- `tests/v2/test_graph_routing.py`
- `tests/v2/test_response_packager_node.py`
- `tests/v2/test_festival_node.py`

남은 작업:

- trace id/thread/actor/run id를 state trace group에 표준 주입.
- supervisor route reason/loop count metric.
- modify/clarification/weather/checkpointer 비용 guard 상세 metric.

### 2026-07-08 2차 적용

적용 완료:

- `agentcore_entrypoint`와 `harness`가 `trace.recommendation_request_id`, `thread_id`, `actor_id`, `agent_run_id`를 graph state에 주입하도록 했다.
- `LovvAgentInvocation` 단위 `AGENT_INVOCATION_METRIC`을 추가해 요청 전체 `durationMs`, status, response summary, trace summary를 남기도록 했다.
- node metric helper와 invocation metric helper를 분리해 V2 telemetry 파일의 책임을 나눴다.
- `Command(resume=...)` payload는 checkpoint resume 의미를 유지하고, dict payload만 invocation trace wrapper로 감싸도록 했다.

검증:

- `tests/v2/test_harness.py`
- `tests/v2/test_entrypoint.py`
- `tests/v2/test_graph_routing.py`
- `tests/v2/test_response_packager_node.py`
- `tests/v2/test_festival_node.py`

남은 작업:

- supervisor route reason/loop count metric.
- modify/clarification/weather lifecycle metric.
- planner/city_select 내부 step별 duration.
- request-level AWS tool latency aggregate.
- AgentCoreMemorySaver event 폭증 guard metric.
- live smoke 결과 JSON에 metric 자동 수집.

### 2026-07-08 3차 적용

적용 완료:

- supervisor node metric의 `outputSummary`에 routing 결과를 남긴다.
- 추가 필드:
  - `routeNextNode`
  - `routeNeedsClarification`
  - `routeClarificationReasonCode`
  - `routeCompletedGroupCount`

검증:

- `tests/v2/test_graph_routing.py::test_graph_emits_top_level_node_metrics`

이번 단계에서 아직 하지 않는 것:

- route reason taxonomy 정교화.
- repeated node pair / route loop warning.
- modify/weather lifecycle 전용 metric.

### 2026-07-08 4차 적용

적용 범위:

- planner/city_select 내부 subgraph step도 `AGENT_NODE_METRIC`과 invocation `stepMetrics`에 포함한다.
  - `city_select.retrieval`
  - `city_select.scoring_and_selection`
  - `planner.retrieve_places`
  - `planner.apply_edit`
  - `planner.route_days`
  - `planner.assemble_itinerary`
  - `planner.retry_alternative_city`
  - `planner.weather_alternative`
- invocation 단위 `toolMetrics`에 AWS tool latency aggregate를 포함한다.
  - `s3vectors.QueryVectors`
  - `dynamodb.GetItem`
  - `dynamodb.BatchGetItem`
  - `dynamodb.Query`
  - `dynamodb.Scan`
  - `bedrock.InvokeModel`
  - `bedrock.Converse`
- checkpointer 생성 시 `AGENT_MEMORY_GUARD`를 출력한다.
  - memory off: `memoryMode=local_memory_saver`
  - AgentCore Memory on: `memoryMode=agentcore_memory_saver`

검증 목표:

- 한 요청 로그에서 planner/city_select 내부 어느 단계가 느린지 구분한다.
- S3 Vector, DynamoDB, Bedrock 호출 횟수와 합산/평균/최대 지연을 확인한다.
- local smoke가 AgentCore Memory를 쓰는지 여부를 실행 시작 시점에 바로 확인한다.

이번 단계에서 아직 하지 않는 것:

- ORS latency aggregate는 route feasibility 전용 metric과 함께 별도 정리한다.
- AgentCore Memory 실제 event count 조회는 AWS runtime/CloudWatch 연동 확인 후 붙인다.
- repeated node pair / same thread rapid retry guard는 route loop metric에서 후속 구현한다.

### 2026-07-08 5차 적용

적용 범위:

- `trace.visited_nodes`와 `trace.route_pair_counts`를 node wrapper에서 누적한다.
- 동일 node pair가 3회 이상 반복되면 node metric `outputSummary`에 route loop guard를 남긴다.
  - `routeLoopReason=repeated_node_pair`
  - `routeRepeatedPair`
  - `routeRepeatedPairCount`
- AgentCore Memory가 켜진 live runtime에서는 invocation 종료 시 `ListEvents` 1페이지를 확인한다.
  - 조회 조건: `memoryId`, `threadId(sessionId)`, `actorId`
  - payload는 포함하지 않음: `includePayloads=false`
  - 페이지 크기: 100
- event page에 `nextToken`이 있으면 비용 위험 신호로 `AGENT_MEMORY_GUARD` WARN을 남긴다.
  - `eventGuard=agentcore_memory_event_page_has_more`
  - `eventPageCount`
  - `hasMoreEvents`

검증:

- `tests/v2/test_graph_routing.py::test_route_loop_guard_warns_on_repeated_node_pair`
- `tests/v2/test_invocation_metric_aggregates.py::test_harness_emits_agentcore_memory_event_guard`

이번 단계에서 아직 하지 않는 것:

- `ListEvents` 전체 pagination은 기본 수행하지 않는다. guard 자체가 추가 비용을 크게 만들 수 있으므로 1페이지 샘플링만 한다.
- same thread rapid retry guard는 CloudWatch/runtime access log와 함께 후속 설계한다.
- actual AgentCore live smoke에서 guard 로그가 CloudWatch에 보이는지 확인하는 작업은 배포 환경에서 수행한다.

### 2026-07-08 6차 적용

적용 범위:

- `AGENT_LIFECYCLE_METRIC`을 추가해 request 전체 metric과 별도로 사용자 흐름 상태를 남긴다.
  - `lifecycleType=modify`: slot/day edit 적용, 부분 적용, 실패 건수.
  - `lifecycleType=clarification`: interrupt 직전 reason code, option count, then 값.
  - `lifecycleType=weather`: weather audit status, evaluation stage, notice level, 판단 불가 사유.
- ORS 외부 호출 latency를 invocation `toolMetrics`에 포함한다.
  - `ors.SnapPlaces`
  - `ors.GetMatrix`

검증:

- `tests/v2/test_ors_provider_fallback.py`
- `tests/v2/test_planner_apply_edit.py`
- `tests/v2/test_weather_alternative.py`
- `tests/v2/test_response_packager_node.py::test_response_packager_node_clarifies_weather_alternative_available`

이번 단계에서 아직 하지 않는 것:

- lifecycle metric을 CloudWatch dashboard/metric filter로 승격하는 작업.
- weather alternative resume 이후의 대체 일정 품질 metric 세분화.
- ORS cache hit/miss 구분 metric.

### 2026-07-08 live E2E 검증

검증 위치:

- `docs/tasks/results/v2_observability_live_e2e/20260708T160734Z/`

검증 케이스:

- `weather-create-v2`: 동해 바다·해안 7월 생성, weather clarification 발생.
- `modify-slot-v2`: 기존 동해 일정의 slot replace 수정.
- `weather-resume-chain-v3`: 같은 프로세스에서 weather clarification 응답까지 resume.

관측 결과:

- `AGENT_MEMORY_GUARD`: local memory saver, AgentCore Memory disabled 확인.
- `AGENT_NODE_METRIC`: intent, planner 내부 step, explain, response packager 기록 확인.
- `AGENT_LIFECYCLE_METRIC`: modify applied, weather evaluated, clarification waiting 확인.
- `AGENT_INVOCATION_METRIC`: create, modify, clarify resume request-level metric 확인.
- `toolMetrics` aggregate 확인:
  - `bedrock.Converse`
  - `bedrock.InvokeModel`
  - `dynamodb.BatchGetItem`
  - `s3vectors.QueryVectors`
  - `ors.SnapPlaces`
  - `ors.GetMatrix`

검증 중 발견 및 수정:

- planner/city_select 병렬 검색의 worker thread에서 기록한 tool metric이 invocation aggregate로 돌아오지 않았다.
- `contextvars.copy_context()`와 공유 tool metric buffer를 적용해 parent invocation의 `toolMetrics`에 합산되도록 수정했다.
- `Command(resume=...)` 경로도 request-level `AGENT_INVOCATION_METRIC`으로 감싸도록 수정했다.
- LangGraph resume replay로 동일 clarification lifecycle이 중복 출력되던 문제를 request/reason 기준 idempotent guard로 줄였다.

## 8. 구현 전 주의

- `app/LovvAgentV2/`는 deploy mirror이므로 `src/lovv_agent_v2/`에서 검증한 뒤 배포 직전 복사한다.
- telemetry 때문에 state에 non-serializable runtime 객체를 넣지 않는다.
- checkpointer에 저장되는 state에는 runtime dependency가 들어가지 않아야 한다.
- 문서/metric field 이름은 public response contract와 분리한다. Observability field는 운영 진단용이다.
