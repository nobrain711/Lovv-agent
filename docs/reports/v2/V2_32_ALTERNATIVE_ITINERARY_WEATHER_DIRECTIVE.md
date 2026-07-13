# V2_32 대체 일정 날씨 지시서

> 상태: 설계 지시서, 1차 구현 진행 중.
> 범위: `src/lovv_agent_v2/resources/city_monthly_weather_risks.json`를 사용해 V2가 언제, 어떤 방식으로 날씨 리스크 기반 대체 일정을 노출할지 결정한다.

## 1. 결정 사항

`alternative_itinerary`는 기본으로 생성되는 두 번째 전체 일정이 아니다.
선택된 도시와 여행 월, 그리고 실제 일정의 야외 노출도가 모두 의미 있게 날씨에 민감할 때만 제공하는 날씨 리스크 백업 표면이다.

기본 일정 생성 흐름은 그대로 유지한다.

```text
city_select / direct anchor
-> planner retrieve_places
-> route_days
-> assemble_itinerary
-> response_packager
```

날씨 리스크는 기본 일정이 조립된 뒤 평가한다. 트리거가 다음 두 요소에 동시에 의존하기 때문이다.

- 선택 도시와 `travel_month`
- 실제 일정의 outdoor/mixed 노출도

## 2. 날씨 리스크 리소스 계약

런타임 소스:

```text
src/lovv_agent_v2/resources/city_monthly_weather_risks.json
```

조회 키:

```text
(city_id, travel_month)
```

주요 필드:

```json
{
  "city_id": "KR-...",
  "month": 7,
  "risk": {
    "overall": "low | medium | high",
    "dimensions": {
      "rain": "low | medium | high",
      "heat": "low | medium | high",
      "cold": "low | medium | high",
      "low_sunshine": "low | medium | high",
      "snow": "low | medium | high | unknown"
    },
    "scores": {},
    "reason_codes": []
  },
  "data_quality": {}
}
```

커버리지 주의:

- 현재 테이블은 기후표 도시 68개, city-month 816행을 포함한다.
- 특정 city-month 리스크가 없는 것은 정상이며 planner 실패로 이어지면 안 된다.
- 리스크가 없으면 `weather_risk_status = unavailable`로 두고, 대체 일정 안내를 만들지 않는다.
- 선택 도시가 68개 weather map 대상에 없으면 `unavailable_reason = city_weather_map_missing`로 audit에 남긴다.

## 3. 트리거 정책

날씨 안내와 대체 일정 생성은 분리한다.

| 조건 | Planner 동작 |
|---|---|
| 리스크 행 없음 | 날씨 안내 없음, 대체 일정 없음 |
| `overall=low` | 대체 일정 없음 |
| `overall=medium`이고 outdoor/mixed 비율 `>= 40%` | 약한 날씨 안내 추가 |
| `overall=high`이고 outdoor/mixed 비율 `>= 25%` | 강한 날씨 안내 추가 |
| `overall=high`이고 outdoor/mixed 비율 `>= 50%` | 날씨 대체 일정 제공 |

정확한 비율은 `V2_16`을 따르며, smoke 측정 뒤 조정할 수 있다.

사용자 노출 문구에는 반드시 "평년 기준 리스크"를 사용하고, 실시간 예보처럼 보이게 표현하지 않는다.

### 날씨 판단 세부

날씨 판단은 두 층으로 나뉜다.

```text
monthly climate risk
  -> 선택 도시 + 여행 월의 기후상 리스크

itinerary exposure
  -> 생성된 일정이 실제로 그 리스크에 노출되는 정도
```

날씨 리스크 행만으로 대체 일정을 만들면 안 된다. 어떤 city-month의 `overall`이 `high`여도 최종 일정이 대부분 실내라면, planner는 가벼운 안내만 주거나 아예 대체 일정을 만들지 않아야 한다.

런타임 판단 순서:

1. `(selected_city_id, travel_month)`를 확정한다.
2. `city_monthly_weather_risks.json`에서 해당 행을 조회한다.
3. 행이 없으면 `weather_risk_status=unavailable`로 두고 종료한다.
   - `city_id`/`travel_month`는 있으나 map에 행이 없으면 `city_weather_map_missing`.
   - `city_id` 또는 `travel_month` 자체가 없으면 각각 `missing_city_id`, `missing_travel_month`.
4. `risk.overall`, `risk.dimensions`, `risk.scores`, `risk.reason_codes`를 읽는다.
5. 최종 일정 item을 `indoor | outdoor | mixed | unknown`으로 분류한다.
6. 노출 비율을 계산한다.
   - `outdoor_ratio = outdoor_count / known_exposure_count`
   - `mixed_ratio = mixed_count / known_exposure_count`
   - `weather_sensitive_ratio = (outdoor_count + mixed_count) / known_exposure_count`
7. 관련 리스크 dimension과 노출 slot을 매칭한다.
8. 안내 문구와 `alternative_itinerary` 제공 여부를 결정한다.

`unknown` 노출은 분모에서 제외한다. 모든 item이 `unknown`이면 날씨 대체 일정을 제공하지 않고 내부 audit만 남긴다.

### 리스크 severity 출처

`risk.overall`과 `risk.dimensions`는 `city_monthly_weather_thresholds.json`에서 미리 계산된다.

threshold 정책은 `V2_16`을 따른다.

| threshold 유형 | 목적 |
|---|---|
| global percentile | 이 city-month가 전국 모든 city-month와 비교해 어려운 조건인지 판단 |
| same-month percentile | 이 도시가 같은 월의 다른 도시와 비교해 어려운 조건인지 판단 |

Dimension 점수 규칙:

| metric 방향 | 조건 | 점수 |
|---|---|---:|
| upper-tail metric | global p90 이상 | +2.0 |
| upper-tail metric | global p75 이상 | +1.0 |
| upper-tail metric | same-month p90 이상 | +1.0 |
| upper-tail metric | same-month p75 이상 | +0.5 |
| lower-tail metric | global p10 이하 | +2.0 |
| lower-tail metric | global p25 이하 | +1.0 |
| lower-tail metric | same-month p10 이하 | +1.0 |
| lower-tail metric | same-month p25 이하 | +0.5 |

Dimension severity:

| dimension 점수 | severity |
|---:|---|
| `>= 3.0` | `high` |
| `>= 1.5` | `medium` |
| 그 외 | `low` |

Overall severity:

| 조건 | overall |
|---|---|
| 하나 이상의 dimension이 `high`이거나 total score `>= 4.0` | `high` |
| total score `>= 2.0` | `medium` |
| 그 외 | `low` |

Dimension과 metric 매핑:

| dimension | source metrics | route/planner 의미 |
|---|---|---|
| `rain` | `precip_mm`, `precip_days` | outdoor/mixed slot이 민감함 |
| `heat` | `avg_high_c`, `humidity_pct` | 낮 시간 outdoor/mixed slot이 민감함 |
| `cold` | `avg_low_c` | outdoor/mixed slot이 민감함 |
| `low_sunshine` | `sunshine_hours` | 경관/전망 outdoor slot에 약한 민감 신호 |
| `snow` | `snow_days` | outdoor/mixed slot과 도보 경로가 민감함. 커버리지 부족으로 `unknown`인 경우가 많음 |

`reason_codes`는 어떤 percentile 규칙이 발화했는지 설명한다. 예: `avg_low_c_lte_global_p10`. 이는 audit/debug 재료이며 사용자 노출 문구에 그대로 복사하면 안 된다.

### 안내와 대체 일정 결정 매트릭스

Planner는 날씨 severity와 일정 노출도를 함께 본다.

| 리스크 + 노출 | 출력 |
|---|---|
| 리스크 행 없음 | 안내 없음, 대체 일정 없음 |
| `overall=low` | 안내 없음, 대체 일정 없음 |
| `overall=medium` + `weather_sensitive_ratio < 40%` | 대체 일정 없음. 낮은 우선순위 audit만 선택적으로 남김 |
| `overall=medium` + `weather_sensitive_ratio >= 40%` | 약한 안내 |
| `overall=high` + `weather_sensitive_ratio < 25%` | 노출 dimension이 맞을 때만 약한 안내 |
| `overall=high` + `weather_sensitive_ratio >= 25%` | 강한 안내 |
| `overall=high` + `weather_sensitive_ratio >= 50%` | 강한 안내 + 신뢰할 수 있는 대체 후보가 있을 때 대체 일정 제공 또는 사전 계산 |

Dimension 매칭이 중요하다. 예를 들면 다음과 같다.

- `rain=high`는 해변, 트레일, 야외 축제, 전망지, 야외 이동이 섞인 mixed slot에 영향을 준다.
- `heat=high`는 저녁 실내 slot보다 낮 시간 outdoor slot에 더 크게 영향을 준다.
- `cold=high`는 야외 도보나 노출된 경관 slot에 영향을 준다.
- `low_sunshine=high` 단독으로는 보통 전체 대체 일정을 트리거하지 않고 보조 사유로만 사용한다.
- `snow=unknown`은 단독으로 어떤 동작도 트리거하지 않는다.

### 예시

예시 A: 비 리스크가 높고 야외 중심 일정인 경우

```text
city_id = KR-...
month = 7
risk.overall = high
risk.dimensions.rain = high
weather_sensitive_ratio = 0.67
```

결정:

```text
weather_notice = strong
alternative_itinerary = 같은 도시의 실내/날씨 회복력 있는 대체 후보가 있으면 허용
user wording = "7월은 평년 기준 비 리스크가 높은 편이라 야외 일정 일부는 실내 대체 후보를 준비할 수 있습니다."
```

예시 B: 리스크는 높지만 대부분 실내 일정인 경우

```text
risk.overall = high
weather_sensitive_ratio = 0.20
```

결정:

```text
weather_notice = weak 또는 none
alternative_itinerary = none
```

이유:

```text
해당 city-month 자체는 리스크가 있지만, 이 구체적인 일정은 크게 노출되어 있지 않다.
```

예시 C: city-month 행이 없는 경우

```text
city_id가 weather risk table에 없음
```

결정:

```text
weather_risk_status = unavailable
weather_notice = none
alternative_itinerary = none
```

이유:

```text
날씨 리스크 커버리지는 불완전할 수 있으며, planner 출력을 막으면 안 된다.
```

## 4. 야외 노출 분류

Planner는 각 일정 item을 다음 중 하나로 분류한다.

```text
indoor | outdoor | mixed | unknown
```

초기 classifier는 결정론적이고 audit 가능해야 한다.

1. `item_type == festival`이면 추후 payload에 실내 근거가 생기기 전까지 `outdoor`로 본다.
2. `attraction_subtype_code` 기반 분류는 `attraction_subtypes.json`을 따른다.
3. subtype이 없을 때만 title/theme fallback을 사용한다.
4. `unknown`은 그대로 유지하며 outdoor exposure에 포함하지 않는다.

리스크 dimension별 민감 대상:

| dimension | 영향 대상 |
|---|---|
| `rain` | outdoor/mixed slot |
| `heat` | 낮 시간 outdoor/mixed slot |
| `cold` | outdoor/mixed slot |
| `snow` | outdoor/mixed slot, 특히 도보 경로 |
| `low_sunshine` | outdoor 경관/전망 slot. 약한 신호 |

## 5. 대체 일정 의미

`alternative_itinerary`는 날씨에 민감한 slot에 대한 교체 제안이지, 도시 교체가 아니다.

규칙:

- 선택 도시는 유지한다.
- trip type과 day count를 유지한다.
- seed/festival item은 해당 seed 자체가 안전하지 않고 사용자가 명시적으로 교체를 요청한 경우가 아니면 유지한다.
- 영향받은 outdoor/mixed non-seed slot만 교체한다.
- 실내 또는 날씨 회복력이 있는 subtype을 우선한다.
- 가능한 한 day/order 구조를 보존한다.
- primary itinerary를 조용히 바꾸지 않는다.

권장 대체 item 필드는 일반 planner item shape를 재사용하되, 날씨 metadata를 추가한다.

```json
{
  "day": 1,
  "slot": "afternoon",
  "item_type": "attraction",
  "placeId": "...",
  "title": "...",
  "body": "...",
  "reason": "비가 많은 달이라 실내 후보로 대체할 수 있습니다.",
  "replacesItemId": "item-2",
  "weatherRiskReason": "rain_high",
  "weatherRiskDimensions": ["rain"]
}
```

## 6. 응답 계약

Public response는 기존 recommendation response envelope을 유지한다.

Primary path:

```text
response_status = modification_pending
itinerary.days = primary itinerary
alternativeItinerary = optional weather backup proposal
explainability.userNotice includes weather notice
```

대체 item 생성 전에 명시적인 사용자 선택을 받고 싶다면 기존 clarification 메커니즘을 사용한다.

```text
reason_code = weather_alternative_available
then = weather_alternative
```

다만 V2 첫 구현은 reserve/indoor 후보가 이미 충분할 때 가벼운 사전 계산 `alternative_itinerary`를 우선한다. 신뢰할 수 있는 대체 후보가 없으면 안내만 반환한다.

## 7. Planner 통합 지점

날씨 단계는 `assemble_itinerary`가 primary itinerary를 만든 뒤, response packaging/explanation 전에 추가한다.

```text
route_days
-> assemble_itinerary
-> weather_alternative
-> explain_itinerary
-> response_packager
```

이유:

- 최종 slot과 route item payload가 필요하다.
- primary itinerary의 selection/routing을 흔들면 안 된다.
- planner reserve와 선택 도시/월 metadata를 재사용할 수 있다.

State 추가:

```text
state.planner.weather_risk
state.planner.weather_notice
state.planner.alternative_itinerary
state.planner.validation_result.weather_audit
```

## 8. 대체 slot 후보 소스

후보 소스는 다음 순서로 사용한다.

1. 같은 도시의 route/selection reserve
2. 선택되지 않은 planner place pool candidates
3. indoor/weather-resilient subtype hint를 포함한 같은 도시 S3 Vector 재조회

날씨 대체 일정에는 자동 alternative-city fallback을 사용하지 않는다.

첫 구현은 reserve/place-pool만으로 시작할 수 있다. S3 재조회는 교체 품질을 측정한 뒤 붙인다.

## 9. 초기 구현 계획

1. `(city_id, month)` 키 기반 weather risk resource loader를 추가한다.
2. 결정론적 item exposure classifier를 추가한다.
3. 안내와 optional alternative를 만드는 `weather_alternative` planner step을 추가한다.
4. 아직 노출되어 있지 않다면 packager에 `alternativeItinerary` 지원을 추가한다.
5. smoke case를 추가한다.
   - 비 리스크가 높은 월 + outdoor-heavy itinerary -> 안내 + 백업
   - low-risk month -> 안내 없음
   - missing risk city -> 실패 없음
   - festival seed present -> seed 보존

## 10. Non-goals

- 실시간 날씨 예보를 사용하지 않는다.
- 자동 도시 교체를 하지 않는다.
- primary itinerary를 자동으로 변형하지 않는다.
- raw percentile `reason_codes`를 사용자에게 노출하지 않는다.
- V2 첫 단계에서 weather risk로 city_select를 광범위하게 reranking하지 않는다.
