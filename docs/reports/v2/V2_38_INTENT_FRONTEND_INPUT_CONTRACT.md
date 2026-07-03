# V2_38 — Frontend To Intent Input Contract

작성일: 2026-07-02

상태: 현재 구현 기준 초안

관련 문서:

- `V2_34_MODIFY_INTENT_SCHEMA.md`
- `V2_36_INTERRUPT_HANDLING_MATRIX.md`
- `V2_39_INTENT_PROCESSING_OUTPUT_SCHEMA.md`

---

## 0. 목적

이 문서는 프론트가 V2 intent 경로로 어떤 입력을 보내야 하는지 정리한다.

현재 `src/lovv_agent_v2/agents/intent/` 구현은 다음 두 경로를 지원한다.

1. `request`에서 deterministic 필드를 읽고 `CitySelectInput`을 만든다.
2. `intent_prompt_runtime`이 주입된 경우, LLM structured output으로 raw query의 preference/soft/transport/congestion 값을 보강한다.

Intent는 도시 label, `city_key`, `ddb_pk` 매핑을 프론트에 요구하지 않는다. 프론트가 보내는 도시 식별자는 `destinationId` 하나로 제한한다.

---

## 1. Create Request

프론트는 초회 생성 요청에서 아래 shape를 보낸다.

```json
{
  "entryType": "create",
  "requestId": "req-001",
  "rawQuery": "경주 말고 조용한 바다 쪽으로 1박 2일 가고 싶어.",
  "country": "KR",
  "travelMonth": 7,
  "travelYear": 2026,
  "tripType": "2d1n",
  "activeRequiredThemes": ["바다·해안"],
  "includeFestivals": false,
  "destinationId": null,
  "executionMode": "city_discovery",
  "userLocation": null
}
```

### Required Fields

| frontend field | internal key | owner | note |
|---|---|---|---|
| `country` | `country` | frontend/API | 현재 V2는 `KR`만 실사용 범위 |
| `travelMonth` | `travel_month` | frontend/API | 1-12 |
| `travelYear` | `travel_year` | frontend/API | 예: `2026` |
| `tripType` | `trip_type` | frontend/API | `daytrip`, `2d1n` 등 planner 지원값 |
| `includeFestivals` | `include_festivals` | frontend/API | 축제 포함 여부 |

### User Text Fields

| frontend field | internal key | owner | note |
|---|---|---|---|
| `rawQuery` | `raw_query` | user/frontend | intent parser의 기준 문장 |
| `softPreferenceQuery` | `soft_preference_query` | optional | 없으면 intent가 빈 문자열 또는 prompt 결과로 보강 |

`rawQuery`는 선호/비선호 테마, 지역 선호/비선호, 혼잡 선호, 이동 선호를 담을 수 있다.

현재 code parser가 직접 추출하는 항목:

- `preferred_theme_ids`
- `disliked_theme_ids`
- `preferred_region_ids`
- `disliked_region_ids`
- `preferred_region_spans`
- `disliked_region_spans`
- `unresolved_region_spans`
- `contradiction_reasons`

`preferred_region_ids` / `disliked_region_ids`는 legacy field name을 유지하지만 값은 V2 `city_id` 형식의 `KR-*`만 담는다. LLM은 city id를 생성하지 않고 `preferred_region_spans` / `disliked_region_spans` 같은 짧은 원문 지역명만 보조 추출한다. backend는 city identity map으로 span을 canonicalize하며, `동구 (대구광역시)` 같은 qualifier와 `시/군/구` suffix를 처리한다. 매칭 실패나 단독 `동구`처럼 ambiguous한 span은 id로 승격하지 않고 `unresolved_region_spans`에 둔다.

prompt runtime이 있을 때 보강되는 항목:

- `soft_preference_query`
- `transport_pref`
- `congestion_pref`
- `unsupported_conditions`

---

## 2. Theme Input

프론트는 테마를 Korean label 배열로 보낸다.

```json
{
  "activeRequiredThemes": ["바다·해안", "역사·전통"]
}
```

허용 label은 현재 V2 테마 6종이다.

| label | canonical id |
|---|---|
| `바다·해안` | `sea_coast` |
| `자연·트레킹` | `nature_trekking` |
| `역사·전통` | `history_tradition` |
| `예술·감성` | `art_sense` |
| `온천·휴양` | `healing_rest` |
| `미식·노포` | `food_local` |

Intent parser는 raw query에서 선호 테마 id를 찾으면 label로 변환해 `active_required_themes`에 반영할 수 있다. 명시 테마가 없거나 parser가 추출하지 못하면 request의 `activeRequiredThemes` 값을 사용한다.

---

## 3. Destination Input

프론트는 목적 도시가 정해진 경우 `destinationId`만 보낸다.

```json
{
  "destinationId": "KR-47-130",
  "executionMode": "anchored_place_search"
}
```

규칙:

- `destinationId`는 Dynamo city_id 형식이다.
- `cityKey`, `ddbPk`, 도시 label은 프론트 필수 입력이 아니다.
- intent 이후 `enrich_city_select_identity()`가 내부 map으로 `city_key`와 `ddb_pk`를 채운다.
- 현재 구현은 `executionMode`를 request에서 읽고, 없으면 `city_discovery`로 기본값을 둔다. 따라서 anchored 생성 요청은 프론트가 `executionMode=anchored_place_search`를 함께 보내야 한다.

목표 상태에서는 `destinationId != null`이면 backend가 `anchored_place_search`를 deterministic하게 유도하는 것이 더 안전하다.

---

## 4. Clarification Answer Input

`END_WAIT_USER` 응답 이후 프론트는 가능하면 서버가 준 `optionId`를 그대로 보낸다.

```json
{
  "entryType": "clarify",
  "threadId": "thread-001",
  "selectedOptionId": "continue_without_festival"
}
```

자연어 답변도 허용할 수 있지만, 현재 intent 구현에는 pending option resolver가 아직 없다.

```json
{
  "entryType": "clarify",
  "threadId": "thread-001",
  "rawQuery": "축제 빼고 계속해줘"
}
```

필요한 후속 구현:

- checkpoint에서 pending clarification options를 읽는다.
- 자연어 답변을 기존 option 중 하나로 resolve한다.
- 새 option을 만들지 않는다.
- resolve 실패 시 다시 묻거나 abort 안내를 반환한다.

---

## 5. Modify Request Input

일정 수정은 초회 생성 완료 후 같은 `threadId`로 들어온다.

```json
{
  "entryType": "modify",
  "threadId": "thread-001",
  "itineraryRevision": "rev-001",
  "rawModifyQuery": "1일차 오후 장소를 조용한 산책지로 바꿔줘."
}
```

프론트는 `editOps`를 직접 만들지 않는다. `V2_34_MODIFY_INTENT_SCHEMA.md` 기준의 `edit_ops`는 modify intent가 생성한다.

현재 구현 상태:

- `modify_parser.parse_modify_query()`는 아직 `parse_initial_query()` wrapper다.
- 실제 `slot_replace`, `city_change` op 생성은 후속 구현 대상이다.

---

## 6. Confirm Request Input

사용자가 일정을 저장 확정하면 confirm event를 보낸다.

```json
{
  "entryType": "confirm",
  "threadId": "thread-001",
  "recommendationId": "rec-001",
  "itineraryRevision": "rev-001"
}
```

Confirm은 planner 수정이 아니라 profile update path로 들어간다.

---

## 7. Frontend Must Not Send

프론트는 아래 값을 직접 구성하지 않는다.

| field | reason |
|---|---|
| `editOps` | modify intent가 생성 |
| `cityKey` | backend city identity map이 생성 |
| `ddbPk` | backend city identity map이 생성 |
| `themeWeights` | profile agent가 생성 |
| `apply` | clarification option 생성 시 서버가 확정 |
| `then` | clarification option 생성 시 서버가 확정 |

---

## 8. Current Implementation Gaps

| gap | current behavior | target |
|---|---|---|
| intent contradiction interrupt | state에 `needs_clarification`, `contradiction_reasons`만 보존 | `Clarification` + `END_WAIT_USER` 승격 |
| underspecified input | 미지원 | abort-only clarification |
| out-of-scope region | 미지원 | KR 범위 안내 clarification |
| natural-language clarification answer | 미지원 | pending option resolver |
| modify op extraction | preference parser wrapper 수준 | `slot_replace` / `city_change` schema 생성 |
| anchored mode derivation | request `executionMode` 의존 | `destinationId` 기반 deterministic derivation |
