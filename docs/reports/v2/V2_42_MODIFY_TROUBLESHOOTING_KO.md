# V2_42 — 일정 수정 트러블슈팅 기록

작성일: 2026-07-03

상태: live smoke 기반 트러블슈팅 한글판

관련 문서:

- `V2_34_MODIFY_INTENT_SCHEMA.md`
- `V2_38_INTENT_FRONTEND_INPUT_CONTRACT.md`
- `V2_39_INTENT_PROCESSING_OUTPUT_SCHEMA.md`
- `V2_41_ROUTE_DAYS_SMOKE_CASEBOOK.md`

---

## 0. 목적

이 문서는 V2 일정 수정 경로를 live smoke로 검증하면서 발견한 문제, 원인, 수정 방향을 한글로 정리한다.

범위:

- 도시 변경 수정 요청의 timeout 원인
- supervisor routing loop 수정
- live smoke 재검증 결과
- 장소 교체 수정 설계 메모
- 복합 수정 요청에 대한 intent 차단 필요성

---

## 1. 도시 변경 live smoke timeout

### 시나리오

새 AgentCore checkpoint session에서 다음 순서로 실행했다.

1. 일반 탐색 생성
   - `destinationId` 없음
   - query: `조용한 바다 산책과 해안 풍경 위주로 2박 3일 일정`
   - theme: `바다·해안`
   - festival: false
2. 같은 session에서 수정 요청
   - `rawModifyQuery`: `도시는 강릉으로 바꿔줘.`

초기 실행은 150초 timeout에 걸렸다.

### 관측

flush log를 남기는 live stream으로 재실행했을 때, 첫 번째 timeout은 네트워크 지연이 아니라 graph routing loop였다.

초기 loop:

```text
intent
-> supervisor
-> planner
-> supervisor
-> planner
-> supervisor
-> ...
```

원인:

- `intent.modify_intent.routing_hint = planner_direct_anchor`
- supervisor가 city-change direct-anchor modify를 planner로 보내는 조건에서 `planner.planner_output` 존재 여부를 보지 않았다.
- 따라서 planner가 이미 완료되어도 stale response보다 먼저 planner route가 다시 선택됐다.

1차 수정 후에는 planner loop는 사라졌지만, 다음 loop가 드러났다.

```text
planner
-> supervisor
-> explain_itinerary
-> supervisor
-> response_packager
-> supervisor
-> response_packager
-> supervisor
-> ...
```

원인:

- 도시 변경 수정 중에는 기존 `response.response_payload`를 stale response로 무시해야 한다.
- 하지만 response packager가 새 response를 만든 뒤에도 supervisor가 "현재 수정 요청에 대한 새 response"와 "이전 create response"를 구분하지 못했다.
- 그 결과 response packager 이후에도 다시 response packager로 라우팅했다.

---

## 2. 수정 내용

수정 파일:

- `src/lovv_agent_v2/agents/supervisor/router.py`

수정 원칙:

1. city-change direct-anchor route는 planner output이 없을 때만 planner로 보낸다.
2. planner output이 생긴 뒤 stale response가 있으면 무시하고 `explain_itinerary`로 보낸다.
3. response packager가 target city에 대한 새 response를 만들면 graph를 종료한다.

현재 종료 판정:

- `modify_intent.city_change.target_city_id == response.response_payload.destination.destinationId`, 또는
- `modify_intent.city_change.target_city_name == response.response_payload.destination.name`

초기에는 live smoke에서 `destination.name = 강릉시`는 들어오지만 `destinationId = null`인 케이스가 있었기 때문에 name fallback을 두었다.

주의:

- `destinationId = null`은 사용자 응답 품질상 별도 개선 대상이다.
- response packager가 planner output의 city id를 destination id로 보강하면 name fallback 의존도를 줄일 수 있다.

---

## 3. 검증

관련 테스트:

```text
tests/v2/test_supervisor_graph.py::test_supervisor_routes_city_change_modify_to_planner_before_stale_response
tests/v2/test_supervisor_graph.py::test_supervisor_routes_city_change_planner_output_to_explain_before_stale_response
tests/v2/test_supervisor_graph.py::test_supervisor_ends_after_city_change_response_payload
tests/v2/test_modify_city_change_reanchor.py
tests/v2/test_planner_direct_anchor.py::test_retrieve_places_node_treats_empty_city_select_as_direct_anchor
tests/v2/test_intent_dispatch_contract.py::test_intent_node_builds_city_change_modify_intent
```

결과:

```text
6 passed
```

최종 live trace:

```text
session: city-change-general-final-20260703132501

create_done:
  response_status: modification_pending
  raw_query: 조용한 바다 산책과 해안 풍경 위주로 2박 3일 일정

modify:
  intent.destination_id: KR-51-150
  trip_intent.destination_id: KR-51-150
  raw_query: 조용한 바다 산책과 해안 풍경 위주로 2박 3일 일정

route:
  intent
  -> supervisor
  -> planner
  -> supervisor
  -> explain_itinerary
  -> supervisor
  -> response_packager
  -> supervisor
  -> end

elapsed: 11.62s
response:
  response_status: modification_pending
  destination.name: 강릉시
```

### 3.1 2026-07-04 재현: 기존 destinationId가 남는 도시 변경 loop

별도 slot replace 검증 중 다음 순서로 다시 재현했다.

```text
session: v2-live-city-then-slot-0704-03

1. create
   input: v2_gen_07_nature_coast_3d2n_live_payload.json
   result: 동해시 / KR-51-170 / 3일 10개

2. modify city-change
   rawModifyQuery: 도시는 강릉으로 바꿔줘.
   request.destinationId: KR-51-170
   intent.city_select_input.destination_id: KR-51-150
```

처음에는 `response_packager` 이후 다음 loop가 발생했다.

```text
response_packager
-> supervisor
-> response_packager
-> supervisor
-> ...
```

원인:

- front modify payload의 `destinationId`는 "수정 전 현재 도시"를 가리킨다.
- city-change intent가 만든 `intent.city_select_input.destination_id`는 "수정 후 목표 도시"를 가리킨다.
- response packager가 request의 기존 `destinationId`를 우선해 응답 destination을 `KR-51-170`으로 만들었다.
- supervisor는 `modify_intent.city_change.target_city_id = KR-51-150`와 응답 destination이 다르다고 보고 현재 modify response로 인정하지 못했다.

수정:

- city-change modify에 한해서 response packager가 `intent.city_select_input.destination_id`를 destination 기준으로 우선 사용한다.
- slot-replace modify는 기존처럼 request/currentOrder의 destination을 우선한다.

검증:

```text
tests:
  tests/v2/test_response_packager_destination.py
  tests/v2/test_supervisor_graph.py
  tests/v2/test_modify_city_change_reanchor.py
  tests/v2/test_planner_apply_edit_multi.py

result:
  30 passed

live:
  create:       16.966s / 동해시 / KR-51-170 / 10 items
  city-change: 30.210s / 강릉시 / KR-51-150 / 10 items
  slot-replace after city-change:
    10.522s / 강릉시 유지
    Day 1 slot 2: 소돌아들바위공원 -> 칠성산
```

### 3.2 복합 raw query: 도시 변경 + 장소 교체

다음처럼 한 문장에 도시 변경과 장소 변경이 함께 들어오는 경우도 확인했다.

```text
rawModifyQuery:
  도시는 강릉으로 바꾸고 1일차 두 번째 장소도 바꿔줘.

payload:
  v2_mod_live_mixed_city_change_slot_replace_gen07.json
```

현재 rule parser 결과:

```json
{
  "status": "ok",
  "kind": "city_change",
  "edit_ops": [],
  "routing_hint": "planner_direct_anchor",
  "city_change": {
    "target_city_id": "KR-51-150",
    "target_city_name": "강릉시"
  }
}
```

live 결과:

```text
session: v2-live-mixed-city-slot-0704-02
create: 22.904s / 동해시 / KR-51-170 / 10 items
mixed modify: 19.180s / 강릉시 / KR-51-150 / 10 items
```

결론:

- 현재 구현은 복합 modify를 복합 수정으로 처리하지 않는다.
- city-change가 우선 적용되고, slot replace는 `edit_ops`로 남지 않는다.
- 따라서 사용자가 "도시도 바꾸고 장소도 바꿔줘"라고 말하면 현재는 "도시 변경 후 재생성"으로만 처리된다.
- 이 동작은 사용자 의도 일부를 조용히 누락하므로 올바른 최종 정책이 아니다.
- intent 단계에서 city-change와 slot replace가 한 요청에 함께 감지되면 `unsupported` 또는 `needs_clarification`으로 막아야 한다.
- 후속 구현 항목: `intent.modify_parser`/LLM modify parser가 mixed modify를 `kind=city_change`로 단순 축약하지 않고, `reason_code=modify_mixed_city_and_slot_unsupported` 같은 명시적 응답으로 올리게 한다.

---

## 4. 장소 교체 설계 메모

장소 교체는 도시 변경과 다르게 도시/일정 전체를 다시 만들지 않는다.

목표 흐름:

```text
rawModifyQuery
-> intent.modify_intent.edit_ops[]
-> supervisor
-> planner edit mode
-> response_packager
```

### 4.1 Intent 책임

Intent는 `rawModifyQuery + backend checkpoint state`를 기준으로 replace intent를 만든다.

필수 출력:

- `intent_type = modification`
- `kind = slot_replace`
- `status = ok | needs_clarification | unsupported`
- `routing_hint = planner_apply_edit`
- `edit_ops[]`

`edit_ops[]`의 핵심 필드:

- `target`
  - 어떤 response item을 바꿀지
  - `item_id`, `content_id`, `day`, `order`, `target_text`, `resolution`
- `condition`
  - 무엇으로 바꿀지
  - `replacement_query`
  - `replacement_query_raw`
  - `theme`
  - `mood`
  - `place_type`
  - `avoid_content_ids`
- `seed_policy`
  - seed item 보호 여부
  - same-theme replace 허용 여부

Intent는 장소 후보 검색을 하지 않는다. target resolution과 replacement 조건 구조화까지만 맡는다.

### 4.2 Supervisor 책임

`modify_intent.status`가 `ok`이고 `routing_hint = planner_apply_edit`이면 planner로 보낸다.

단, city-change에서 발견한 것처럼 stale response가 남아 있을 수 있다. 따라서 slot replace도 다음 원칙이 필요하다.

1. planner edit output이 없으면 `planner`
2. planner edit output이 있고 explain이 없으면 `explain_itinerary`
3. 새 response가 만들어지면 `end`
4. 기존 create response는 stale로 취급

새 response 판정은 city-change처럼 destination으로 구분하기 어렵다. 따라서 slot replace에는 별도 revision marker가 필요하다.

권장 marker:

```json
{
  "response": {
    "source_intent_type": "modification",
    "source_modify_kind": "slot_replace",
    "source_itinerary_revision": "rev-001"
  }
}
```

또는 response payload metadata에 같은 값을 넣는다.

### 4.3 Planner 책임

Planner는 전체 도시를 다시 선택하지 않는다.

Planner edit mode는 현재 itinerary를 base로 두고 target slot만 교체한다.

단일 replace 흐름:

```text
1. current itinerary load
2. target item locate
3. replacement source 결정
4. 후보 pool 생성
5. avoid_content_ids / existing itinerary content ids 제외
6. seed policy 검사
7. candidate score
8. target slot에 candidate 삽입
9. 해당 day route 재계산
10. explain/response 재생성
```

replacement source:

| 조건 | 후보 출처 | 비고 |
|---|---|---|
| `replacement_query` 없음 | 기존 planner reserve pool | "그 장소만 다른 곳으로" 같은 단순 교체. 새 vector search 없이 현재 일정 생성에서 남은 후보를 우선 사용한다. |
| `replacement_query` 있음 | 같은 도시 안 vector retrieval | "조용한 산책지로 바꿔줘" 같은 의도 교체. 해당 query로만 retrieval한다. |

검색/후보 범위:

- 기본은 현재 itinerary city 안에서만 작동한다.
- city-change request가 아니면 city_select를 다시 실행하지 않는다.
- `replacement_query`가 없으면 reserve pool을 먼저 사용한다.
- `replacement_query`가 있으면 reserve pool을 섞지 않고 query 전용 retrieval 결과만 사용한다.
- theme 조건이 함께 오면 retrieval filter 또는 post-filter에 적용한다.
- theme 조건이 없으면 theme filter를 강제하지 않는다.
- reserve pool이 비어 있거나 모든 후보가 제외/route 실패하면 fallback retrieval을 바로 돌리지 말고 notice 또는 clarification으로 올리는 쪽이 안전하다.

후보 제외:

- 교체 대상 content id
- 현재 일정에 이미 들어간 content ids
- user avoid 조건에 걸린 content ids
- seed conflict 정책에 걸린 candidates
- route hard limit을 위반하는 candidates

### 4.4 Scoring 방향

replace scoring은 city_select/planner 생성 scoring보다 좁아야 한다.

우선순위:

1. replacement source priority
2. replacement query similarity
3. required theme match
4. original target subtype 또는 compatible subtype
5. slot/time compatibility
6. same-day route insertion cost
7. seed policy compatibility

`replacement_query`가 있으면 query similarity를 우선한다.

`replacement_query`가 없으면 query similarity를 새로 만들지 않고 reserve pool의 기존 planner score를 우선한다.

```text
no modifyQuery:
  reserve candidates
  -> existing planner score / theme evidence
  -> route insertion cost

with modifyQuery:
  vector retrieval by replacement_query
  -> optional theme filter
  -> query similarity
  -> route insertion cost
```

기존 target item의 theme/subtype/slot/day context는 `replacement_query`가 없을 때 검색 query가 아니라 reserve 후보의 compatibility scoring에만 사용한다.

기존 문맥 기반 fallback retrieval은 V2.0 기본 경로로 두지 않는다. 이유는 사용자가 "그냥 바꿔줘"라고 했을 때 backend가 임의 해석 query를 만들어 새로운 장소를 끌고 오면 수정 의도가 과해질 수 있기 때문이다.

### 4.4.1 Modify Query 분기

`condition.replacement_query_raw` 또는 `condition.replacement_query`가 있으면 query-constrained replace다.

```text
target: 1일차 오후 장소
modifyQuery: 조용한 숲길
theme: 자연·트레킹
```

처리:

1. current city 안에서 `조용한 숲길` query로 retrieval
2. theme 조건이 있으면 `자연·트레킹` 후보만 생존
3. target/existing itinerary content id 제외
4. route hard limit 검사
5. 가장 좋은 후보를 target slot에 삽입

`condition.replacement_query`가 없으면 reserve-based replace다.

```text
target: 1일차 오후 장소
modifyQuery: null
```

처리:

1. 기존 planner reserve pool에서 후보를 읽음
2. target/existing itinerary content id 제외
3. target item의 theme/subtype/slot/day와 호환되는 후보를 우선
4. ORS/haversine route insertion 검사
5. 가장 좋은 후보를 target slot에 삽입

이 경로에서는 raw/soft query retrieval을 새로 돌리지 않는다.

### 4.4.2 다중 수정 정책

다중 replace는 가능하지만, V2.0에서는 "동시에 전역 최적화"가 아니라 **순차 적용**으로 시작한다.

권장 규칙:

1. `edit_ops`를 현재 itinerary order 기준으로 정렬한다.
2. 앞 op의 결과를 다음 op의 base itinerary로 사용한다.
3. 각 op마다 candidate pool을 독립적으로 만든다.
4. 앞 op에서 새로 사용한 content id는 뒤 op의 `avoid_content_ids`에 추가한다.
5. 한 op라도 unresolved/ambiguous/route impossible이면 전체 적용을 중단하고 `needs_clarification` 또는 partial-failure notice를 반환한다.
6. V2.0에서는 partial success를 사용자에게 자동 반영하지 않는다.

다중 replace가 어려운 이유:

- 두 target이 같은 day에 있으면 첫 교체가 두 번째 교체의 route cost를 바꾼다.
- 두 target이 서로 가까운 후보를 경쟁하면 candidate 중복이 생긴다.
- 한 target을 바꿨더니 다른 target의 hard leg limit이 깨질 수 있다.
- seed item이 포함되면 same-theme 정책과 route repair가 동시에 걸린다.

따라서 초기 구현의 안전한 제한:

- 최대 2개 replace까지 허용
- 모두 non-seed일 때만 자동 실행
- 같은 day multiple replace는 순차 적용하되 day route를 매 op 이후 재검증
- 서로 다른 day multiple replace는 각 day별로 독립 적용
- 3개 이상 또는 seed 포함 multiple replace는 clarification/unsupported로 올림

후속 고도화:

- 같은 day의 multiple replace를 batch 후보 조합으로 풀기
- 후보 조합별 route cost를 계산해 전역 최적 조합 선택
- 실패 op만 사용자에게 재질문하고 성공 op를 preview로 보여주는 partial edit flow

### 4.5 Route 적용

replace는 전체 route_days를 처음부터 다시 돌릴 수도 있지만, 초기 구현은 더 좁게 시작하는 것이 안전하다.

권장 V2.0 방식:

1. target day만 재배치한다.
2. target slot에 candidate를 넣고 day route를 다시 계산한다.
3. hard leg limit을 넘으면 다음 candidate를 시도한다.
4. 모든 candidate가 실패하면 `needs_clarification` 또는 notice를 반환한다.

후속 확장:

- target day 실패 시 다른 day로 이동 가능한지 simulation
- reserve candidate로 cross-day repair
- front reorder 결과를 정본으로 받는 경우, front order 기준 route repair

### 4.6 Clarification / Unsupported

replace는 다음 경우에 실행하지 않는다.

- target item unresolved
- target item ambiguous
- seed item을 다른 theme/city로 바꾸려는 경우
- replacement query가 도시 변경 의도를 포함하는 경우
- 후보가 route hard limit을 모두 위반하는 경우

이때는 `response_packager_wait_user`로 사용자에게 다시 묻는다.

---

## 5. 다음 구현 순서

권장 순서:

1. Supervisor에 `planner_apply_edit` 라우팅과 stale/new response marker 추가
2. Planner edit mode input adapter 추가
3. 단일 non-seed replace 구현
4. 같은 day route repair
5. seed same-theme replace
6. multiple replace

city-change troubleshooting에서 얻은 교훈:

- modify 경로는 이전 checkpoint state가 남아 있으므로 stale group을 항상 의식해야 한다.
- Supervisor는 "어떤 output이 현재 modify request에 의해 생성된 것인가"를 판정할 수 있어야 한다.
- 단순히 `response_payload` 존재 여부만 보면 modify loop가 쉽게 생긴다.

---

## 6. Targetless City Rediscovery Timeout

### 증상

`다른 도시로 바꿔줘` 요청을 같은 session에 넣으면 city rediscovery는 시작되지만 live smoke가 300-420초 timeout으로 끝났다.

### 분리 진단

- `intent`: 정상. `routing_hint=city_select_rediscovery`, `destination_id=None`, `disliked_city_ids=(기존 도시)`로 변환됨.
- `city_select`: 정상. 약 3.9초, 기존 동해시를 제외하고 삼척시 선택.
- `planner`: 정상. 약 3.5초, 삼척시 3일/10개 item 구성.
- `explain_itinerary`: 정상. 약 3.5초.
- `response_packager`: 정상.
- `full_no_checkpoint`: 수정 전에는 `GraphRecursionError` 발생.

### 원인

`has_current_modify_response_payload()`가 city_change의 명시 `target_city_id` 또는 `target_city_name`이 있는 경우만 현재 수정 응답으로 인정했다.

targetless rediscovery는 의도적으로 `target_city_id=None`, `target_city_name=None`이므로, response가 이미 생성된 뒤에도 Supervisor가 "현재 요청에 대한 응답이 아직 없다"고 판단했다. 그 결과 graph가 `explain_itinerary -> response_packager -> supervisor` 루프에 빠졌다.

추가로 기존 생성 intent의 `preferred_region_ids/spans/names`가 남아 있어 "동해시 선호 + 동해시 제외"가 동시에 적용되는 충돌도 있었다.

### 해결

- targetless city_change에서는 response destinationId가 존재하고 `avoid_city_ids`에 포함되지 않으면 현재 modify response로 인정한다.
- targetless rediscovery 진입 시 기존 `preferred_city_ids`, `preferred_region_ids`, `preferred_region_spans`, `preferred_region_names`를 비운다.

### 재검증

- `full_no_checkpoint`: 18.724초, `KR-51-230 / 삼척시`, 3일 일정.
- live smoke:
  - 기준 생성: `20260704T134409Z_intent-targetless-base-gen07.json`
  - targetless modify: `20260704T134553Z_intent-targetless-rediscovery-fixed.json`
  - 결과: `KR-51-230 / 삼척시`, 3일, 10 items, 28.721초.

### 추가 표현 검증

같은 session에서 유사한 targetless 표현도 확인했다.

- `비슷한 분위기로 다른 지역으로 바꿔줘.`
  - 결과: `KR-48-GOSEONG-GYEONGNAM / 고성군 (경상남도)`, 3일, 8 items, 28.587초.
  - 증거: `20260704T135914Z_intent-targetless-variant-01.json`
- `이번엔 다른 목적지로 다시 추천해줘.`
  - 결과: `KR-51-230 / 삼척시`, 3일, 10 items, 44.468초.
  - 증거: `20260704T140020Z_intent-targetless-variant-02.json`

주의: 현재 정책은 "이번 요청의 currentOrder 도시"만 즉시 exclude한다. 따라서 같은 session에서 여러 번 targetless city-change를 반복하면, 직전 도시가 아닌 과거 추천 도시로 다시 돌아올 수 있다. 장기적으로는 `memory.modify_history.excluded_city_ids` 누적 정책을 city-change rediscovery에도 명확히 적용해야 한다.

### Timing Instrumentation Follow-up

유독 느린 live case를 정확히 분리하려면 `run_general_live_smoke.py` 또는 live harness에 stage timing을 남긴다.

기록할 최소 구간:

1. AgentCore/checkpointer load
2. `intent`
3. `profile`
4. `festival_verifier`
5. `city_select`
6. `planner`
7. `explain_itinerary`
8. `response_packager`
9. AgentCore/checkpointer write

외부 호출 latency가 의심되는 경우에는 각 stage 내부에서 Bedrock embedding, S3 Vector query, DynamoDB lookup, ORS, Bedrock Converse copy generation을 별도 timing으로 분리한다.

판정 기준:

- node별 timing은 빠른데 full live만 느리면 checkpointer/replay/write 비용을 의심한다.
- `explain_itinerary`만 흔들리면 Bedrock Converse copy generation 지연을 의심한다.
- `city_select` 또는 `planner.retrieve_places`가 느리면 embedding/S3 Vector query 병목을 본다.
- `route_days`가 느리면 ORS matrix/snap 호출과 route repair loop를 본다.

---

## 7. Slot Replace Stabilization Before Day-level Edit

### 증상

하루 전체 수정으로 넘어가기 전, 단일 slot replace와 같은 day multi-slot replace에서 다음 문제가 함께 관측됐다.

- `1일차 세 번째`, `첫날 가운데 코스`, `마지막 코스` 같은 한국어 순번 표현이 deterministic parser에서 누락될 수 있었다.
- 같은 day의 `2번째, 3번째 장소를 ...로 바꿔줘` 요청을 LLM fallback이 단일 op로 축소할 수 있었다.
- replacement query에 theme가 포함되면 vector retrieval 단계에서 theme hard filter가 걸려 후보가 과도하게 줄었다.
- query가 있는데 explicit theme가 없는 경우에도 기존 active theme가 replacement 후보 우선순위에 개입했다.
- 새로 retrieval한 후보 중 기존 itinerary item이 다시 선택될 수 있었다.
- multi/failed slot replace response가 이미 packaged된 뒤에도 Supervisor가 다시 `response_packager`로 보내는 loop 위험이 있었다.

### 원인

- modify parser가 숫자 순번 중심으로 작성되어 한국어 순번과 같은 day list target을 충분히 정규화하지 못했다.
- LLM prompt fallback은 target 위치 해석을 보완하기 위한 경로였지만, rule parser가 이미 정확히 잡은 multi-op를 덮어쓸 수 있었다.
- apply_edit의 retrieval `theme` 인자가 hard filter로 사용되어, 사용자의 "분위기/장소 유형" 요청이 theme sparse case에서 실패로 이어졌다.
- active theme는 초회 생성의 맥락인데, query 기반 slot replace에서는 사용자가 방금 말한 replacement query보다 강하게 작동하면 안 된다.
- Supervisor의 "현재 modify 응답인가" 판정이 single `applied_edit/failed_edit` 중심이라 `applied_edits/failed_edits` list를 충분히 보지 못했다.

### 해결

- deterministic parser에 `첫/두/세/네/마지막` 순번과 같은 day multi target parser를 추가했다.
- rule parser가 multi-op를 만들었거나, LLM fallback이 `modify_target_unresolved`를 반환하면 rule 결과를 유지한다.
- replacement retrieval은 항상 theme filter 없이 검색한다.
- explicit `condition.theme`는 후보 정렬의 soft priority로만 사용한다.
- query가 있고 explicit theme가 없으면 active theme soft priority도 적용하지 않고 raw similarity 순서를 우선한다.
- query가 없고 reserve pool을 쓰는 replace에서만 기존 active theme soft priority를 유지한다.
- fresh retrieval 후보에서 current itinerary content id를 제외한다.
- Supervisor가 `applied_edits/failed_edits` list도 현재 request 결과로 인식하고, 이미 response payload가 있으면 graph를 종료한다.

### 재검증

- targeted tests: `56 passed`
  - `test_modify_intent_rule_parser.py`
  - `test_modify_intent_llm.py`
  - `test_planner_apply_edit.py`
  - `test_planner_apply_edit_theme_priority.py`
  - `test_planner_apply_edit_multi.py`
  - `test_planner_apply_edit_seed_policy.py`
  - `test_planner_apply_edit_notice.py`
  - `test_supervisor_graph.py`
- live smoke:
  - `20260705T053425Z_0705-modify-same-day-multi-theme-soft-a.json`
    - same-day multi query replacement completed, two slots replaced.
  - `20260705T054145Z_0705-modify-slot-position-rough-photo-a.json`
    - rough slot-position query replacement completed.

### 남은 범위

- `1일차 전체 바꿔줘` 같은 day-level edit는 아직 slot replace가 아니라 별도 `day_regenerate` 계열로 설계해야 한다.
- 복합 수정은 sequential fold로 처리하되, city_change와 slot_replace가 한 문장에 섞인 경우는 intent 단계에서 unsupported/clarification으로 막는 방향이 안전하다.
- query 있는 slot replace는 now-current policy 기준으로 replacement query가 최우선이며, active theme는 개입하지 않는다.
