# LOVV V2 User Clarification Implementation Tasks

작성일: 2026-07-05
브랜치: `feature/user_clarification`
기준 문서: `docs/reports/v2/V2_36_INTERRUPT_HANDLING_MATRIX.md`

## 1. 이번 브랜치의 목표

V2에서 사용자의 추가 선택이 필요한 지점을 `END_WAIT_USER` + LangGraph interrupt로 일관되게 처리한다.

핵심 원칙:

- 초회 생성 성공과 일반 수정 결과는 `modification_pending`으로 끝낸다.
- `END_WAIT_USER`는 사용자의 선택 없이는 다음 안전한 실행이 불가능한 경우에만 사용한다.
- 사용자는 `optionId`만 보내고, 서버는 checkpoint에 저장된 원본 option의 `apply`와 `then`을 복원한다.
- 자연어 clarification 답변 해석은 후속 범위이며, 이번 브랜치는 button/option 기반 resume을 우선한다.
- 서버는 SSR처럼 사용자에게 보여줄 `prompt`, `label`, `helperText`를 완성해서 반환한다.

## 2. Agent별 Clarification 후보 전체

상태 표기:

| 상태 | 의미 |
|---|---|
| 구현 완료 | 현재 코드에서 public `clarification` 응답, interrupt/resume 또는 명시 종료 동작까지 확인됨 |
| 응답 완료 / action 후속 | `END_WAIT_USER` 응답은 만들지만, 선택 후 실제 재시도 action은 후속 구현 |
| 후속 후보 | 아직 clarification 생성 또는 판정 로직이 없음 |
| notice 유지 | 사용자 선택 없이 계속 진행하고 notice/audit으로만 남김 |

Clarification 후보는 아래처럼 세 등급으로 나눈다.

| 등급 | 의미 |
|---|---|
| 당장 처리 | 이번 브랜치에서 `END_WAIT_USER` + option 기반 resume 또는 abort 안내까지 닫는다 |
| 이후 처리 | 사용자 선택이 필요하지만 action/resume 계약이 아직 부족하다 |
| notice 유지 | 사용자 선택 없이 계속할 수 있으므로 `modification_pending` notice로만 알린다 |

### 2.1 Intent Agent

| case | reason_code | 상태 | 입력 유형 | 응답 | 비고 |
|---|---|---|---|---|---|
| 선호/비선호 테마 overlap | `contradiction` | 구현 완료 | 자유 입력형 | `END_WAIT_USER` | `revise_conditions`, `then=abort`; 같은 thread에 `entryType=clarify` 정정 입력 가능 |
| 선호/비선호 지역 overlap | `contradiction` | 구현 완료 | 자유 입력형 | `END_WAIT_USER` | city/region preference filter 적용 전 차단 |
| modify target이 currentOrder에서 해소되지 않음 | `modify_target_unresolved` | 구현 완료 | 자유 입력형 | `END_WAIT_USER` | 슬롯 위치를 다시 묻는다 |
| modify target이 여러 항목에 걸림 | `modify_target_ambiguous` | 응답 완료 / action 후속 | option 제시형 | `END_WAIT_USER` | 후보 슬롯 중 하나를 고르게 하려면 `then=planner_apply_edit` 후속 필요 |
| seed를 다른 테마로 바꾸려 함 | `modify_seed_theme_conflict` | 구현 완료 | 자유 입력형 | `END_WAIT_USER` | seed replace 정책상 같은 테마만 허용 |
| 서로 충돌하는 modify op | `modify_ops_conflict` | 구현 완료 | 자유 입력형 | `END_WAIT_USER` | 같은 target 중복 등은 실행 전 차단 |
| add/remove/reorder/trip length/booking | 없음 | notice 유지 | 없음 | `modification_pending` | backlog/unsupported notice |
| 너무 짧거나 목적지가 불명확한 생성 입력 | `underspecified` | 후속 후보 | 자유 입력형 | `END_WAIT_USER` | 아직 intent 판정 로직 미확정 |
| 한국 외 지역/서비스 범위 밖 | `out_of_scope_region` | 후속 후보 | 자유 입력형 | `END_WAIT_USER` | scope detector 필요 |

### 2.2 Profile Agent

| case | reason_code | 등급 | 응답 | 비고 |
|---|---|---|---|---|
| profile 없음/비활성 | 없음 | notice 유지 | 기존 flow 계속 | cold start는 정상 |
| profile theme weight가 약함/없음 | 없음 | notice 유지 | 기존 flow 계속 | 추천 품질 신호이지 사용자 질문 대상 아님 |
| 저장 확정 전 profile 반영 여부 | 없음 | 이후 처리 | terminal/save flow | clarification이 아니라 save/confirm 계약 |

### 2.3 Festival Verifier

Festival Verifier는 이번 브랜치의 1차 구현 대상이다.

| case | reason_code | 상태 | 입력 유형 | 응답 | resume action |
|---|---|---|---|---|---|
| 요청 월에 확정 축제 도시 없음 | `festival_none` | 구현 완료 | option 제시형 | `END_WAIT_USER` | 축제 없이 discovery, 테마 무관 축제 재검색, 중단 |
| 확정 축제는 없고 잠정 후보만 있음 | `festival_tentative` | 구현 완료 | option 제시형 | `END_WAIT_USER` | 잠정 위험 수락 후 anchor, 또는 축제 없이 discovery |
| anchor 도시에는 축제가 없고 월 전체에는 confirmed 도시가 있음 | `anchor_festival_conflict` | 구현 완료 | option 제시형 | `END_WAIT_USER` | anchor 유지/축제 도시 전환/중단 |
| festival lookup 자체 실패 | 없음 | 후속 후보 | option 제시형 또는 notice | `END_WAIT_USER` 또는 notice | AWS/데이터 오류와 사용자 선택지를 분리해야 함 |

필요 작업:

- `festival_none`에 `search_any_festival_theme` option을 추가한다.
- `memory.pending_clarification` 또는 동등한 checkpoint 상태에 option 원본을 보존한다.
- resume 시 `optionId`로 원본 option을 찾아 `then=rerun_discovery | anchor | abort`를 적용한다.

### 2.4 City Select

| case | reason_code | 상태 | 입력 유형 | 응답 | 비고 |
|---|---|---|---|---|---|
| preferred/disliked city filter 결과 후보 없음 | `no_candidate_city` | 후속 후보 | option 제시형 | `END_WAIT_USER` | 선호/비선호 도시 조건 완화 여부를 물을 수 있음 |
| anchor city identity를 찾지 못함 | `no_candidate_city` | 후속 후보 | 자유 입력형 | `END_WAIT_USER` | destinationId/name 재입력 후보 |
| city 후보는 있지만 theme coverage가 얇음 | `thin_city` | notice 유지 | 없음 | `modification_pending` | planner capacity risk로 내려보냄 |
| festival_gate.allowed_city_ids 누락 | 없음 | notice 유지 또는 error | 없음 | 내부 계약 위반 | 사용자 질문 대상 아님 |
| 일반 discovery 후보 없음 | 없음 | notice 유지 | 없음 | planner/response notice | 전국 pool 기준 실질 rare case |

이번 브랜치에서는 City Select clarification을 구현하지 않는다. 다만 preferred/disliked city filter가 강화되면 `no_candidate_city`는 후속 구현 후보로 둔다.

### 2.5 Planner: Generation

| case | reason_code | 상태 | 입력 유형 | 응답 | 비고 |
|---|---|---|---|---|---|
| 장소 후보 부족으로 일정 생성 실패/부분 생성 | `generation_insufficient_candidates` | 구현 완료 | option 제시형 | `END_WAIT_USER` | 테마 완화/다른 도시 탐색 option |
| required theme 일부가 0개 | 없음 | notice 유지 | 없음 | `modification_pending` | partial theme miss notice |
| route hard-leg/총 이동시간으로 trim 과다 | 없음 | notice 유지 | 없음 | `modification_pending` | 일정은 만들되 품질 notice |
| healing 등 sparse theme | `sparse_theme` 후보 | 후속 후보 | option 제시형 | `END_WAIT_USER` 가능 | hard theme 유지/완화 선택지가 필요할 수 있음 |
| direct anchor가 너무 얇음 | `thin_city` | 후속 후보 | option 제시형 | `END_WAIT_USER` 가능 | anchor 유지/조건 완화/도시 변경 |
| alternative city fallback 필요 | 없음 | 후속 후보 | option 제시형 | `END_WAIT_USER` 가능 | 자동 도시교체 대신 사용자 선택 방향 |

이번 브랜치에서는 planner가 `planner_status_gate=insufficient_candidates`를 반환하면 생성 결과가 일부 있더라도 사용자 선택을 받는다. 단순 city_select의 thin/risk 신호만으로는 멈추지 않는다.

### 2.6 Planner: Modify / Apply Edit

| case | reason_code | 상태 | 입력 유형 | 응답 | 비고 |
|---|---|---|---|---|---|
| slot replace target 없음 | `modify_target_unresolved` | 구현 완료 | 자유 입력형 | `END_WAIT_USER` | 현재 일정 기준 슬롯 재입력 |
| slot replace 후보 없음 | `slot_replace_no_candidate` | 구현 완료 | option 제시형 | `END_WAIT_USER` | 조건 완화/현재 장소 유지. 조건 완화는 `then=retry_slot_replace` |
| 후보는 있으나 affected day route 불가능 | `slot_replace_route_infeasible` | 구현 완료 | option 제시형 | `END_WAIT_USER` | 조건 완화/현재 장소 유지. 조건 완화는 `then=retry_slot_replace` |
| seed same-theme 후보가 없음 | `modify_seed_theme_conflict` | 구현 완료 | 자유 입력형 | `END_WAIT_USER` | 같은 테마 조건 재확인 |
| 다중 수정 중 일부 실패 | 없음 | notice 유지 | 없음 | `modification_pending` | 부분 적용 + 실패 슬롯 notice |
| query 없는 replace이고 reserve 없음 | `slot_replace_no_candidate` | 구현 완료 | option 제시형 | `END_WAIT_USER` | 현재는 재검색 후 실패 시 질문 |
| day regenerate | 없음 | 구현 완료 | 자유 입력형 | 별도 op | `1일차 전체 바꿔줘` baseline 구현. 실패 clarification은 후속 |
| planner edit resume 실행 | 없음 | 후속 후보 | option 제시형 | `then=planner_apply_edit` 필요 | 현재 `then=abort`까지만 |

현재 허용 범위:

- slot replace target을 찾지 못한 경우 `modify_target_unresolved`로 다시 요청한다.
- slot replace 후보가 없거나 route feasibility가 깨진 경우 `slot_replace_no_candidate` 또는 `slot_replace_route_infeasible`으로 조건 완화/현재 장소 유지 선택지를 제공한다.
- 조건 완화 option은 실패 op의 `condition.theme`을 제거하고 seed policy를 `theme_relaxed`로 바꾼 뒤 planner edit를 재시도한다.

### 2.7 Weather Alternative

| case | reason_code | 상태 | 입력 유형 | 응답 | 비고 |
|---|---|---|---|---|---|
| weather risk 높고 outdoor 비율 높음 | `weather_alternative_available` | 구현 완료 | option 제시형 | `END_WAIT_USER` | 대체 일정 보기/현재 일정 유지 option |
| weather map에 도시 없음 | 없음 | notice 유지 | 없음 | `modification_pending` | 판단 불가 notice |
| indoor/mixed 대체 후보 없음 또는 대체 동선 불가 | 없음 | 구현 완료 | option 선택 후 notice | `modification_pending` | primary 일정 유지 + 대체 불가 notice |
| low/medium risk | 없음 | notice 유지 | 없음 | `modification_pending` | 안내만 제공 |

현재 구현은 사용자가 `use_weather_alternative`를 고르면 그 시점에 실내/혼합 후보로 대체 일정을 생성한다. 대체 후보는 `indoor` 우선, 부족하면 `mixed`까지 사용하며, 변경된 day에 대해 travel-time provider로 hard-leg feasibility를 확인한다. ORS runtime이 있으면 ORS matrix를 사용하고, 후보 부족 또는 동선 불가면 primary 일정을 유지한다.

### 2.8 Response Packager / Entrypoint / Supervisor

| case | reason_code | 상태 | 입력 유형 | 응답 | 비고 |
|---|---|---|---|---|---|
| any structured clarification present | 기존 reason | 구현 완료 | option 제시형 또는 자유 입력형 | `END_WAIT_USER` | public `clarification` block + interrupt |
| stale interrupt 뒤 clarify 정정 입력 | 기존 reason | 구현 완료 | 자유 입력형 | 재생성 | 기존 interrupt를 정리하고 `entryType=clarify`의 정정 조건으로 생성 실행 |
| modify인데 checkpoint 없음/만료 | 없음 | 구현 완료 | 자유 입력형 | `END_WAIT_USER` 또는 notice | 새 일정 생성 안내. interrupt는 불필요 |
| resume optionId가 pending option에 없음 | `clarify_option_unresolved` | 후속 후보 | option 제시형 | `END_WAIT_USER` | 다시 선택 요청 |
| resume payload가 apply를 조작함 | 없음 | 구현 완료 | 없음 | 무시 | checkpoint 원본 option만 신뢰 |
| natural language clarification answer | 없음 | 후속 후보 | 자유 입력형 | `END_WAIT_USER` | resolver 필요 |

Response Packager는 text SSR surface를 책임진다. 모든 option은 `label`과 `helperText`를 포함해야 한다.

## 3. Resume 처리 범위

이번 브랜치에서 구현할 resume 처리:

1. `resume` 또는 `resumeValue`에서 선택된 `optionId`를 읽는다.
2. checkpoint state의 pending clarification에서 같은 `optionId`를 찾는다.
3. 사용자 payload의 `apply`는 신뢰하지 않는다.
4. option 원본의 `apply`와 `then`만 적용한다.

`then`별 처리:

| then | 처리 |
|---|---|
| `rerun_discovery` | `intent.city_select_input`에 patch를 반영하고 festival/city discovery 경로로 재진입 |
| `anchor` | `destination_id`를 반영하고 direct anchored planner 경로로 재진입 |
| `abort` | 실행하지 않고 조건 재입력 안내 response 반환 |
| `weather_alternative` | primary itinerary 기준으로 indoor/mixed 대체 일정을 생성하고 `modification_pending`으로 반환 |
| `retry_slot_replace` | 실패한 slot replace op의 테마 조건을 완화하고 planner edit 경로로 재진입 |

## 4. 구현 순서

1. Festival option completeness
   - `search_any_festival_theme` option 추가
   - festival clarification option 테스트 보강

2. Intent contradiction clarification
   - contradiction을 구조화 `Clarification` mapping으로 변환
   - supervisor/response packager가 intent clarification도 `END_WAIT_USER`로 보내는지 확인

3. Resume option resolver
   - checkpoint의 pending clarification에서 option 원본 복원
   - `rerun_discovery`, `anchor`, `abort` routing 테스트 추가

4. Modify clarification boundary cleanup
   - 현재 장소 유지 계열은 `then=abort`로 종료한다.
   - 조건 완화 계열은 `then=retry_slot_replace`로 planner edit를 재시도한다.

## 5. 수락 기준

- festival clarification 3종이 public response의 `clarification` block으로 노출된다.
- `festival_none`에는 `search_any_festival_theme` option이 포함된다.
- intent preference contradiction이 `END_WAIT_USER`로 멈춘다.
- resume payload가 `optionId`만 포함해도 checkpoint option 원본을 복원한다.
- 사용자 payload가 `apply`를 포함해도 서버는 무시한다.
- 모든 public option은 사용자가 선택 결과를 이해할 수 있도록 `label`과 `helperText`를 제공한다.
- modify slot replace clarification은 현재 장소 유지(`abort`)와 조건 완화 재시도(`retry_slot_replace`)를 구분한다.

## 5.1 진행 기록

### 2026-07-05 1차 구현

- `ClarificationApply`에 `active_required_themes`, `festival_theme_agnostic`을 추가하여 축제 재검색 시 테마 조건 완화를 명시할 수 있게 했다.
- `festival_none`에 `search_any_festival_theme` option을 추가했다.
- `festival_tentative`에도 안전한 `revise_conditions` abort option을 추가했다.
- `response_packager` interrupt resume 직후, public payload가 아니라 checkpoint에 있던 option 원본의 `apply/then`을 복원하도록 공통 resolver를 추가했다.
- `then=rerun_discovery | anchor`는 stale `festival_gate/city_select/planner/response`를 비우고 `intent.city_select_input`에 patch를 반영해 재진입한다.
- `then=abort`는 실행 재진입 없이 기존 `END_WAIT_USER` response에 `clarification_resume` audit을 남긴다.
- intent preference contradiction은 구조화된 `intent.clarification`으로 승격하고 supervisor가 `response_packager`로 보낸다.
- 명시 `entryType=clarify` payload도 `optionId`로 pending option의 `reason_code/apply/then`을 복원한다.

### 2026-07-05 2차 상태 정리

구현 완료로 보는 케이스:

| agent | 완료 케이스 | 입력 유형 | 확인 범위 |
|---|---|---|---|
| Intent | preference contradiction | 자유 입력형 | `END_WAIT_USER` 응답, helperText 노출, 같은 thread에서 `entryType=clarify` 정정 입력 재생성 |
| Festival Verifier | `festival_none` | option 제시형 | option 생성, `rerun_discovery/abort` resume |
| Festival Verifier | `festival_tentative` | option 제시형 | option 생성, `anchor/rerun_discovery/abort` resume |
| Festival Verifier | `anchor_festival_conflict` | option 제시형 | option 생성, `anchor/abort` resume |
| Planner Modify | slot target unresolved | 자유 입력형 | `END_WAIT_USER`, 슬롯 재입력 안내 |
| Planner Modify | slot candidate 없음 / route infeasible | option 제시형 | `END_WAIT_USER`, 조건 완화/현재 장소 유지 option, `broaden_replace_theme` 재시도 |
| Response Packager / Entrypoint | structured clarification interrupt | option 제시형 또는 자유 입력형 | public `clarification`, `helperText`, stale interrupt 뒤 clarify 정정 recovery |
| Planner Generation | `generation_insufficient_candidates` | option 제시형 | planner 후보 부족 시 테마 완화/다른 도시 탐색 resume |
| Planner Modify | `slot_replace_no_candidate`, `slot_replace_route_infeasible` | option 제시형 | `broaden_replace_theme` 선택 시 slot replace 재시도 |

남은 입력은 아래처럼 분리한다.

| 유형 | 남은 케이스 | 필요한 후속 |
|---|---|---|
| option 제시형 | city filter 결과 후보 없음 | 도시 조건 완화/선호 도시 무시/다른 도시 제안 option 설계 |
| option 제시형 | direct anchor thin city | anchor 유지/조건 완화/도시 변경 option 설계 |
| option 제시형 | modify target ambiguous | 후보 슬롯 선택 후 planner edit로 이어지는 `then=planner_apply_edit` |
| option 제시형 | resume optionId 불일치 | 다시 선택 요청용 `clarify_option_unresolved` |
| 자유 입력형 | underspecified 생성 입력 | 부족한 조건을 다시 쓰게 하는 intent 판정 |
| 자유 입력형 | out-of-scope region | 서비스 범위 안내와 재입력 유도 |
| 자유 입력형 | anchor city identity 없음 | destination name/id 재입력 |
| 자유 입력형 | natural language clarification answer | 기존 option으로 resolve하는 intent resolver |
| option 제시형 | day regenerate 실패 | route/candidate 실패 시 조건 완화 option 설계 |

## 6. 이번 범위에서 하지 않는 것

- 자연어 clarification answer resolver
- planner edit resume action
- day regenerate 실패 clarification
- city select clarification
- app mirror 반영

## 7. Live 검증 기록

### 2026-07-05 generation 후보 부족 clarification

입력: `docs/tasks/results/v2_intent_mocks/generation/v2_gen_06_healing_2d1n_live_payload.json`

초기 생성:

- 결과: `docs/tasks/results/v2_general_live_smoke/20260705T142012Z_gen-insufficient-relax-create.json`
- `clarificationReason=generation_insufficient_candidates`
- options:
  - `relax_generation_themes`
  - `search_other_city`

`relax_generation_themes` resume:

- 입력: `docs/tasks/results/v2_intent_mocks/clarify_generation_relax_theme.json`
- 결과: `docs/tasks/results/v2_general_live_smoke/20260705T142049Z_gen-insufficient-relax-resume.json`
- `destinationId=KR-47-230`, `destinationName=영천시`
- `dayCount=2`, `itemCount=4`
- `clarificationReason=null`

`search_other_city` resume:

- 입력: `docs/tasks/results/v2_intent_mocks/clarify_generation_search_other_city.json`
- 결과: `docs/tasks/results/v2_general_live_smoke/20260705T142211Z_gen-insufficient-other-resume.json`
- 기존 `KR-2-4/남동구`는 제외되고 `KR-33-2/단양군`으로 변경됨
- `dayCount=2`, `itemCount=2`
- 여전히 후보가 얇아 `clarificationReason=generation_insufficient_candidates`

해석:

- option resume과 city exclusion 적용은 동작한다.
- healing sparse theme는 다른 도시 탐색 후에도 다시 후보 부족이 될 수 있으므로, 반복 clarification 또는 sparse-theme notice 정책은 별도 개선 후보로 남긴다.

### 2026-07-05 slot replace live 확인

생성 기반:

- 입력: `docs/tasks/results/v2_intent_mocks/generation/v2_gen_02_coast_vibrant_2d1n_live_payload.json`
- 결과: `docs/tasks/results/v2_general_live_smoke/20260705T142338Z_slot-replace-create.json`
- `destinationId=KR-38-13`, `destinationName=여수시`, `itemCount=6`

seed slot replace:

- 입력: `docs/tasks/results/v2_intent_mocks/modify/v2_mod_live_seed_replace_gen02_with_query.json`
- 결과: `docs/tasks/results/v2_general_live_smoke/20260705T142413Z_slot-replace-seed-modify.json`
- `itemCount=5`, `clarificationReason=null`
- 첫 장소가 `거문도해수욕장`으로 변경됨

healing stress slot replace:

- 입력: `docs/tasks/results/v2_intent_mocks/modify/v2_mod_live_slot_replace_gen02_healing_stress.json`
- 결과: `docs/tasks/results/v2_general_live_smoke/20260705T142550Z_slot-replace-healing-stress.json`
- `itemCount=3`, `clarificationReason=null`
- 두 번째 슬롯이 `미평 봉화산 산림욕장`으로 교체됨

해석:

- live에서는 slot replace 성공 경로가 확인됐다.
- 이번 실행에서는 `slot_replace_no_candidate`가 재현되지 않아 broaden option live resume은 미확인이다.
- broaden option 자체는 focused test에서 `retry_slot_replace`와 theme relaxation state update로 검증한다.

### 2026-07-06 weather alternative resume 정리

- `keep_primary_itinerary`는 primary itinerary를 그대로 사용해 `modification_pending`으로 종료한다.
- `use_weather_alternative`는 option 선택 시점에 대체 일정을 생성한다. 미리 backup itinerary를 계산하지 않는다.
- 대체 후보는 `state.planner.modify_context.reserve_pool`을 우선 사용하고, 부족하면 같은 도시에서 `indoor/mixed` 후보를 추가 검색한다.
- `mixed` 후보는 `indoor`보다 후순위이며, 포함 시 사용자 notice에 실내외 혼합형임을 알린다.
- 변경된 day는 travel-time provider로 hard-leg feasibility를 확인한다. ORS runtime이 있으면 ORS `snap_places/matrix_minutes` 경로를 탄다.
- 후보 부족 또는 동선 불가 시에는 primary itinerary를 유지하고 대체 불가 notice를 붙인다.

검증:

- `tests/v2/test_weather_response_resume.py`
- `tests/v2/test_response_packager_node.py`
- `tests/v2/test_response_clarification.py`
- `tests/v2/test_weather_alternative.py`

### 2026-07-06 day regenerate baseline 정리

- `day_regenerate`는 더 이상 clarification 후속 후보가 아니라 planner modify baseline으로 구현됐다.
- 현재 범위는 한 일차 전체 변경이다.
- queryless 요청은 reserve pool을 먼저 쓰고, 부족하면 같은 도시 residual retrieval을 수행한다.
- query가 있으면 day-level replacement query로 재검색한다.
- 기존 일정의 content id와 modify history replacement id는 후보에서 제외한다.
- 선택된 후보는 medoid-first ordering과 hard-leg feasibility를 통과해야 한다.
- 비대상 day는 보존한다.
- 정상 서비스 modify는 같은 `threadId/sessionId`를 사용해 checkpoint state를 복원하는 것을 전제로 한다.
- checkpoint가 없거나 `planner_output.itinerary`가 비어도 `currentOrder`가 있으면 이를 fallback으로 사용해 빈 응답을 방지한다.

Live evidence:

- `docs/tasks/results/v2_general_live_smoke/20260705T181943Z_residual-dayregen-queryless.json`
  - `destinationId=KR-47-770`, `destinationName=영덕군`
  - day 1 regenerated
  - day 2 preserved
  - `dayCount=2`, `itemCount=6`

## 8. 남은 항목 우선순위

### 8.1 구현 중요도가 높은 항목

| 우선순위 | 항목 | 이유 | 예상 범위 |
|---|---|---|---|
| 1 | `resume optionId` 불일치 처리 | 잘못된 option 선택이나 만료된 UI payload가 들어오면 현재 사용자에게 명확히 다시 선택을 요청해야 한다. | response packager resume resolver + 테스트 |
| 2 | City Select `no_candidate_city` clarification | 선호/비선호 도시 필터가 강화된 상태라 후보 0건은 실제 사용자 입력 완화가 필요한 지점이다. | city_select 결과 판정 + option 설계 |
| 3 | direct anchor thin city clarification | 고정 도시가 얇은 경우 자동 대체보다 anchor 유지/조건 완화/도시 변경 선택이 필요하다. | planner generation gate + response option |
| 4 | sparse theme 정책 | `온천·휴양`처럼 데이터 희소 테마는 반복 후보 부족으로 이어진다. 사용자에게 theme 완화 여부를 명시해야 한다. | generation insufficient와 통합 가능 |
| 5 | natural language clarification answer resolver | button 기반 resume은 동작하지만, 자유 입력형 답변을 기존 option/action으로 해석하는 루프는 아직 없다. | intent resolver 후속 |

### 8.2 빠르게 처리 가능한 항목

| 우선순위 | 항목 | 이유 | 예상 범위 |
|---|---|---|---|
| 1 | `clarify_option_unresolved` 응답 | resolver에서 option 미일치 시 같은 clarification을 다시 보여주는 좁은 변경으로 닫을 수 있다. | response packager |
| 2 | day regenerate 실패 clarification | baseline action은 구현됐지만 실패 시 조건 완화/현재 day 유지 option은 아직 정교하지 않다. | planner modify clarification |
| 3 | slot replace 실패 broaden live 재현 | focused test는 있으나 live에서 `slot_replace_no_candidate` 재현 기록이 없다. | mock payload 조정 + smoke |
| 4 | anchor city identity 없음 문구 정리 | city identity map 기반으로 재입력 안내 문구와 helperText를 고정하면 된다. | intent/city_select boundary |

### 8.3 후순위로 둘 항목

| 항목 | 이유 |
|---|---|
| day regenerate 실패 clarification | baseline op는 구현됐고, 실패 시 option 설계만 후속이다. |
| modify target ambiguous slot 선택 | UI에서 후보 슬롯을 보여주고 선택 후 planner edit로 이어지는 계약이 더 필요하다. |
| out-of-scope region | scope detector와 intent policy가 먼저 정해져야 한다. |
| festival lookup 자체 실패 | AWS/데이터 오류와 사용자 선택 가능 상태를 분리해야 해서 단순 clarification보다 운영 오류 처리에 가깝다. |
