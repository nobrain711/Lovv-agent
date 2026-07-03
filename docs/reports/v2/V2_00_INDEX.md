# V2 작업 인덱스 · 공유 진입점

> 범위: 2026-06-28 브레인스토밍부터 만든 V2 문서. 그 이전 문서(`docs/reports/`의 ARCHITECTURE_DECISIONS·SCENARIO_MATRIX·발표덱)는 그대로 둠.
> **팀 공유는 이 문서 하나만 보내면 됨** — 아래 깊이 가이드대로 읽으면 구조→변경→대응→검증 순서로 따라간다.

## 파일 맵 (`docs/reports/v2/`)
| 번호 | 파일 | 내용 |
|---|---|---|
| 00 | `V2_00_INDEX.md` | (이 문서) 진입점 · 공유 가이드 |
| 01 | `V2_01_SCENARIO_BRAINSTORM_CONSOLIDATED.md` | 3개 모델 발산 통합 + 스코프 결정 |
| 02 | `V2_02_SCENARIO_INSCOPE.md` | 범위 밖 제거, V2 대응 시나리오 집합 |
| 03 | `V2_03_SCENARIO_ARCH_IMPACT_MAP.md` | 시나리오 → 노드/계약/출력/결정 매핑(Step 3) |
| 04 | `V2_04_SCENARIO_CONCRETE.md` | 구체화(SC-00~M4, [V1·고도화]+[V2·신규]) |
| ~~05~~ | — | *CONCRETE_SAMPLES(구체화 초안) → **04에 흡수, 삭제됨*** |
| ~~06~~ | — | *BRAINSTORM_INPUT_BRIEF 예약 자리 → **미사용*** |
| 07 | `V2_07_ARCHITECTURE_FINAL.md` | **확정 아키텍처 델타 + 우선순위(P0/P1/P2, thin slice)** |
| 08 | `V2_08_SCENARIO_COVERAGE.md` | 확정 구조가 시나리오를 어떻게 커버하나(설명용) |
| 09 | `V2_09_INTENT_PARSING_SPEC.md` | Intent 파싱 기준(생성/수정·공통/전용) + 검증 부록 |
| 10 | `V2_10_VERIFICATION_PLAN.md` | 아키텍처 전반 검증 계획 + 계측 선결 |
| 11 | `V2_11_MODIFY_IO_CONTRACT.md` | 수정 I/O 계약(ModifyResult 입력 · 수정 응답 출력 스키마) |
| 12 | `V2_12_DIRECTORY_STRUCTURE.md` | V2 디렉토리 구조(수정본: infra 계층·memory·포팅 맵) |
| 13 | `V2_13_PORTING_HANDOFF.md` | V1→lovv_agent_v2 포팅 핸드오프(순서·매핑·import 규칙·분해) |
| 14 | `V2_14_RETRIEVAL_ANALYSIS_BRIEF.md` | retrieval_smoke 결과 분석 지시서(분석 에이전트용) |
| 16 | `V2_16_CITY_MONTHLY_WEATHER_RISK.md` | 월별 평년 기후 기반 city weather risk table 산출 근거 |
| 17 | `V2_17_PROFILE_THEME_PERSONAS.md` | profile theme_weights 튜닝용 synthetic persona fixture |
| 18 | `V2_18_FESTIVAL_HANDLING.md` | 축제 처리 설계 초안(일부 결정은 21이 supersede) |
| 20 | `V2_20_MASTER_HANDOFF.md` | V2 현상태 master handoff + 다음 작업 큐 |
| 21 | `V2_21_FESTIVAL_DIRECTIVE.md` | **Festival 중앙 결정 + city_select/festival/planner/packager 세션별 지시서** |
| 22 | `V2_22_PROFILE_CONFIG.md` | **Profile Agent theme-weight config + runtime source/RDS evidence 경계** |
| 22 | `V2_22_RESPONSE_CLARIFICATION_DIRECTIVE.md` | **기존 recommendation response 유지 + optional clarification block 확장 지시서** |
| 23 | `V2_23_STATE_CONTRACT_DIRECTIVE.md` | **V2 Canonical UnifiedAgentState 계약 + legacy CandidateEvidence 제거 지시서** |
| 32 | `V2_32_ALTERNATIVE_ITINERARY_WEATHER_DIRECTIVE.md` | **월별 weather risk 기반 alternative itinerary 지시서** |
| 32 | `V2_32_CITY_SELECT_SCORING_LEGACY_AUDIT.md` | **city_select 스코어링 V1 legacy 감사와 제거/유지 판단** |
| 33 | `V2_33_SCORING_DATADRIVEN_RATIONALE.md` | **city_select/planner 점수식 도달 과정과 남은 한계** |
| 34 | `V2_34_MODIFY_INTENT_SCHEMA.md` | **수정 Intent Agent 출력 스키마(slot_replace/city_change/backlog + seed same-theme 정책)** |
| 35 | `V2_35_ROUTE_DAYS_EXPLANATION.md` | **Planner route_days 일자 배치 알고리즘 + smoke 사례 설명** |
| 36 | `V2_36_INTERRUPT_HANDLING_MATRIX.md` | **interrupt option/apply/then 처리 matrix와 수락 기준** |
| 38 | `V2_38_INTENT_FRONTEND_INPUT_CONTRACT.md` | **Frontend → Intent 입력 계약(create/clarify/modify/confirm + request-owned field 경계)** |
| 39 | `V2_39_INTENT_PROCESSING_OUTPUT_SCHEMA.md` | **Intent 처리/출력 state 계약(entryType dispatch + downstream owner 경계)** |
| — | `V2_DECISIONS_LOG.md` | Step 4 결정 로그(왜 그렇게 정했나) |
| — | `../../tasks/results/v2_intent_mocks/` | V2 입력 mock(생성14·수정4) + 핸드오프 |

> **번호 05·06 공백은 의도된 것**: 05는 04에 흡수, 06은 예약만 하고 미사용. 07~10은 그대로 둔다(재번호 시 상호참조·다이어그램 깨짐 방지).

## 다이어그램 (`docs/reports/`)
- `V2_ARCHITECTURE_STRUCTURE_final.svg` / `.png` — 확정본 반영(soft 게이트·capacity 제거·seed-only·on-demand Plan B·출력 스키마·배치 편집·세션 avoid). *PNG는 출력 폴더에 있으면 이 위치로 옮겨둘 것.*

---

## 공유 가이드 — 깊이 3단
- **1분(전원)**: 다이어그램 PNG + `08` §0·§5. "뭘 만드나 / V2.0에 뭐가 보이나".
- **확정 검토(설계 참여자)**: `07`(델타+우선순위) + `V2_DECISIONS_LOG`(근거).
- **구현 착수(담당)**: `09`(Intent 파싱) + `22_PROFILE`(Profile config/source) + `34`/`38`/`39`(최신 Intent 입출력 계약) + `10`(검증·계측).

### 미팅 읽는 순서
다이어그램 → `08`(위→아래로 시나리오 대응) → `07`(변경점·우선순위) → 열린 항목 결정.

### 미팅에서 받아낼 것
1. **우선순위/thin slice 동의** — `F1·F2·F3 → C1~C4·W1` 먼저, 나머지 V2.1 (`07` §2).
2. **열린 경계 3개** — 쿼리 임베딩 위치 · tripType 결측 기본값 · transport 수정 적용 (`09` 부록 B).
3. **front 협의** — 출력 스키마 3종 + "저장 이벤트" 신호 + move는 front 담당 (`07` 데이터 계약).

---

## 진행 상태
- ✅ Step 1~3 시나리오(발산→인스코프→영향 매핑) + 구체화(04)
- ✅ Step 4 정책·계약 결정 10건 (`V2_DECISIONS_LOG`)
- ✅ Step 5 아키텍처 확정 + 우선순위(`07`) · 커버리지(`08`) · Intent 파싱(`09`) · 검증 계획(`10`) · 다이어그램
- ✅ 2026-07-02 Intent 계약 갱신 반영: 수정 intent 출력(`34`) · front 입력(`38`) · intent 처리/출력 state(`39`)
- ✅ 2026-07-03 Profile RDS evidence tool 상태 반영: `src/`와 `app/LovvAgentV2/` 파일 parity 있음, runtime RDS 배선 미완료
- ▶ **다음**: `10` §0 계측(로깅+사유 enum) → thin slice 코드 착수(F3 수정 루프부터)
