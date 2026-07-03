# V2_39 — Intent Processing And Output Schema

작성일: 2026-07-02

상태: 현재 구현 기준 + 후속 구현 계약

관련 문서:

- `V2_34_MODIFY_INTENT_SCHEMA.md`
- `V2_36_INTERRUPT_HANDLING_MATRIX.md`
- `V2_38_INTENT_FRONTEND_INPUT_CONTRACT.md`

---

## 0. 목적

이 문서는 Intent Agent가 프론트 입력을 어떻게 처리하고, downstream graph에 어떤 출력 state를 남겨야 하는지 정의한다.

핵심 원칙:

- 프론트는 request facts를 보낸다.
- Intent는 자연어에서 선호/비선호, 혼잡/이동 성향, clarification/modify intent를 해석한다.
- Profile weight, city identity mapping, Dynamo PK, planner edit execution은 Intent가 만들지 않는다.

---

## 1. Intent Dispatch

Intent는 request의 `entryType` 또는 동등한 내부 discriminator로 먼저 분기한다.

| entryType | 의미 | Intent output | 다음 owner |
|---|---|---|---|
| `create` 또는 missing | 초회 일정 생성 | `CreateIntentOutput` | Profile -> Supervisor |
| `clarify` | pending clarification 답변 | `ClarifyIntentOutput` | Resume/Supervisor |
| `modify` | 기존 일정 수정 | `ModifyIntentOutput` | Supervisor/Planner |
| `confirm` | 일정 저장 확정 | `ConfirmIntentOutput` | Profile |

현재 코드의 `intent_node()`는 `create` 경로에 해당하는 `CitySelectInput` 생성만 구현되어 있다. `clarify`, `modify`, `confirm` 분기는 후속 구현 대상이다.

---

## 2. Create 처리 방안

### 2.1 입력 분리

Intent는 create request를 두 종류로 나누어 다룬다.

| 구분 | 예시 필드 | 처리 |
|---|---|---|
| API-owned facts | `country`, `travelMonth`, `travelYear`, `tripType`, `includeFestivals`, `destinationId`, `userLocation` | request 값을 보존 |
| Natural-language signals | `rawQuery`, `softPreferenceQuery` | parser/LLM으로 해석 |

`destinationId`가 있으면 프론트에서 이미 city_id map을 적용한 것으로 본다. Intent는 도시 label, `city_key`, `ddb_pk`를 파싱하지 않는다.

### 2.2 자연어 추출

현재 code parser가 추출하는 항목:

- preferred/disliked theme ids
- preferred/disliked region ids (`KR-*` city_id only)
- contradiction reasons

LLM structured output이 추출해야 하는 항목:

- `cleaned_raw_query`
- `soft_preference_query`
- `transport_pref`: `walk | car | unknown`
- `congestion_pref`: `quiet | vibrant | neutral`
- `unsupported_conditions`
- preferred/disliked theme ids
- preferred/disliked region ids (`KR-*` city_id only)

LLM이 사실상 재결정하지 말아야 하는 항목:

- `country`
- `travel_month`
- `travel_year`
- `trip_type`
- `include_festivals`
- `destination_id`
- `user_location`

현재 prompt schema에는 위 API-owned fields도 포함되어 있다. 구현 시 validator는 request 값과 LLM 출력이 충돌하면 request 값을 우선해야 한다.

### 2.3 CreateIntentOutput

`create` intent는 state의 `intent` bucket에 아래 shape를 남긴다.

```json
{
  "intent_type": "create",
  "intent_extraction_mode": "code_parser",
  "city_select_input": {
    "country": "KR",
    "travel_month": 7,
    "travel_year": 2026,
    "trip_type": "2d1n",
    "active_required_themes": ["바다·해안"],
    "include_festivals": false,
    "cleaned_raw_query": "경주 말고 조용한 바다 쪽으로 1박 2일 가고 싶어.",
    "soft_preference_query": "",
    "unsupported_conditions": [],
    "destination_id": null,
    "user_location": null,
    "execution_mode": "city_discovery",
    "congestion_pref": "quiet",
    "transport_pref": "unknown",
    "city_key": null,
    "ddb_pk": null
  },
  "preferred_theme_ids": ["sea_coast"],
  "disliked_theme_ids": [],
  "preferred_region_ids": [],
  "disliked_region_ids": ["KR-47-130"],
  "preferred_region_spans": [],
  "disliked_region_spans": ["경주"],
  "unresolved_region_spans": [],
  "preferred_region_names": [],
  "disliked_region_names": ["경주시"],
  "needs_clarification": false,
  "clarifying_question": null,
  "contradiction_reasons": []
}
```

`city_select_input`은 `CitySelectInput.from_mapping()`을 통과할 수 있어야 한다.

---

## 3. Clarify 처리 방안

`clarify`는 graph가 `END_WAIT_USER`로 멈춘 뒤, 사용자가 선택지에 응답한 경우다.

### 3.1 Button 선택

프론트가 `selectedOptionId` 또는 `optionId`를 보내면 Intent는 새 option을 만들지 않는다. checkpoint의 pending clarification option에서 동일 id를 찾아 resolve한다.

```json
{
  "intent_type": "clarify",
  "status": "resolved",
  "thread_id": "thread-001",
  "selected_option_id": "continue_without_festival",
  "resume": {
    "option_id": "continue_without_festival"
  }
}
```

### 3.2 자연어 답변

자연어 답변 resolver는 후속 구현이다. 구현 시에도 출력은 기존 option id 하나로 귀결되어야 한다.

```json
{
  "intent_type": "clarify",
  "status": "resolved",
  "thread_id": "thread-001",
  "raw_clarify_query": "축제 빼고 계속해줘",
  "selected_option_id": "continue_without_festival",
  "resume": {
    "option_id": "continue_without_festival"
  },
  "audit": {
    "matched_label": "축제 없이 계속"
  }
}
```

Resolve 실패 시:

```json
{
  "intent_type": "clarify",
  "status": "needs_clarification",
  "thread_id": "thread-001",
  "raw_clarify_query": "음 아무거나",
  "selected_option_id": null,
  "reason_code": "clarify_option_unresolved"
}
```

---

## 4. Modify 처리 방안

`modify`는 checkpoint의 기존 itinerary/context를 읽어 수정 intent를 만든다. 프론트가 `editOps`를 보내지 않는다는 점이 중요하다.

처리 순서:

1. `threadId`, `itineraryRevision`, `rawModifyQuery`를 읽는다.
2. checkpoint에서 current itinerary와 `currentOrder`를 복원한다.
3. target phrase를 `item_id`로 resolve한다.
4. 요청이 slot replacement인지 city change인지 분류한다.
5. `V2_34_MODIFY_INTENT_SCHEMA.md`의 `modify_intent`를 출력한다.

출력은 `V2_34_MODIFY_INTENT_SCHEMA.md`를 canonical schema로 사용한다.

최소 discriminator:

```json
{
  "intent_type": "modification",
  "status": "ok",
  "kind": "slot_replace",
  "routing_hint": "planner_apply_edit"
}
```

도시 변경의 경우:

```json
{
  "intent_type": "modification",
  "status": "ok",
  "kind": "city_change",
  "edit_ops": [],
  "city_change": {
    "target_city_id": "KR-47-130",
    "target_city_name": "경주시",
    "city_preference_query": "경주로 바꿔줘",
    "carry_over_themes": true,
    "carry_over_festivals": true,
    "avoid_city_ids": ["KR-51-150"]
  },
  "routing_hint": "city_select_rediscovery"
}
```

---

## 5. Confirm 처리 방안

`confirm`은 일정 저장 확정 이벤트다. Intent는 새로운 여행 조건을 만들지 않고, profile update path가 필요한 최소 식별자만 남긴다.

```json
{
  "intent_type": "confirm",
  "status": "ok",
  "thread_id": "thread-001",
  "recommendation_id": "rec-001",
  "itinerary_revision": "rev-001"
}
```

Profile Agent는 checkpoint의 최종 itinerary와 theme context를 읽어 장기 profile을 업데이트한다.

---

## 6. Intent가 만들지 않는 값

| value | owner |
|---|---|
| `theme_weights` | Profile Agent |
| `city_key`, `ddb_pk` | city identity enrichment |
| festival verification result | Festival Verifier |
| place candidates / replacement candidates | Planner retrieval |
| route legs / 이동 시간 | Planner internal calculation |
| `apply`, `then` | clarification option generator |

---

## 7. 구현 우선순위

1. `create`: 현재 경로 유지, API-owned field 우선 보정 강화.
2. `clarify`: button `optionId` resolve부터 구현.
3. `modify`: `V2_34`의 `slot_replace`와 `city_change` 출력 생성.
4. `confirm`: profile update path용 discriminator 추가.
5. natural-language clarify resolver는 button path 이후 추가.
