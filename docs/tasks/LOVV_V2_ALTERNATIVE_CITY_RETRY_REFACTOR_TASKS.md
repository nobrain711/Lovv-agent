# LOVV V2 — Alternative City Retry Refactor Tasks

작성일: 2026-07-04

상태: 이후 작업용 task 문서

범위: alternative city 기능은 유지하되, planner graph의 별도 `retry_alternative_city` node를 제거하고 기존 planner orchestration 내부로 흡수한다.

---

## 1. 배경

현재 planner subgraph는 생성 경로에서 다음 구조를 가진다.

```text
retrieve_places
-> route_days
-> assemble_itinerary
-> { retry_alternative_city -> retrieve_places | END }
```

`retry_alternative_city`는 planner가 `insufficient_candidates`를 낸 뒤, `city_select.city_selection_result.alternative_city`가 있으면 selected city를 대체 도시로 바꾸고 retrieve/route/assemble을 한 번 더 실행하기 위해 분리된 node다.

이 분리는 초기에 유용했다.

- planner core와 silent city replacement를 분리했다.
- fallback 재시도를 한 번으로 제한해 무한 loop를 막았다.
- city_select가 넘긴 `alternative_city.seeds`를 명시적으로 소비했다.

하지만 현재 planner 구조에서는 이 기능이 별도 graph node로 남아 있어 흐름을 복잡하게 만든다. 특히 `retrieve_places`, `route_days`, `assemble_itinerary`가 공식 생성 경로인데, 그 뒤에 다시 도시를 교체하는 graph-level loop가 붙어 있어 생성/수정 구조 설명이 어려워진다.

---

## 2. 결정

Alternative city 기능은 당장 제거하지 않는다.

다만 별도 LangGraph node로 두지 않고, planner 내부 orchestration으로 낮춘다.

목표 구조:

```text
retrieve_places
-> route_days
-> assemble_itinerary
-> END
```

fallback 판단과 대체 도시 적용은 graph edge가 아니라 planner 내부 helper로 처리한다.

권장 위치:

```text
planner/steps/alternative_city/
  policy.py   # retry 가능 여부 판단
  apply.py    # city_selection_result를 alternative city로 전환
```

또는 기존 `steps/retry_alternative_city/node.py`를 `steps/alternative_city/` 아래 helper로 옮긴다.

---

## 3. 유지할 동작

기능 자체는 유지한다.

유지 조건:

- planner status가 `insufficient_candidates`
- 아직 fallback을 사용하지 않음
- `city_select.city_selection_result.alternative_city`가 있음
- alternative city에 usable `seeds`가 있음
- direct anchor / city-change / slot-replace 경로가 아님

유지 결과:

- selected city를 alternative city로 전환
- original selected city는 `city_selection_result.alternative_city` 또는 fallback audit에 보존
- `planner.fallback.used = true`
- `planner.fallback.reason = primary_city_insufficient_candidates`
- 이후 retrieve/route/assemble을 한 번만 재실행

---

## 4. 제거할 구조

제거 대상:

- `planner/subgraph.py`의 `retry_alternative_city` node 등록
- `assemble_itinerary -> retry_alternative_city -> retrieve_places` graph edge
- `state_adapter.retry_alternative_city()` graph node adapter

유지 또는 이동 대상:

- retry 가능 여부 판단 로직
- alternative selected city payload 생성
- fallback audit 생성
- existing tests의 business expectation

---

## 5. 구현 순서

1. 현재 `retry_alternative_city` 테스트를 subgraph 결과 중심으로 유지한다.
2. `steps/retry_alternative_city/node.py`의 로직을 graph node가 아닌 helper 단위로 분리한다.
3. `state_adapter` 또는 planner orchestration helper에서 다음 순서를 내부 실행한다.

```text
run retrieve_places
run route_days
run assemble_itinerary
if should_retry_alternative_city:
    apply alternative city
    run retrieve_places
    run route_days
    run assemble_itinerary
return final state
```

4. `planner/subgraph.py`에서는 graph edge를 단순화한다.

```text
retrieve_places -> route_days -> assemble_itinerary -> END
apply_edit -> END
```

5. `compile_planner_subgraph()`와 `compile_v2_graph()`가 동일하게 동작하는지 확인한다.
6. alternative fallback live/smoke는 나중에 별도 케이스로 검증한다.

---

## 6. 테스트 계획

관련 테스트:

- `tests/v2/test_planner_alternative_fallback.py`
- `tests/v2/test_planner.py`
- `tests/v2/test_state_contract.py`

필수 확인:

- alternative city가 있는 thin primary city는 한 번 fallback한다.
- alternative city가 있어도 seeds가 없으면 fallback하지 않는다.
- direct anchor는 fallback하지 않는다.
- slot replace는 fallback 경로를 타지 않는다.
- graph compile이 통과한다.

---

## 7. 주의사항

이 작업은 alternative city 정책 자체를 바꾸는 작업이 아니다.

정책 변경, 즉 "자동 도시 교체를 완전히 끄고 사용자에게 물어보기"는 별도 결정이다. 이 task는 기능을 유지하면서 graph 구조를 단순화하는 리팩터링이다.

따라서 결과 응답의 사용자 의미는 그대로 두고, 내부 graph node 구조만 정리한다.
