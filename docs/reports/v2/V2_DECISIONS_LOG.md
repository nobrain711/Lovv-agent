# V2 설계 결정 로그 (Step 4)

> `V2_SCENARIO_CONCRETE.md`/`..._ARCH_IMPACT_MAP.md`가 건 정책·계약 결정을 하나씩 확정해 기록.
> 상태: ✅ 확정 · ⏳ 대기 · 표기일 2026-06-28.

## 이미 확정(이전 세션)
- ✅ **테마 게이트 = soft**(부분 충족 허용, 미충족 강한 감점; 누락 테마 audit/userNotice 후보).
- ✅ **capacity 결합 제거**(candidate_sufficiency 삭제, 항상 rank 0, insufficient는 Planner In-city Itinerary로).
- ✅ **수정 재인출 = S3 Vectors**(캐시 vector + top_k, 좌표·메타는 vector metadata).
- ✅ **데이터 4종 적재**(세부타입·indoor/outdoor·도시월 기상·visitor stats).
- ✅ **이동수단 거친 구분 채택**(자동차/뚜벅이, 거친 soft 신호).

## Step 4 결정
### ✅ D-A · 출력 스키마 / Plan B  (2026-06-28, on-demand로 확정)
**결정**: `alternativeItinerary`를 공식 응답 필드로 **두되, 미리 자동 생성하지 않는다(on-demand)**. 날씨 임계 초과 시 primary 일정 + **`weatherNotice`**("비가 잦아요 — 실내 위주 대안 만들어드릴까요?")를 반환하고, **사용자가 원하면(동의/"실내로") 수정 루프로 실내 대안을 생성**해 `alternativeItinerary`를 채운다.
**파급**:
- 응답 스키마에 `alternativeItinerary`(nullable) + `weatherNotice`(발동 사유) 추가. 평상시/미발동 = null.
- **Plan B 생성 경로 = 수정 루프**(SC-M4 날씨 악화→실내와 동일) → 별도 자동 생성 모드 없음 = 비용·복잡도↓.
- **D-J = `weatherNotice` 발동 임계**(Plan B 자동 생성 임계가 아님).
- 전제: indoor/outdoor 태깅 + 도시·월 기상(적재됨).

### ✅ D-B · 수정 처리 범위  (2026-06-28)
**결정**: 1차 = **비-seed 슬롯 교체**, 그 교체 요청에 **슬롯 단위 자연어 조건(무드·타입·위치 = 추가 query) 포함**(SC-03). 즉 "무드"는 *전체 재구성*이 아니라 *교체 슬롯에 거는 조건*으로 받는다.
- **확장(백로그)**: 전체 무드 재구성, 일정 길이 변경, 날짜/월 변경, 맥락 변화 후 재요청, 4d3n, 복합 변경.
- **도시 변경**: city_select 재실행 **경로만 설계**(1차 미포함).
**파급**: Planner 수정 모드는 슬롯 단위 재인출(S3 Vector)로 완결. city_select 되감기는 도시 변경 확장 시에만.
### ✅ D-K · 프로필 fallback / write  (2026-06-28)
**결정**: profile은 **"저장 확인된 일정"에서만** 구성한다.
- **write(쓰기)**: 사용자가 일정을 **저장(확정)**할 때, 그 저장된 일정 정보(테마·선택 장소 등)에서 theme_weights를 집계해 profile에 반영. **수정 중간 발화·단발 신호는 장기 profile에 직접 누적하지 않음**(저장된 완성 일정만 학습 → 변덕 방지).
- **read/fallback "충분" 기준**: **저장 일정 수 ≥ n**(또는 profile에 '반영 횟수' 카운터 별도 저장). 충분하면 모호 입력을 profile로 자동 채움(추천 이유에 "이전 선호 기반" 명시), 부족하면 되묻기.
- n 값은 추후 튜닝(초안 2~3).
**파급**: **"일정 저장" 이벤트**가 profile write 트리거 → front에서 저장 신호 필요(신규 의존). `LovvUserProfile`에 `saved_trip_count`(=trip_count 명확화)·집계 theme_weights. 저장 일정 evidence 보강은 `src/lovv_agent_v2/agents/profile/rds_mysql_tool.py`와 `app/LovvAgentV2/lovv_agent_v2/agents/profile/rds_mysql_tool.py`에 동일하게 존재하지만, 운영 사용 전 RDS 연결 설정, Secrets/IAM/VPC 배선, 호출 owner 연결이 필요하다.

### ✅ D-E · 이동수단 신호 (transport_pref)  (2026-06-28)
**결정**: `transport_pref = walk / car / unknown` 3값(거친 soft 신호). **walk → 슬롯 간 거리 페널티 강화(도보 집약)**, **car → 완화**, **unknown → 기본**. 역·터미널 라우팅은 아님. 이 값은 request field가 아니라 Intent LLM이 `raw_query`에서 파싱해 `CitySelectInput`/`PlannerIntent`에 기록한다.

### ✅ D-J · weatherNotice 발동 임계  (2026-06-28)
**결정 (방식 확정 · 수치 추후)**: 기온은 **기상청 특보 기준 차용**(폭염 일최고 33℃ / 한파 일최저 -12℃), 강수는 **월 강수량 → 일평균(mm/day) 환산** 절대 구간 + **연평균 대비 2배** 상대 보정. 임계 초과 시 `weatherNotice` 발동(D-A의 on-demand Plan B 트리거).
- **임계 숫자(10/6/3 mm·day, 33/-12℃ 등)는 구현·데이터 보고 후 튜닝**.

### ✅ 4d3n 정책  (2026-06-28)
**결정**: V2.0은 **짧은 일정(daytrip·2d1n·3d2n) 품질을 먼저 확인**한다. 4d3n+ 는 그 효과 확인 후 **확장**(1차 품질 보장 범위 밖, 백로그). 요청 시 응답은 하되 userNotice로 한계 고지.

### ◐ D-C · move / 동선  (2026-06-28, 부분 확정)
- **출력 move**: **front가 장소 간 이동시간을 제공** → 에이전트는 출력에 move를 새로 채우지 않음(front 담당, 중복 회피).
- **배치 동선(Planner)**: V2.0 1차 = **haversine geo_penalty**(내부, 무 API). **front의 이동시간 API를 배치 스코어링에 사용할지는 ⏳ 검토 중**(쓰면 동선 정확도↑, API 호출 비용·지연↑).

### ✅ 되묻기 경계 (모순/긴서사)  (2026-06-28)
**결정**: **모순 입력은 무조건 되묻기**(`needs_clarification`) — 창의적 절충 생성 안 함(엉뚱한 결과 차단). 긴서사는 핵심 키워드 추출 후 진행(별개). 짧은 NL도 되묻기(SC-I1, 기확정).

### ✅ 기피 재생성 (전면 불만)  (2026-06-28)
**결정**: "다 별로야" 같은 전면 불만 시 기존 도시/테마를 **세션 avoid**로 설정 → **그 세션이 끝날 때(TTL)까지 계속 제외**하고 차순위로 재생성. **영구 profile에는 쓰지 않음**(세션 한정).

### ✅ 응답상태 확장  (2026-06-28)
**결정**: 기존 `completed` / `END_WAIT_USER` + **`modification_pending`**(수정 완료 + 다음 수정 입력 대기 = interrupt 상태) **1개만 추가**. 풀세트(rejected/modified_completed 등 세분화)는 안 감(front 상태 매핑 최소화).

### ✅ 다건 동시 수정 (배치 편집)  (2026-06-28)
**결정**: 한 입력의 복수 편집을 `edit_ops` 리스트로 분해 → 각 비-seed 슬롯 교체 → **일괄 재인출 후 단일 재배치**(순차 금지). op 간/슬롯 내 모순 → 되묻기. seed·≤3 불변. C4에 흡수.
- **부분 실패 = 부분 적용 + 안내**: 성공 op는 반영, 실패(no_candidate) 슬롯은 유지하고 `userNotice`로 고지. 상태 = `modification_pending`.

### ✅ 수정 출력 스키마 (Modify I/O)  (2026-06-28)
**결정**: 수정은 **checkpoint state에서 resume**해 출발(1차 — 전체 재적재 비효율 허용, 재인출은 슬롯 단위만). 응답 itinerary = **전체(full) + `modification.changed_slots` 요약**(diff 반환 안 함). 다건 **전체 실패 = `modification_pending` + 원본 유지 + notice**. 정본 = `V2_11_MODIFY_IO_CONTRACT.md`.

### ✅ front 드래그앤드롭 / itinerary 배열 소유  (2026-06-28)
**결정**: front가 드래그앤드롭으로 순서·위치를 바꾸므로 — **순서·위치 재배열(REORDER/MOVE) = front 담당**(에이전트 modify 범위 영구 제외, move=front 연장). 수정 시 **itinerary 배열 출처 = front가 현재 일정 동봉(우선), 미동봉 시 checkpoint fallback**. 즉 배열=front, 내용 생성=에이전트.

### ✅ Festival gate / tentative 처리 / clarification 계약  (2026-06-30)
**결정**: Festival은 city_select 앞단 게이트이며 도시 랭킹 보너스가 아니다. `include_festivals=true`면 Festival Verifier가 월·도시·날짜 상태를 먼저 검증하고, confirmed 축제 도시만 `allowed_city_ids`로 city_select에 넘긴다. `tentative`는 자동 진행하지 않고 반드시 `festival_tentative` clarification으로 사용자 확인을 받는다. `outdated`·`unknown`·`skipped`는 제외한다.
**응답 규칙**: Festival Verifier status는 `ok | needs_clarification`만 사용한다. 후보 없음/충돌/미확정은 `status=no_candidate`가 아니라 `needs_clarification + reason_code`로 표현한다. clarification option은 stable `option_id`, resume patch인 `apply`, 재진입 경로인 `then(anchor|rerun_discovery|abort)`를 포함한다.
**정본**: `V2_21_FESTIVAL_DIRECTIVE.md`.

### ✅ Response clarification additive 확장  (2026-06-30)
**결정**: public response는 기존 recommendation response 1종을 유지한다. `completed`/`END_WAIT_USER` 구분은 기존처럼 `ServingState.response_status`가 맡고, V2 clarification은 top-level optional `clarification` block으로만 추가한다. 기존 `explainability.userNotice`는 유지하며, `END_WAIT_USER`에서는 `clarification.prompt`와 같은 문구를 넣어 기존 소비자와 호환한다.
**응답 규칙**: public response는 camelCase를 쓴다. 내부 node 계약이 snake_case를 쓰더라도 Packager가 `reason_code→reasonCode`, `option_id→optionId`, `include_festivals→includeFestivals`로 변환한다. Resume은 1차로 `selectedOptionId`를 받아 checkpoint의 원본 option에서 `apply`와 `then`을 복원한다.
**정본**: `V2_22_RESPONSE_CLARIFICATION_DIRECTIVE.md`.

### ✅ V2 Canonical State / legacy CandidateEvidence 제거  (2026-06-30)
**결정**: V2 중앙 계약은 `core/state.py::UnifiedAgentState`이며 top-level group은 `request`, `intent`, `profile`, `festival_gate`, `city_select`, `planner`, `response`, `routing`, `memory`, `trace`로 고정한다. `CandidateEvidenceInput`, `CandidateEvidencePackage`, `CandidateReasonClaim`, `candidate_evidence_input`, `candidate_evidence_package`는 V2 state/API 정본으로 사용하지 않는다.
**응답 규칙**: City Select 입력은 `state.intent.city_select_input`, 출력은 `state.city_select.city_selection_result`에 둔다. Festival은 `state.festival_gate`, Packager는 `state.response`를 소유한다. 과거 포팅 문서의 `CandidateEvidence*` 표현은 legacy 제거 대상 또는 baseline 설명으로만 해석한다.
**정본**: `V2_23_STATE_CONTRACT_DIRECTIVE.md`.

### ✅ Weather 기반 alternative itinerary  (2026-07-01)
**결정**: `city_monthly_weather_risks.json`은 primary itinerary를 바꾸는 city_select ranking 요소가 아니라, planner 후단의 weather notice 및 optional `alternative_itinerary` 생성 trigger로 사용한다. Lookup key는 `(selected_city_id, travel_month)`이며, risk row가 없으면 실패하지 않고 notice/alternative 없이 진행한다.
**응답 규칙**: `alternative_itinerary`는 기본 일정의 자동 대체가 아니라 weather-sensitive outdoor/mixed non-seed slot에 대한 backup proposal이다. 사용자는 primary itinerary를 그대로 받고, weather risk가 높을 때만 평년 기준 weather notice와 대체 후보를 함께 본다. live forecast처럼 표현하지 않는다.
**정본**: `V2_32_ALTERNATIVE_ITINERARY_WEATHER_DIRECTIVE.md`.

### ✅ Intent 입출력 소유 경계 / modify 계약  (2026-07-02)
**결정**: 프론트는 request facts와 사용자 원문을 보내고, Intent는 자연어 신호와 clarification/modify intent만 해석한다. API-owned field(`country`, `travelMonth`, `travelYear`, `tripType`, `includeFestivals`, `destinationId`, `userLocation`)는 LLM이 사실상 재결정하지 않으며, 충돌 시 request 값을 우선한다.
**응답 규칙**: `entryType`은 `create`, `clarify`, `modify`, `confirm`으로 분기한다. `modify`에서 프론트는 `editOps`를 보내지 않고, Intent가 checkpoint/current itinerary를 기준으로 `slot_replace` 또는 `city_change`를 만들어 Supervisor/Planner에 넘긴다. `city_key`, `ddb_pk`, profile weight, place candidates, route legs는 Intent 소유가 아니다.
**정본**: `V2_34_MODIFY_INTENT_SCHEMA.md`, `V2_38_INTENT_FRONTEND_INPUT_CONTRACT.md`, `V2_39_INTENT_PROCESSING_OUTPUT_SCHEMA.md`.

---

## 전체 확정 요약 (Step 4 완료 · 2026-06-28)
| ID | 결정(요약) |
|---|---|
| **D-A** | `alternativeItinerary` 필드 두되 **on-demand** — weatherNotice 후 사용자 동의 시 **수정 루프로** 실내 대안 생성 |
| **D-B** | 1차 = **슬롯 교체 + 슬롯 단위 조건(무드/타입/위치)**. 도시 변경 = 경로만 설계. 길이/날짜/전체무드/맥락변화/4d3n = 백로그 |
| **D-K** | profile = **저장 확인된 일정에서만** write. 모호 fallback = **저장 수 ≥ n**. 수정 발화는 장기 누적 안 함 |
| **D-C** | 출력 move = **front 담당**(미채움). 배치 = **haversine geo_penalty 1차**, 실이동 API 사용은 ⏳ 검토 |
| **D-E** | `transport_pref` = **walk/car/unknown**(거친 soft). walk=거리 페널티↑, car=완화 |
| **D-J** | 방식 확정(기온 KMA 33/-12 + 강수 일평균·상대 2배), **임계 수치는 추후 튜닝** |
| **4d3n** | **짧은 일정(≤3d2n) 먼저** 품질 확인 → 4d3n+ 확장(백로그) |
| **응답상태** | +`modification_pending` 1개 |
| **되묻기** | 모순 = **무조건 되묻기**. 긴서사 = 핵심 추출 진행 |
| **기피** | 전면 불만 → **세션 avoid(세션 끝까지 제외)**, 영구 profile 아님 |
| **수정 출력** | checkpoint resume서 출발 · itinerary **전체(full)+changes** · 전체실패=원본유지 (→ `V2_11`) |
| **front 드래그** | 순서·위치 재배열=**front**(에이전트 제외, 단 끌어오면 결정론 저비용) · 수정 시 itinerary=front 동봉(우선)/checkpoint(fallback) · **front 동봉본에 seed 표시 포함**(합의) |
| (기확정) | soft 테마 게이트 · capacity 제거 · 수정 재인출 S3 Vector · 데이터 4종 적재 · 이동수단 채택 |

**남은 미정/검토(구체화 단계로)**: D-J 임계 수치 · D-C 실이동 API 사용 여부 · 4d3n 확장 시점 · profile fallback n값 · 축제 테마 정합 필터(데이터 전제). *(수정 응답 반환 방식 → full+changes로 확정, `V2_11`)*
