# Profile RDS MySQL Tool 검증 결과

## 결론

Profile RDS MySQL saved-itinerary tool 검증은 통과했다.

- 대상 tool: `RdsSavedItinerarySignalsTool`
- 대상 경로:
  - `src/lovv_agent_v2/agents/profile/rds_mysql_tool.py`
  - `src/lovv_agent_v2/agents/profile/rds_mysql_rows.py`
  - `app/LovvAgentV2/lovv_agent_v2/agents/profile/rds_mysql_tool.py`
  - `app/LovvAgentV2/lovv_agent_v2/agents/profile/rds_mysql_rows.py`
- 기존 runtime wiring 변경 여부: 변경 없음
- 실제 검증 시각: 2026-07-03T01:21:31Z

## 실행한 검증

| 검증 | 결과 | 로그 |
|---|---:|---|
| `uv run pytest tests/v2/test_profile_rds_mysql_tool.py tests/v2/test_profile_evidence.py` | PASS, 10 passed | `pytest_profile_rds.log` |
| `uv run python -m py_compile ...` | PASS | `py_compile.log` |
| `src` / `app` RDS tool parity `cmp` | PASS, identical | `src_app_parity.log` |
| 변경 파일 pure LOC 측정 | PASS, 모두 250 이하 | `pure_loc.log` |
| `git status --short` snapshot | captured | `git_status.log` |

## 검증 범위

이번 검증은 RDS MySQL tool이 기존 `SavedItinerarySignalsTool` 계약에 맞는 payload를 생성하는지 확인했다.

- `itineraries`에서 저장 일정 수와 최근 저장 일정을 조회한다.
- `plan_reactions`에서 좋아요 일정만 조회한다.
- `itinerary_items`에서 장소 상세 row를 병합한다.
- `itinerary_items` row가 없으면 `itinerary_json` snapshot의 `items` 또는 `stops`에서 장소 evidence를 fallback 추출한다.
- 결과 payload는 기존 `ProfileEvidenceResolver`와 함께 동작한다.

## 제한

라이브 RDS 접속 검증은 수행하지 않았다. 현재 요청 범위가 기존 runtime/Profile 코드를 수정하지 않는 isolated tool 생성이었고, 이번 검증은 주입형 SQL client를 통해 SQL 계약과 payload 변환을 확인하는 focused test로 수행했다.
