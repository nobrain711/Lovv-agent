# LOVV V2 User Clarification Troubleshooting

> 범위: `END_WAIT_USER` interrupt/resume 인프라를 실제 create clarification 흐름에 연결하면서 발견한 문제와 수정 원칙.
> 기준일: 2026-07-05

---

## 1. 문제: corrected clarification 입력이 공통 resume 흐름을 벗어남

### 증상

- 모순 입력으로 `END_WAIT_USER` clarification이 발생한 뒤, 사용자가 조건을 바로잡아 다시 입력해도 기존 clarification 상태가 남거나 새 요청처럼 처리될 위험이 있었다.
- 초기 live 확인에서 corrected input을 `entryType=create`처럼 다시 보내는 방식으로 검증하여, 실제 front 계약인 `entryType=clarify` 흐름을 충분히 검증하지 못했다.
- 한때 `agentcore_entrypoint`에서 특정 clarification reason을 보고 `revise_conditions` resume을 자동 구성한 뒤 graph를 다시 호출하는 우회가 들어갔다.

### 원인

- public API 입력 계약상 front는 기존 request shape를 유지하되 `entryType=clarify`로 corrected fields를 보낸다.
- 반면 application-level 의미 처리는 response packager interrupt continuation 이후에 이루어져야 한다.
- entrypoint가 `reasonCode`, `optionId`, `then` 같은 clarification 의미를 해석하면 공통 interrupt/resume 책임 경계가 깨진다.

---

## 2. 확정한 책임 분리

### AgentCore entrypoint

- `entryType=clarify` payload를 발견하면 `Command(resume=<payload>)`로 graph에 전달한다.
- reason별 option 적용, corrected create 해석, downstream state reset은 하지 않는다.
- 즉 entrypoint는 IO adapter이며 clarification 의미를 모른다.

### Response packager continuation

- interrupt 이후 resume 값을 받아 application-level update로 변환한다.
- button option resume은 checkpoint에 저장된 option에서 `apply + then`을 복원한다.
- free-input corrected clarification은 `entryType=clarify` payload를 corrected create 입력으로 해석하고, stale downstream state를 비운다.

### Intent node

- `entryType=clarify`라도 create 필드가 있으면 corrected create로 정규화한다.
- option button resume과 corrected free input resume을 구분한다.
- stale `intent.city_select_input`, `festival_gate`, `city_select`, `planner`, `response`, `routing`이 새 생성 흐름에 섞이지 않도록 초기화 경계를 제공한다.

---

## 3. 수정 파일

- `src/lovv_agent_v2/agentcore_entrypoint.py`
  - `entryType=clarify`를 `Command(resume=...)`로 전달.
  - reason-aware auto-reinvoke 우회 제거.
- `src/lovv_agent_v2/agents/response_packager/clarification_resume.py`
  - option resume과 corrected free-input resume을 분리.
  - corrected create 입력이면 downstream state reset update 생성.
- `src/lovv_agent_v2/agents/intent/node.py`
  - corrected clarify payload를 create-equivalent input으로 파싱.

---

## 4. 검증

### Focused tests

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\v2\test_entrypoint.py::test_handle_v2_invocation_sends_clarify_request_as_resume `
  tests\v2\test_response_packager_node.py::test_response_resume_update_restarts_from_corrected_clarify_payload `
  tests\v2\test_response_packager_node.py::test_response_packager_node_resumes_with_checkpoint_option `
  tests\v2\test_intent_dispatch_contract.py::test_intent_node_treats_clarify_with_create_fields_as_corrected_create `
  tests\v2\test_intent_dispatch_contract.py::test_intent_node_resolves_button_clarification_from_pending_memory `
  -q --basetemp .tmp_pytest\clarify-common
```

결과: `5 passed`

### Live smoke

동일 session에서 진행:

1. contradiction create
   - 결과: `docs/tasks/results/v2_general_live_smoke/20260705T125606Z_intent-contradiction-common-initial.json`
   - `clarificationReason=contradiction`
   - `dayCount=0`, `itemCount=0`
2. corrected clarify
   - 입력: `docs/tasks/results/v2_intent_mocks/intent_live_contradiction_clarify_corrected_20260705.json`
   - 결과: `docs/tasks/results/v2_general_live_smoke/20260705T125630Z_intent-contradiction-common-clarify.json`
   - `entryType=clarify`
   - `destinationId=KR-51-150`
   - `destinationName=강릉시`
   - `dayCount=1`, `itemCount=3`
   - `clarificationReason=null`

---

## 5. 재발 방지 원칙

- clarification 의미 처리는 entrypoint에 넣지 않는다.
- `entryType=clarify`는 graph resume 신호이며, fresh create 재요청으로 우회하지 않는다.
- option 선택형 clarification과 자유 입력형 clarification은 response packager continuation에서 분기한다.
- stale state reset은 corrected input을 실제 새 생성 흐름으로 되돌릴 때만 수행한다.
- 실제 action 처리 루프가 아직 없는 clarification은 문서에 “infra wired, semantic resume pending”으로 남긴다.

---

## 6. 문제: Generation 후보 부족이 일부 일정으로 포장되어 clarification을 지나침

### 증상

- `v2_gen_06_healing_2d1n` live 실행에서 planner가 후보 부족 notice를 남겼지만, 1개 장소짜리 일정이 존재한다는 이유로 `END_WAIT_USER`가 발생하지 않았다.
- 결과 파일: `docs/tasks/results/v2_general_live_smoke/20260705T141854Z_gen-insufficient-relax-create.json`
- 응답은 `destinationId=KR-2-4`, `itemCount=1`, `clarificationReason=null`이었다.

### 원인

- 초기 구현은 `planner_status_gate=insufficient_candidates`이면서 `itinerary=[]`인 경우만 generation 후보 부족 clarification으로 보냈다.
- 실제 planner는 “일부 장소는 만들었지만 목표 일정으로는 부족한” 케이스도 `insufficient_candidates`로 표시한다.
- 사용자 관점에서는 이 경우도 조건 완화/다른 도시 탐색 선택지가 필요하다.

### 수정

- response packager의 generation 후보 부족 판정을 `planner_status_gate=insufficient_candidates` 기준으로 단순화했다.
- 단순 city_select thin/risk 신호는 여전히 clarification으로 승격하지 않는다.
- `search_other_city` resume은 현재 선택 도시를 `disliked_city_ids`에 넣고 discovery를 재실행한다.
- `relax_generation_themes` resume은 빈 테마가 아니라 검색 가능한 V2 장소 테마 전체로 확장한다.

### Live 확인

- 수정 후 초기 생성:
  - `docs/tasks/results/v2_general_live_smoke/20260705T142012Z_gen-insufficient-relax-create.json`
  - `clarificationReason=generation_insufficient_candidates`
- 테마 완화 option:
  - `docs/tasks/results/v2_general_live_smoke/20260705T142049Z_gen-insufficient-relax-resume.json`
  - `destinationName=영천시`, `itemCount=4`, `clarificationReason=null`
- 다른 도시 option:
  - `docs/tasks/results/v2_general_live_smoke/20260705T142211Z_gen-insufficient-other-resume.json`
  - `destinationName=단양군`, `itemCount=2`, 다시 `generation_insufficient_candidates`

### 남은 주의점

- `온천·휴양`처럼 데이터가 희소한 테마는 다른 도시로 바꿔도 다시 후보 부족이 될 수 있다.
- 반복 clarification UX와 sparse theme 전용 안내는 별도 정책으로 다룬다.
