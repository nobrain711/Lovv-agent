# LOVV V2 AgentCore Memory Troubleshooting

작성일: 2026-07-08

## 1. 사건 요약

AgentCore Memory `Short-Term-Memory` 사용량이 2026-07-03부터 2026-07-05까지 비정상적으로 증가했다.

확인된 Cost Explorer 사용량:

| 날짜 | Usage type | Operation | Events |
| --- | --- | --- | ---: |
| 2026-07-03 | `USE1-Memory:Consumption-based:Short-Term-Memory` | `CREATE_EVENT` | 265,444 |
| 2026-07-04 | `USE1-Memory:Consumption-based:Short-Term-Memory` | `CREATE_EVENT` | 170,442 |
| 2026-07-05 | `USE1-Memory:Consumption-based:Short-Term-Memory` | `CREATE_EVENT` | 217,149 |

합계: 653,109 events.

동기간 AgentCore Runtime compute 사용량은 작았고, CloudWatch runtime log도 많지 않았다. 따라서 외부 API 요청 자체가 수십만 번 발생한 것이 아니라, 특정 요청/세션 내부에서 AgentCore Memory write가 과도하게 반복된 것으로 판단한다.

## 2. 확인된 원인

### 2-1. AgentCoreMemorySaver 저장 모델

현재 V2 live harness는 `LOVV_MEMORY_ENABLED=true`일 때 LangGraph graph를 `AgentCoreMemorySaver` checkpointer로 compile한다.

관련 경로:

- `src/lovv_agent_v2/harness.py`
- `src/lovv_agent_v2/infra/memory/checkpointer.py`

설치된 `langgraph-checkpoint-aws` 구현 확인 결과, `AgentCoreMemorySaver`는 checkpoint 저장 시 단일 state row를 덮어쓰지 않는다. 대신 AgentCore Memory `create_event`를 사용해 다음 항목을 이벤트로 저장한다.

- checkpoint body
- channel data
- pending writes
- graph step별 intermediate writes

따라서 정상 요청 1회도 여러 개의 Memory event를 만든다.

### 2-2. 수정 루프/무한 루프와 결합된 비용 폭발

일반적인 생성/단일 수정 세션은 수십 event 수준이었다.

확인 샘플:

| Session | Events |
| --- | ---: |
| `v2-smoke-v2_gen_04_history_2d1n` | 46 |
| `v2-live-regression-0705-gen07-a` | 42 |
| `v2-live-slot-replace-fail-0705` | 46 |

반면 특정 slot replace live 세션은 매우 큰 event 수를 만들었다.

| Session | Events |
| --- | ---: |
| `slot-replace-live-20260704-01` | 20,080 |

이 차이는 단순 checkpointer 기본 비용만으로 설명하기 어렵다. 당시 일정 수정 구현 중 supervisor routing 또는 modify loop가 종료되지 않는 문제가 있었고, 그 루프가 도는 동안 매 graph step마다 AgentCore Memory checkpoint write가 발생한 것으로 판단한다.

즉 실제 폭증 원인은 다음 조합이다.

1. `AgentCoreMemorySaver`가 LangGraph step/channel/write 단위로 Memory event를 생성한다.
2. 일정 수정 flow에서 무한 루프 또는 과도한 반복 routing이 발생했다.
3. local live smoke와 AgentCore runtime 모두 같은 AgentCore Memory resource를 사용했다.
4. loop 중 매 step이 checkpoint write를 만들면서 단일 세션이 수만 event까지 증가했다.

## 3. 로컬 smoke 영향

2026-07-03부터 2026-07-05 사이 생성된 로컬 결과 파일 기준:

| 위치 | 파일 수 |
| --- | ---: |
| `docs/tasks/results/v2_generation_planner_smoke` | 148 |
| `docs/tasks/results/v2_general_live_smoke` | 105 |

특히 `scripts/v2/run_general_live_smoke.py`와 `scripts/v2/run_generation_to_planner_smoke.py`는 live harness를 사용한다. `.env.v2.local`에 `LOVV_MEMORY_ENABLED=true`가 설정되어 있으면 로컬 테스트도 AgentCore Memory에 직접 checkpoint를 쓴다.

## 4. 즉시 차단 조치

현재 비용 재발 방지를 위해 다음 값을 `false`로 내려야 한다.

```text
LOVV_MEMORY_ENABLED=false
```

확인된 차단 대상:

- `.env.v2.local`
- `agentcore/agentcore.json`

주의: `LOVV_MEMORY_ID`가 남아 있어도 `LOVV_MEMORY_ENABLED=false`이면 checkpointer는 생성되지 않는다.

## 5. 운영 원칙

### 5-1. AgentCoreMemorySaver는 기본 사용 금지

`AgentCoreMemorySaver`를 full LangGraph checkpointer로 다시 켜면 동일한 비용 폭발이 재발할 수 있다.

특히 다음 환경에서는 사용하지 않는다.

- local smoke
- batch smoke
- generation matrix
- route/planner regression live test
- 반복 수정 live test

### 5-2. 일정 수정/clarification은 상태 저장이 필요하다

일정 수정과 clarification resume을 지원하려면 상태 저장은 필요하다. 다만 full graph state를 AgentCore Memory에 그대로 저장하는 방식은 현재 비용 위험이 크다.

권장 방향:

1. 기본은 stateless 또는 memory off.
2. 수정/clarification 상태는 compact state로 별도 저장.
3. 필요한 값만 저장한다.

compact state 후보:

- `thread_id`
- `actor_id`
- `last_trip_intent`
- `selected_city`
- `current_order`
- `reserve_pool` 최소 형태
- `pending_clarification`
- `excluded_city_ids`
- `replaced_content_ids`

### 5-3. DynamoDBSaver 검토

`AgentCoreMemorySaver` 대신 `DynamoDBSaver`를 사용하면 AgentCore Memory `CREATE_EVENT` 과금 폭발을 피할 수 있다.

확인된 차이:

- `AgentCoreMemorySaver`: AgentCore Memory event 기반 저장
- `DynamoDBSaver`: DynamoDB item 기반 저장, 큰 payload는 S3 offload 가능

권장 구성:

- 별도 checkpoint table 사용
- 예: `LovvAgentV2Checkpoints`
- on-demand billing
- TTL 1~7일
- S3 offload와 compression 검토

단, DynamoDBSaver도 full graph state를 계속 저장하면 storage/latency 비용이 커질 수 있으므로 compact state 설계와 함께 검토한다.

## 6. 재발 방지 작업

우선순위 높은 조치:

1. `LOVV_MEMORY_ENABLED=true` 상태에서 local smoke 실행 금지.
2. live smoke runner 시작 시 memory enabled이면 명시적으로 fail 또는 강한 경고.
3. graph recursion limit을 낮게 명시.
4. supervisor route loop guard 추가.
5. 동일 `routing.next_node` 반복 횟수 제한.
6. 수정 flow에서 terminal response 또는 planner 재진입 조건을 명확히 검증.
7. checkpointer backend를 `off | dynamodb | agentcore_memory`로 분리.
8. AgentCore Memory backend는 실험용 또는 제한된 resume test 전용으로만 허용.

## 7. 결론

이번 비용 폭증은 단순히 테스트 수가 많아서 발생한 문제가 아니다.

핵심 원인은 다음이다.

```text
modify flow 반복/무한 루프
+ AgentCoreMemorySaver full graph checkpoint
+ local/live smoke 반복 실행
= AgentCore Memory CREATE_EVENT 폭증
```

따라서 일정 수정/clarification을 위해 상태 저장은 계속 필요하지만, AgentCoreMemorySaver를 full LangGraph checkpointer로 그대로 사용하는 방식은 폐기하거나 매우 제한적으로만 사용해야 한다.
