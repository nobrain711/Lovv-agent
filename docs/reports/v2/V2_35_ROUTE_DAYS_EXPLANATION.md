# V2 Route Days Explanation

작성일: 2026-07-02

## 1. 목적

`route_days`는 Planner 안에서 "어떤 장소를 어느 날, 어떤 순서로 방문할지"를 결정하는 단계다.

현재 planner 흐름에서 책임은 다음처럼 나뉜다.

```text
retrieve_places
  -> 도시 안 후보 장소 pool 생성

route_days
  -> working set 선택
  -> seed/anchor 기준 일자 배정
  -> 이동 순서 결정
  -> 이동시간 초과 후보 reserve 처리

assemble_itinerary
  -> route_days 결과를 public PlannerOutput item으로 변환
```

따라서 `assemble_itinerary`는 실제 배치 알고리즘이 아니라 output builder에 가깝다. 일자별 배치와 route trim은 `route_days`가 결정한다.

## 2. 입력과 출력

`route_days`는 `PlannerPlace` working set을 받는다. 이 working set은 raw retrieval 후보, soft retrieval 후보, seed, active theme, trip type을 반영해 `build_working_set()`에서 만들어진다.

입력의 핵심 필드:

- `places`: 선택된 `PlannerPlace` 목록
- `trip_type`: `daytrip`, `2d1n`, `3d2n`
- `transport_pref`: `walk`, `car`, `unknown` 등
- `durations`: ORS 또는 fallback provider가 만든 장소 간 이동시간 matrix
- `provider_audit`: snap/matrix provider의 audit 정보

출력의 핵심 필드:

- `days[]`: 일자별 route 결과
- `days[].anchor_place_id`: 해당 일자의 anchor
- `days[].anchor_type`: `seed` 또는 `medoid`
- `days[].places[]`: 방문 순서와 이전 장소로부터 이동분
- `reserve[]`: 선택됐지만 이동시간/route 제약으로 최종 일정에서 빠진 후보
- `audit`: 이동시간 정책, trim 결과, transport notice

## 3. 상세 알고리즘

### 3.1 Working Set 선택

`route_days`에 들어가기 전 `build_working_set()`이 일정 후보를 고른다.

현재 정책:

- raw 후보 중 active theme에 속한 장소를 유지한다.
- soft 후보는 상대 컷 없이 theme gate를 통과하면 고려한다.
- preferred theme는 별도 검색이 아니라 raw/soft pool 안의 차순위 생존 신호로만 쓴다.
- raw/soft가 같은 place id를 가리키면 하나로 merge하고 soft score를 보강한다.
- trip type별 target count에 맞춰 theme quota를 적용한다.
- 같은 subtype이 과도하게 반복되지 않도록 subtype cap을 적용한다.
- 명시 seed가 없으면 active theme별 top 1을 semantic seed로 승격한다.

중요한 점은 seed가 "무조건 포함해야 할 anchor 후보" 역할을 한다는 것이다. 축제 포함이면 confirmed festival이 seed로 들어갈 수 있다. 단, `destination_id + include_festivals=false`인 direct anchor 경로는 supervisor가 city_select를 건너뛰므로 city_select의 place score/theme evidence seed가 없다. 이 경우 planner가 해당 city_id로 anchored retrieval을 직접 수행한 뒤, 명시 seed가 없으면 selected 후보 안에서 active theme별 top 1을 semantic seed로 승격한다.

### 3.2 Trip Type별 목표 수

`day_profile.py` 기준 목표는 다음과 같다.

| trip type | max target | min target |
|---|---:|---:|
| `daytrip` | 3 | 2 |
| `2d1n` | 3 + 3 = 6 | 2 + 2 = 4 |
| `3d2n` | 3 + 4 + 3 = 10 | 2 + 3 + 2 = 7 |

이 값은 "후보를 몇 개까지 뽑을지"와 "최종 일정이 충분한지"를 판단하는 기준이 된다.

### 3.3 Anchor 선정

일자별 route의 시작점은 anchor다.

선정 순서:

1. seed 장소를 먼저 anchor로 쓴다.
2. seed 수가 day count보다 적으면 남은 후보에서 medoid를 고른다.
3. medoid는 다른 후보들과의 총 이동시간이 가장 작은 장소다.

이 방식은 seed를 일정의 의미 중심으로 보존하면서, seed가 부족한 날에는 동선상 중심적인 장소를 anchor로 잡게 해준다.

### 3.4 일자별 배정

각 장소는 가장 가까운 anchor day bucket으로 들어간다.

배정 기준:

1. 해당 day bucket이 이미 목표 수를 넘었는지
2. anchor와의 이동시간이 얼마나 짧은지
3. 현재 bucket의 장소 수가 얼마나 적은지

즉 단순히 점수순으로 하루에 몰아넣지 않고, anchor 주변으로 장소를 나눠서 일자별 밀도를 조절한다.

### 3.5 방문 순서 결정

각 day bucket 안에서는 anchor에서 시작해 nearest-neighbor 방식으로 순서를 잡는다.

```text
anchor
  -> 현재 위치에서 가장 가까운 미방문 장소
  -> 다시 가장 가까운 미방문 장소
  -> ...
```

완전 최적 TSP는 아니지만, 후보 수가 작고 실시간 응답이 필요한 planner에는 충분히 빠르고 설명 가능한 방식이다.

### 3.6 Route Trim

정렬된 day route가 너무 길면 일부 후보를 reserve로 보낸다.

현재 기준:

- 하루 총 이동시간: 180분 이하
- 단일 hard leg 이동시간: 120분 이하
- `transport_pref == "walk"`일 때 soft leg 이동시간: 60분 이하

trim 우선순위:

1. 120분 초과 hard leg를 만드는 pair 중 seed가 아닌 후보를 제거한다.
2. 그래도 하루 총 이동시간이 길면 전체 route에서 이동 부담이 큰 non-seed 후보를 제거한다.
3. walk 선호가 있으면 60분 soft leg 초과도 trim 조건으로 본다.
4. seed는 가능한 한 보존한다.

이 정책 때문에 최종 itinerary 수가 working set 수보다 적을 수 있다. 이때 빠진 장소는 `route.reserve`와 `route_audit.trimmed_place_ids`에 남는다.

### 3.7 Cross-Day Repair

route trim으로 빠진 후보가 곧바로 버려지는 것은 아니다. 현재 구현은
`cross_day_repair` 단계에서 reserve 후보를 다른 day에 넣었을 때 다음 조건을
덜 깨는지 시뮬레이션한다.

- 삽입 후 day total이 180분 이하인지
- 삽입 후 max hard leg가 120분 이하인지
- walk 선호가 있으면 soft leg 60분 이하인지
- 해당 day의 target count를 과도하게 넘기지 않는지

조건을 만족하면 해당 reserve 후보를 더 적합한 day에 재삽입하고,
`route_audit.cross_day_rescued_place_ids`에 기록한다. 즉 route trim은 단순
삭제가 아니라 "일단 빼고, 다른 날에 넣으면 괜찮은지 다시 본다"는 2단계
정책이다.

이 정책이 필요한 이유는 명확하다. 어떤 장소는 1일차 route에서는 120분 hard
leg를 만들지만, 2일차 anchor 근처에 넣으면 이동 제약을 만족할 수 있다.
기존의 day-local trim만 있으면 이런 후보가 불필요하게 사라진다.

## 4. 실제 Smoke 사례

### 4.1 동해시 2D1N 해안 조용한 여행

결과 파일:

`docs/tasks/results/v2_generation_planner_smoke/20260702_generation_batched/20260701T202210Z/v2_gen_01_coast_quiet_2d1n.json`

요약:

- destination: `KR-51-170` 동해시
- planner gate: `ok`
- trip type: `2d1n`
- 최종 itinerary: 2일, 6개 장소
- reserve: 7개
- route trim: 없음
- day targets: `[3, 3]`

배치 결과:

| day | anchor type | 장소 | 이동분 |
|---:|---|---|---|
| 1 | seed | 한섬해변&한섬감성바닷길 -> 감추해변 -> 대진 해수욕장 | 0, 1, 7 |
| 2 | medoid | 하평해변(동해) -> 고불개해변 -> 망상해변 | 0, 1, 8 |

해석:

- 2D1N 목표인 6개 장소를 정확히 채웠다.
- 1일차는 seed 중심으로, 2일차는 medoid 중심으로 묶였다.
- 각 일자의 이동시간이 8분, 9분 수준이라 도시 안 compact route가 만들어졌다.
- reserve 7개는 후보 pool의 여유를 보여주며, 최종 일정에는 target count만 반영됐다.

이 사례는 `route_days`가 의미 중심(seed)과 동선 중심(medoid)을 함께 쓰는 방식이 실제 해안 여행 일정에 잘 맞는다는 근거다.

### 4.2 진도군 도보 해안 당일 여행

결과 파일:

`docs/tasks/results/v2_generation_planner_smoke/20260702_generation_single_60s/20260701T235922Z/v2_gen_11_coast_walk_daytrip.json`

요약:

- destination: `KR-38-21` 진도군
- planner gate: `ok`
- trip type: `daytrip`
- transport preference: `walk`
- 최종 itinerary: 1일, 3개 장소
- route trim: 없음
- transport notice: `walkable_compact_city`
- day target: `[3]`

배치 결과:

| day | anchor type | 장소 | 이동분 |
|---:|---|---|---|
| 1 | seed | 진도 신비의 바닷길 -> 가계해수욕장 -> 쉬미항 | 0, 1, 16 |

해석:

- 당일 목표인 3개 장소를 채웠다.
- seed인 `진도 신비의 바닷길`을 시작점으로 두고 가까운 해안 후보를 이어 붙였다.
- 전체 day travel이 17분이라 `walkable_compact_city` notice가 가능했다.

이 사례는 도보 선호가 있을 때 route provider audit을 통해 compact 여부를 판단하고, 사용자가 이해할 수 있는 이동성 notice를 만드는 데 유효하다.

### 4.3 강릉시 Anchored 예술 당일 여행

결과 파일:

`docs/tasks/results/v2_generation_planner_smoke/trip_intent_entry_verify/20260702T020447Z/v2_gen_18_anchored_gangneung_art_daytrip.json`

요약:

- destination: `KR-51-150` 강릉시
- planner gate: `ok`
- trip type: `daytrip`
- 최종 itinerary: 1일, 3개 장소
- route trim: 없음
- transport notice: `walkable_compact_city`
- day target: `[3]`

배치 결과:

| day | anchor type | 장소 | 이동분 |
|---:|---|---|---|
| 1 | seed | 아르떼뮤지엄 강릉 -> 강릉시립미술관 교동 -> 하슬라아트월드 | 0, 4, 12 |

해석:

- direct anchor 요청에서 city_select 없이 planner가 강릉 도시 안 후보를 검색했다.
- 예술 테마 top seed가 anchor가 되고, 미술관/아트월드가 같은 day bucket에 배치됐다.
- 이동시간이 16분 수준이라 당일 예술 코스로 자연스럽다.

이 사례는 anchored request에서도 `route_days`가 도시 고정 후 장소 검색, semantic seed, nearest-neighbor route를 통해 곧바로 일정화할 수 있음을 보여준다.

## 5. 전체 Smoke 결과 분석

### 5.1 분석 범위

분석 범위는 본편 generation mock `v2_gen_01-08`, `v2_gen_10-40` 총 39건이다. `v2_gen_09`는 제외했고, 이전 timeout anchored 케이스는 rerun한 최신 결과를 우선 사용했다.

이 범위는 short input 10건을 제외한 본편 generation smoke 기준이다.

### 5.2 전체 결과

| 구분 | 건수 | 해석 |
|---|---:|---|
| 전체 케이스 | 39 | 본편 generation smoke 기준 |
| planner `ok` | 34 | 일정 생성 성공 |
| planner `insufficient_candidates` | 3 | 후보 부족 또는 route 후 최종 수량 부족 |
| planner 미진입 | 2 | festival gate clarification |
| response `modification_pending` | 37 | 초회 생성 후 수정 대기 상태 |
| response `END_WAIT_USER` | 2 | 사용자 확인 필요 |

`END_WAIT_USER` 2건은 실패가 아니라 festival gate가 정상적으로 멈춘 케이스다.

- `v2_gen_21_festival_history_art_daytrip`: `festival_none`
- `v2_gen_32_anchored_boryeong_festival_coast_2d1n`: `anchor_festival_conflict`

### 5.3 Planner 관측

정상 planner `ok` 34건은 대체로 안정화됐다.

주요 관측:

- `best * ratio` raw relevance cut 제거 이후, 제주처럼 큰 후보 pool을 가진 케이스가 살아났다.
- `v2_gen_19_anchored_jeju_nature_coast_3d2n`은 10개 item을 만들었고, 자연 5개 + 해안 5개로 theme coverage가 안정적이었다.
- direct anchor seed도 작동한다.
- anchored 성공군 14건 중 seed 1개 케이스가 7건, seed 2개 케이스가 7건이었다.
- route trim은 3건으로 제한적이었다.

route trim 발생 케이스:

- `v2_gen_02`
- `v2_gen_26`
- `v2_gen_33`

이 중 `v2_gen_26`은 selected 6개에서 trim 후 4개로 줄어 target 대비 얇아졌다. 즉 route trim 자체는 드물지만, trim 이후 target 아래로 떨어지는 경우에는 backfill 또는 notice가 필요하다.

### 5.4 문제 패턴

#### 온천·휴양 희소성

`온천·휴양`은 theme gate를 통과할 데이터 자체가 희소하다.

관측 케이스:

- `v2_gen_06_healing_2d1n`: 2개, `insufficient_candidates`
- `v2_gen_24_healing_family_2d1n`: 1개, `insufficient_candidates`
- `v2_gen_38_anchored_damyang_nature_healing_2d1n`: planner `ok`지만 `온천·휴양=0`, 자연 4개로 대체

결론:

- healing은 없는 데이터를 있는 것처럼 포장하면 안 된다.
- `planner_status_gate=ok`라도 required theme count가 0이면 `partial_theme_miss` audit/notice가 필요하다.
- healing을 hard theme로 둘지, 자연/휴식 facet으로 완화할지 별도 정책 결정이 필요하다.

#### Direct anchor destination name 누락

anchored 결과 다수에서 `destinationId`는 있지만 `destination.name=null`로 나타났다.

planner item에는 `city_name_ko`가 있으므로 response packager에서 다음 순서로 보강 가능하다.

1. response destination name
2. selected city payload의 `city_name_ko`
3. planner itinerary item의 `city_name_ko`
4. city identity map

사용자 응답 품질상 우선순위가 높은 수정이다.

#### City Select capacity 신호 혼동

`selection_reason_code`에 `insufficient_candidates`가 붙은 케이스가 16건이었다. 그러나 그중 상당수는 planner가 최종적으로 `ok`를 만들었다.

예:

- `v2_gen_02`
- `v2_gen_03`
- `v2_gen_04`
- `v2_gen_08`
- `v2_gen_11`
- `v2_gen_12`
- `v2_gen_16`
- `v2_gen_29`
- `v2_gen_31`
- `v2_gen_33`
- `v2_gen_39`

결론:

- city_select의 `insufficient_candidates`는 최종 planner 실패가 아니다.
- 현재 의미는 "planner 위험 신호"에 가깝다.
- `planner_capacity_risk` 또는 `thin_theme_pool`처럼 낮은 강도의 audit signal로 바꾸는 편이 덜 혼란스럽다.

#### Auto alternative fallback 위험

fallback 발생 3건:

- `v2_gen_01`: fallback 후 `ok`
- `v2_gen_06`: fallback 후에도 `insufficient_candidates`
- `v2_gen_24`: fallback 후에도 `insufficient_candidates`

특히 healing에서는 alternative city 교체가 문제를 해결하지 못했다. 도시를 자동으로 바꿔도 테마 데이터가 희소하면 결과가 좋아지지 않는다.

결론:

- V2_26에서 논의한 "자동 도시교체보다 scope 조정/되묻기" 방향이 더 적절하다.
- alternative fallback은 유지하더라도 사용자에게 도시 변경 사실과 이유를 분명히 알려야 한다.

### 5.5 우선 수정 제안

1. response packager: direct anchor destination name 보강
   - `destination_id` 기준 city identity map 또는 planner item의 `city_name_ko`를 사용한다.

2. planner validation: partial theme miss 추가
   - planner gate가 `ok`여도 required theme 중 count 0이면 `partial_theme_miss` audit/notice를 생성한다.
   - 특히 `온천·휴양=0` 같은 케이스를 사용자에게 숨기지 않는다.

3. city_select audit 용어 정리
   - 현재 `insufficient_candidates`는 planner 실패처럼 보이지만 실제로는 위험 신호인 경우가 많다.
   - `planner_capacity_risk` 또는 `thin_theme_pool`로 분리한다.

4. route trim 후 backfill
   - selected/routable은 충분한데 trim 후 target 아래로 떨어지는 케이스에 reserve 재삽입 또는 notice를 추가한다.

5. healing sparse-theme policy
   - `온천·휴양`은 단순 quota로 밀어붙이면 빈 결과 또는 약한 결과가 자주 난다.
   - hard theme로 유지할지, 자연/휴식 facet으로 완화할지 별도 정책이 필요하다.

요약하면, 현재 route_days 자체는 대체로 안정적이다. 먼저 고칠 것은 route 알고리즘 본체보다 응답 품질과 검증 신호다. 우선순위는 direct anchor destination name 보강, partial theme miss 노출, city_select capacity signal 정리 순서가 적절하다.

## 6. 왜 여행 일정 계획에 유효한가

### 의미 중심과 동선 중심을 분리한다

여행 일정은 단순히 관련도 높은 장소를 나열하는 문제가 아니다. 사용자가 원한 테마를 대표하는 장소는 반드시 살아야 하고, 동시에 하루 동선이 무리하면 안 된다.

현재 `route_days`는 이 둘을 분리한다.

- 의미 중심: seed, theme quota, subtype cap
- 동선 중심: medoid anchor, nearest-neighbor ordering, route trim

그래서 "좋은 장소 목록"을 "갈 수 있는 일정"으로 바꾸는 중간 단계가 된다.

### Trip type별 밀도가 다르다

`daytrip`, `2d1n`, `3d2n`마다 하루 목표 수가 다르다. 이 정책이 없으면 1일 코스에 장소가 너무 많거나, 2박 3일 코스가 빈약해진다.

현재 target/min target은 smoke에서 다음처럼 작동했다.

- 동해 2D1N: `[3, 3]` -> 6개 장소
- 진도 daytrip: `[3]` -> 3개 장소
- 강릉 daytrip: `[3]` -> 3개 장소

### Seed를 보존하되 seed가 없으면 보완한다

축제나 city_select 대표 장소가 seed로 들어오면 해당 장소를 anchor로 우선 보존한다. direct anchor/no-festival처럼 city_select를 건너뛰는 경로에서는 planner가 도시 anchored retrieval을 먼저 수행하고, 그 결과 안에서 active theme별 top 1을 semantic seed로 승격한다.

이 정책 덕분에 단일 anchor/discovery에서도 "무엇을 중심으로 하루를 시작할지"가 생긴다.

### 무리한 동선은 reserve로 보낸다

후보가 많다고 모두 일정에 넣지 않는다. day limit과 leg limit을 넘는 후보는 reserve로 빠진다.

이것은 일정 품질상 중요하다. 관련도는 높지만 멀리 떨어진 장소를 억지로 넣으면 추천은 풍성해 보여도 실제 여행성은 떨어진다.

### Audit이 설명 가능하다

`route_days`는 다음 값을 남긴다.

- `day_place_targets`
- `anchor_type`
- `day_travel_min`
- `trimmed_place_ids`
- `transport_notice`
- `reserve`

이 audit은 smoke 분석과 사용자-facing notice의 근거가 된다. 예를 들어 도보 선호일 때 compact route면 `walkable_compact_city`, 아니면 차량/대중교통 권장 notice를 만들 수 있다.

## 7. 현재 한계와 후속 개선 후보

### 7.1 Distance provider 품질

route 품질은 duration matrix에 크게 의존한다. ORS가 실패하거나 snap exclusion이 많으면 fallback duration에 의존하게 된다. 이 경우 audit에 provider fallback 여부가 남아야 한다.

### 7.2 Nearest-neighbor는 빠르지만 전역 최적은 아니다

현재 방식은 설명 가능하고 빠르지만 전역 최단 경로를 보장하지 않는다. 후보 수가 커지거나 교통 모드가 다양해지면 local optimization 한계가 드러날 수 있다.

다만 현재 planner는 day별 후보 수가 보통 3-4개 수준이므로 nearest-neighbor가 실용적이다.

### 7.3 Slot Replace와의 연결

향후 장소 변경 수정은 `route_days`의 reserve 개념을 직접 활용하게 된다. 다만
`planner_output.validation_result.itinerary_structure.reserve`를 수정 작업의
정본으로 쓰는 것은 적절하지 않다. `validation_result`는 audit/diagnostic 성격이
강하기 때문이다.

수정 pipeline에서는 별도 working state가 필요하다.

```text
state.planner.modify_context.reserve_pool
```

slot replace는 이 reserve pool을 우선 사용하고, 후보를 삽입한 뒤 다시
`route_days` 또는 동일한 travel-time 정책을 적용해야 한다. 이렇게 해야 "장소만
바꿨는데 동선은 깨진 일정"을 막을 수 있다.

### 7.4 Reserve를 대체 일정으로 승격하는 정책

현재 reserve는 "빠진 후보"로만 남는다. 향후 alternative itinerary를 만들 때는 reserve를 날씨/혼잡/휴무 대체 후보로 재사용할 수 있다.

### 7.5 `assemble_itinerary` 이름 혼동

현재 실제 배치는 `route_days`가 하고, `assemble_itinerary`는 output builder 역할이다. 장기적으로는 `assemble_itinerary`를 `build_planner_output` 또는 `finalize_itinerary`로 rename하는 편이 책임 경계가 명확하다.
