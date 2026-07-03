# V2_22 — Profile theme-weight config (확정)

> Profile 에이전트가 저장 여행 이력으로 테마 가중치를 학습 → city_select의 effective theme_weights로 반영. 2026-06-30 확정.
> 데이터: `docs/tasks/results/v2_profile_personas/`(personas + rescore comparison). 검증: v2 smoke 52케이스 × 20 페르소나 offline 그리드.
> (※ 문서 번호: 21은 축제 지시서가 선점 → 프로필은 22.)

## 확정값 — "중간(medium)"
| 파라미터 | 값 | 비고 |
|---|---|---|
| **weight range** | **[0.8, 1.3]** (medium) | ★ 실질 유일한 레버 |
| alpha | 1.5 | 포화 영역(1.5↑ 차이 미미), 기본값 |
| profile_score_cap | 0.05 | 거의 non-binding(평평 coverage라 tilt가 작음), 기본값 |
| profile_activation_saved_trip_count | 3 | **3건 미만 → profile 완전 off(하드 게이트)** |

## runtime profile source ✅
Profile 데이터의 live 정본은 DynamoDB `LovvUserProfile`이다. `src/lovv_agent_v2/resources/mock_user_profiles.json`과 `app/LovvAgentV2/lovv_agent_v2/resources/mock_user_profiles.json`은 local/dev fixture로만 사용한다.

### read 경로
1. `LOVV_PROFILE_ENABLED=true`이면 Profile Agent는 `LOVV_PROFILE_TABLE`에서 actor별 profile을 읽는다.
2. DynamoDB key shape는 `PK=ACTOR#{actorId}`, `SK=PROFILE#v1`이다.
3. DynamoDB read 실패, missing item, malformed item은 추천 흐름을 실패시키지 않고 cold profile(`None`)로 degrade한다.
4. 테스트/fixture 실행에서는 state의 `profile.lovv_user_profile` 또는 `profile.mock_profile`을 허용한다. 이 값은 live DynamoDB보다 우선하는 운영 계약이 아니라 local injection seam이다.

### Saved itinerary evidence tool 상태

`src/lovv_agent_v2/agents/profile/rds_mysql_tool.py`에는 MySQL 저장 일정 신호를 profile evidence로 읽는 `RdsSavedItinerarySignalsTool`이 있다. 이 도구는 다음 RDS/MySQL 테이블을 읽어 `saved_trip_count`, 최근 저장 일정, 좋아요 일정, 일정 item snapshot을 evidence로 만든다.

- `itineraries`
- `itinerary_items`
- `plan_reactions`

현재 구현은 SQL client protocol을 주입받는 source-level 도구이며, 안전한 table identifier 검증과 `recent_limit`/`liked_limit` 상한을 둔다. 테스트는 `tests/v2/test_profile_rds_mysql_tool.py`가 담당한다.

배포 경계: 이 도구와 `rds_mysql_rows.py`는 현재 `src/lovv_agent_v2`와 `app/LovvAgentV2/lovv_agent_v2`에 동일하게 존재한다. 다만 AgentCore 배포 런타임에서 실제로 사용한다고 보려면 RDS 연결 설정, Secrets/IAM/VPC 배선, 호출 owner 연결을 별도 작업으로 완료해야 한다.

### write 경계
- 추천 실행 중 Profile Agent는 read-only다.
- `entry_type=itinerary_confirmed` 또는 동등한 확정 이벤트에서만 profile update 요청을 남긴다.
- hot aggregate profile(`LovvUserProfile`)에는 TTL을 두지 않는다. 장기 이벤트 이력은 별도 TTL 테이블로 분리한다.
- long-turn personalization event table은 `LovvUserMemoryEvent` 계열을 권장한다. key shape는 `PK=ACTOR#{actorId}`, `SK=EVENT#{created_at_epoch}#{event_id}`, TTL field는 `expires_at` epoch seconds다.
- DAX는 필요한 경우 나중에 붙이는 cache layer이며 필수 table inventory가 아니다.

## 학습 공식 (reference)
```
observed_ratio = saved_theme_counts[t] / total_saved_theme_count
raw_weight     = 1 + alpha·(observed_ratio − 0.2)          # 0.2 = 1/5 균등 기준
learned_weight = clamp(raw_weight, 0.8, 1.3)
confidence     = min(saved_trip_count / 3, 1.0)            # 단, trips<3이면 effective=1(off)
effective      = 1 + confidence·(learned_weight − 1)
```
city_select: active 테마에 대해 effective를 **정규화**한 w[t]를 coverage에 사용. profile의 도시점수 영향은 **±cap(0.05) 클램프**.

## 검증된 동작 (offline 그리드)
- **하드 게이트 필수** — 활성 게이트 없으면 2건짜리 프로필(P03/P04)이 선택을 바꿔 대조군이 깨짐. 게이트 추가 시 **대조군 0** ✓.
- **대조군 항상 inert(0)**: 신규(P00)·콜드스타트(P01~04)·무선호 균등(P15·P19) → 어떤 config든 선택 불변.
- **medium에서 ~10/20 페르소나가 변경**, 페르소나당 ≤2케이스. 전부 **선호 테마 방향**(sea-lover→해안, art→art도시, history→history).
- **멀티테마 요청에서만 실효** — 단일테마는 정규화하면 불변.
- **cap·alpha는 거의 비결정적**; weight *범위*가 실질 레버(약 5/20, 중 10/20, 강 13/20).

## 한계·주의
- profile은 city_select의 **art→대도시 누수를 물려받음**(art 선호 프로필이 종로구류로 1건 밈) — scoring 아닌 데이터/태깅 이슈.
- 절대 변경 수는 cap 적용 세부에 따라 repo md(7/20)와 offline 재현(10/20)이 약간 다름; **패턴은 동일**(대조군 inert·범위>alpha>cap·art누수 제한).
- profile은 **active_themes를 절대 안 건드림**(선택 테마 *내*에서만 tilt). raw=결정권, profile=추천권.

## 통합 메모
- Intent→Profile agent가 request_theme_weights + profile effective를 결합 → city_select가 결합된 effective theme_weights를 소비(V2_15 변경 0). city_select는 결합 결과만 봄.
- RDS saved-itinerary evidence는 장기 profile 정본을 대체하지 않는다. DynamoDB `LovvUserProfile`은 hot aggregate source이고, RDS 도구는 저장 일정 기반 evidence supplement 후보로만 취급한다.
