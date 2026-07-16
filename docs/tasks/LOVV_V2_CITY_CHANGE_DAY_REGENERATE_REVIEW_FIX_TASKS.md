# LOVV V2 City Change / Day Regenerate Review Fix Tasks

작성일: 2026-07-16  
상태: 후속 리뷰 패치 구현 및 검증 완료
대상 브랜치: `fix/v2-city-change-generic-request`

## 1. 목표

현재 PR 리뷰에서 확인된 세 가지 회귀를 기존 수정 파이프라인의 구조를 바꾸지 않고 최소 범위로 해결한다.

- 부정 문맥의 도시명은 direct anchor가 아니라 rediscovery 제외 조건으로 해석한다.
- day regeneration에서는 request `currentOrder`를 최신 정본으로 유지한다.
- 잘못된 `currentOrder` 항목이 planner 결과에 섞이지 않도록 입력 경계를 검증한다.

## 2. 검토 결과

세 리뷰 모두 현재 PR head에서 발생 가능한 유효한 지적이다. 세 건 모두 public response schema나 graph topology를 변경하지 않고 빠르게 수정할 수 있다.

| 항목 | 확인된 원인 | 수정 난이도 |
|---|---|---|
| 부정 도시가 direct anchor로 처리됨 | `find_city_identity_in_text()`가 `말고 다른 도시` 문맥보다 먼저 실행됨 | 낮음 |
| 동일 ID의 최신 일정이 stale 값으로 덮임 | request item을 선택한 뒤 `_existing_itinerary_item()`이 같은 `contentId`의 checkpoint item을 우선 반환함 | 낮음 |
| 빈 mapping이 일정 항목으로 유입됨 | `_mapping_sequence()`가 필수 필드가 없는 `{}`도 정상 mapping으로 수용함 | 낮음 |

## 3. 공통 원칙

1. `src/lovv_agent_v2`를 canonical source로 수정한 뒤 app mirror를 동기화한다.
2. front가 보낸 유효한 `currentOrder`는 checkpoint보다 우선한다.
3. 명시적으로 전달된 `currentOrder`가 잘못된 경우 stale checkpoint로 조용히 대체하지 않는다.
4. 기존 `planner_direct_anchor`, `city_select_rediscovery`, `modify_missing_current_itinerary` public 계약은 유지한다.
5. 기존 positive city change와 generic targetless city change 동작을 그대로 보존한다.

## 4. 구현 작업

### 4.1 부정/targetless 도시 변경 우선순위

수정 대상:

- `src/lovv_agent_v2/agents/intent/modify_city_change.py`
- `tests/v2/test_city_change_rediscovery.py`
- app mirror의 동일 파일

구현:

1. 도시 identity를 direct anchor로 확정하기 전에 부정 도시 문맥을 판정한다.
2. `<도시명> 말고 다른 도시`, `<도시명> 제외하고 도시 변경`처럼 명시 도시가 제외 대상인 경우 targetless rediscovery를 반환한다.
3. 부정 문맥에서 찾은 도시 ID를 기존 current city 및 memory exclusion과 함께 `avoid_city_ids`에 누적하고 순서를 유지한 채 중복 제거한다.
4. 긍정 문맥인 `군산으로 바꿔줘`는 계속 `planner_direct_anchor`로 처리한다.

회귀 테스트:

- `군산 말고 다른 도시로 바꿔줘` -> `city_select_rediscovery`
- 위 결과의 `target_city_id`는 `None`
- `avoid_city_ids`와 `city_select_input.disliked_city_ids`에 군산 ID 포함
- `군산으로 도시 바꿔줘` -> 기존 `planner_direct_anchor` 유지
- `다른 도시로 바꿔줘` -> 기존 targetless rediscovery 유지

### 4.2 Day regeneration의 request 정본 유지

수정 대상:

- `src/lovv_agent_v2/agents/planner/steps/apply_edit/result.py`
- `src/lovv_agent_v2/agents/planner/steps/apply_edit/current_order_snapshot.py`
- `src/lovv_agent_v2/agents/planner/steps/apply_edit/result_day_regenerate.py`
- `tests/v2/test_planner_day_regenerate_current_order.py`
- app mirror의 동일 파일

구현:

1. `full_order`가 전달된 day regeneration에서는 untouched item의 title, day, order, slot, 좌표, city ID, theme, seed 여부를 request item 기준으로 만든다.
2. 동일 `contentId`가 checkpoint에 있더라도 request에 존재하는 값은 checkpoint 값으로 덮지 않는다.
3. request에 없는 설명성 보조 필드만 checkpoint에서 보강할 수 있다.
4. request `currentOrder`가 없을 때만 기존 checkpoint itinerary fallback을 사용한다.

회귀 테스트:

- request와 checkpoint에 동일 `contentId`를 둔다.
- title, day/order, `timeOfDay`, latitude, longitude를 서로 다른 값으로 구성한다.
- regenerate 대상이 아닌 day의 결과가 모두 request 값을 유지하는지 확인한다.
- 기존의 서로 다른 `contentId` currentOrder 우선 테스트도 유지한다.

### 4.3 `currentOrder` 입력 경계 검증

수정 대상:

- `src/lovv_agent_v2/agents/intent/modify_current_order.py`
- `tests/v2/test_modify_current_order.py`
- 필요 시 day/slot modify focused test
- app mirror의 동일 파일

유효 항목 최소 조건:

- non-empty `contentId`, `content_id`, `placeId`, `festivalId` 중 하나
- 1 이상의 정수 `day`
- 1 이상의 정수 `order`
- `bool`은 정수로 인정하지 않음

구현:

1. request에 `currentOrder` 키가 명시된 경우 해당 배열을 독립적으로 검증한다.
2. `{}` 또는 필수 필드가 빠진 항목이 하나라도 있으면 해당 request order 전체를 사용 불가로 처리한다.
3. 명시된 request order가 잘못된 경우 checkpoint order로 조용히 fallback하지 않는다.
4. day/slot 수정은 기존 `modify_missing_current_itinerary` clarification으로 안전하게 종료한다.
5. request에 `currentOrder` 자체가 없을 때만 기존 planner/response checkpoint fallback을 허용한다.

회귀 테스트:

- `currentOrder=[{}]`가 결과 itinerary에 들어가지 않음
- 잘못된 request order가 valid checkpoint를 가리지 않고 사용하는 것이 아니라, 수정 대기 clarification으로 종료됨
- valid request order는 계속 checkpoint보다 우선함
- request order가 생략된 기존 follow-up은 checkpoint fallback을 유지함

## 5. 구현 순서

1. 세 회귀 테스트를 먼저 추가하고 수정 전 실패를 확인한다.
2. city-change 부정 문맥 우선순위를 수정한다.
3. `currentOrder` 입력 경계를 보강한다.
4. day regeneration의 request 우선 merge를 수정한다.
5. canonical source의 focused test 통과 후 app mirror를 동기화한다.
6. app mirror compile/import smoke와 src/app 동일성을 확인한다.

## 6. 관련 테스트

```powershell
$env:PYTHONPATH='src'
$env:LOVV_MEMORY_ENABLED='false'

uv run pytest `
  tests/v2/test_city_change_rediscovery.py `
  tests/v2/test_city_change_identity_map.py `
  tests/v2/test_modify_current_order.py `
  tests/v2/test_planner_day_regenerate.py `
  tests/v2/test_planner_day_regenerate_current_order.py -q
```

넓은 전체 suite나 배포 runtime live test는 이 task의 필수 범위가 아니다. 구현 후 local memory-off에서 다음 두 흐름만 추가 확인한다.

1. 정상 생성 -> `군산 말고 다른 도시로 바꿔줘` -> 군산 제외 rediscovery
2. 정상 생성 -> 최신 `currentOrder` 전달 -> day regeneration -> untouched day 값 보존

## 7. 완료 기준

- 부정 문맥의 명시 도시는 direct anchor로 사용되지 않는다.
- 부정 도시 ID가 rediscovery 제외 목록에 반영된다.
- positive named city change와 generic targetless rediscovery가 모두 기존대로 동작한다.
- day regeneration에서 동일 ID의 request 최신 값이 checkpoint에 의해 덮이지 않는다.
- 잘못된 mapping은 planner itinerary에 유입되지 않는다.
- 명시적 malformed `currentOrder`는 stale checkpoint로 대체되지 않는다.
- 관련 focused test와 app mirror 검증이 통과한다.

## 8. 예상 영향

이 작업은 수정 요청 파싱 우선순위, current order 정규화, day regeneration 결과 조립만 건드린다. city selection 점수, place retrieval, route feasibility, slot replacement 후보 선택, public response envelope에는 영향을 주지 않는다.

## 9. 검증 결과

### 9.1 Red -> Green

수정 전 신규 회귀 테스트 결과:

- 부정 도시 요청: `planner_direct_anchor`로 잘못 분기
- malformed `currentOrder=[{}]`: `modify_missing_current_itinerary`로 종료되지 않음
- 동일 `contentId`: checkpoint의 오래된 제목이 request 최신 제목을 덮음
- 결과: `3 failed`

수정 후 동일 테스트 결과:

- 결과: `3 passed`

### 9.2 Focused regression

관련 city change, currentOrder, day regeneration 테스트를 실행했다.

- 결과: `20 passed`
- positive named city direct anchor 유지
- generic targetless city rediscovery 유지
- request가 생략된 checkpoint currentOrder fallback 유지

### 9.3 Local memory-off live E2E

실행 조건:

- `LOVV_MEMORY_ENABLED=false`
- checkpointer: process-local `MemorySaver`
- 동일 session에서 `create -> day_regenerate -> city rediscovery` 순차 실행
- invocation별 60초 제한

관측 결과:

| 단계 | 결과 | 소요 시간 |
|---|---|---:|
| 군산시 anchored create | `KR-37-2`, 6개 일정 항목 | 22.103초 |
| 1일차 day regeneration | day 2의 최신 title/slot/좌표 유지 | 7.139초 |
| `군산 말고 다른 도시로 바꿔줘` | 익산시 `KR-37-9` 선택, clarification 없음 | 15.849초 |

`AGENT_MEMORY_GUARD`에서 `memoryMode=local_memory_saver`, `eventGuard=agentcore_memory_disabled`를 확인했다.

## 10. PR 재검토 후속 작업

PR HEAD `41786cd3` 재검토에서 확인된 세 merge blocker를 같은 입력 경계 task로 이어서 처리한다.

### 10.1 도시 부정 표현의 범위 제한

- 문장 전체의 `말고/제외/빼고/싫` 존재 여부로 목적 도시를 부정하지 않는다.
- 식별된 도시명 바로 뒤의 조사와 부정 표현만 해당 도시 exclusion으로 해석한다.
- `복잡한 곳은 싫어서 군산으로 도시 바꿔줘`는 군산 direct anchor를 유지한다.
- `군산 말고 다른 도시로 바꿔줘`는 기존처럼 군산 exclusion rediscovery를 유지한다.

### 10.2 `currentOrder` 상태와 consumer 계약 분리

- request `currentOrder`의 missing, empty, valid, malformed 상태를 구분한다.
- missing 또는 empty는 checkpoint fallback을 허용한다.
- non-empty malformed는 stale checkpoint로 대체하지 않고 clarification으로 종료한다.
- city exclusion 추출은 `cityId`만 필요하므로 day/order가 없는 city-only snapshot도 사용할 수 있다.
- slot/day 수정은 canonical content ID와 양의 day/order를 계속 요구한다.

### 10.3 Canonical item과 optional metadata

- `contentId`, `content_id`, `placeId`, `festivalId`를 canonical `contentId`로 정규화한다.
- prompt target은 canonical item만 사용해 alias가 `content_id=None`으로 내려가지 않게 한다.
- `indoorOutdoor` 등 optional metadata는 허용 타입으로 좁힌 뒤 overlay에 사용한다.
- 잘못된 optional 타입이 있어도 `TypeError`로 전체 수정 흐름을 중단하지 않는다.

### 10.4 후속 완료 기준

- unrelated dislike와 positive named destination이 함께 있어도 direct anchor가 유지된다.
- empty request order는 checkpoint 일정으로 fallback한다.
- city-only request order에서 기존 도시 exclusion을 복원한다.
- ID alias가 slot target의 canonical content ID로 전달된다.
- invalid optional exposure가 planner overlay에서 예외를 만들지 않는다.
- 관련 focused regression, src/app mirror, local memory-off 수정 흐름이 통과한다.

### 10.5 후속 검증 결과

Red 단계에서는 다음 5개 회귀가 모두 재현됐다.

- unrelated `싫` 표현이 군산 direct anchor를 rediscovery로 뒤집음
- city-only `currentOrder`에서 기존 도시 exclusion 누락
- empty `currentOrder`가 checkpoint fallback 차단
- `placeId` alias가 prompt target에서 `content_id=None`으로 전달됨
- `indoorOutdoor=[]`가 planner overlay에서 `TypeError` 발생

최소 수정 후 검증 결과:

- 신규 회귀: `5 passed`
- 관련 city change, prompt normalizer, slot/day apply regression: `46 passed`
- 변경 파일 compile: 통과
- src/app mirror: 동일
- 변경 Python 파일: 모두 250 pure LOC 이하

Local memory-off E2E는 동일 session에서 다음 순서로 실행했다.

| 단계 | 결과 |
|---|---|
| 역사·전통 2d1n 생성 | `KR-47-770`, 6개 일정 항목 |
| `복잡한 곳은 싫어서 군산으로 도시 바꿔줘` | 군산 `KR-37-2` direct anchor |
| `currentOrder=[]` 후 slot 수정 | checkpoint fallback 후 Planner 진입 |

마지막 slot 수정은 대체 후보의 동선 불가로 `slot_replace_route_infeasible` clarification에 도달했다. 이는 기존 일정 부재 오류가 아니라 Planner의 정상적인 후보 검증 결과다. `AGENT_MEMORY_GUARD`는 `local_memory_saver`, `agentcore_memory_disabled`를 기록했다.
