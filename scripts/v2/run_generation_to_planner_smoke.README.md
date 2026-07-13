# run_generation_to_planner_smoke.py

V2 generation intent mock case를 live graph에 넣어 planner/response까지 확인하는 smoke runner다.

## 목적

- `docs/tasks/results/v2_intent_mocks/generation/*.json`의 `intent_output`을 front `/recommendations` payload로 변환해 graph 초기 state를 만든다.
- live runtime을 사용해 city_select, planner, response_packager까지 실행한다.
- intent/profile 팀 작업을 건드리지 않고 테스트하려면 `--mock-contract-nodes`를 사용한다.

## 기본 실행

```powershell
uv run python scripts/v2/run_generation_to_planner_smoke.py --limit 1
```

```powershell
uv run python scripts/v2/run_generation_to_planner_smoke.py --case v2_gen_01_coast_quiet_2d1n
```

기본 실행은 production `intent_node`와 `profile_node`를 사용한다.

## Mock Contract Node 실행

```powershell
uv run python scripts/v2/run_generation_to_planner_smoke.py --mock-contract-nodes --case v2_gen_01_coast_quiet_2d1n
```

`--mock-contract-nodes`를 켜면 graph entry는 그대로 `intent`지만, production intent/profile 대신 임시 mock node를 사용한다.

- mock intent node: 변환된 `request`를 `intent.city_select_input`과 `intent.trip_intent`로 정규화한다.
- mock profile node: state에 들어온 mock profile record를 DB 조회 결과처럼 읽고 `theme_weights`를 주입한다.
- city_select 이후 노드는 live graph와 동일하게 실행한다.

## Profile 반영 여부

프로필을 반영하지 않으려면 `--actor-id`와 `--persona-id`를 생략한다.

```powershell
uv run python scripts/v2/run_generation_to_planner_smoke.py --mock-contract-nodes --case v2_gen_01_coast_quiet_2d1n
```

프로필을 반영하려면 `src/lovv_agent_v2/resources/mock_user_profiles.json`의 `profile_id` 또는 `actor_id`를 넘긴다.

```powershell
uv run python scripts/v2/run_generation_to_planner_smoke.py --mock-contract-nodes --case v2_gen_01_coast_quiet_2d1n --actor-id P05_three_trips_sea_threshold
```

`--persona-id`도 같은 lookup으로 처리된다.

```powershell
uv run python scripts/v2/run_generation_to_planner_smoke.py --mock-contract-nodes --case v2_gen_01_coast_quiet_2d1n --persona-id P05_three_trips_sea_threshold
```

## 주요 옵션

| 옵션 | 기본값 | 설명 |
|---|---:|---|
| `--env-file` | `.env.v2.local` | live AWS/runtime 설정을 읽는 env 파일 |
| `--case-dir` | `docs/tasks/results/v2_intent_mocks/generation` | intent mock case 디렉터리 |
| `--out-dir` | `docs/tasks/results/v2_generation_planner_smoke` | smoke 결과 저장 디렉터리 |
| `--case` | 없음 | 특정 case id 1건만 실행 |
| `--limit` | 없음 | 정렬된 case 중 앞 N건만 실행 |
| `--profiles` | `src/lovv_agent_v2/resources/mock_user_profiles.json` | mock profile record store |
| `--actor-id` | 없음 | mock profile lookup key |
| `--persona-id` | 없음 | `--actor-id`와 같은 용도의 alias |
| `--mock-contract-nodes` | off | production intent/profile 대신 임시 mock contract node 사용 |

## 출력

실행이 끝나면 stdout에 run directory가 출력된다.

```text
docs/tasks/results/v2_generation_planner_smoke/<run_id>
```

생성 파일:

- `index.json`: 실행 case 목록과 요약
- `<case_id>.json`: case별 요약

요약에는 아래 값을 포함한다.

- `response_status`
- `selected_city`
- `selection_reason_code`
- `festival_gate`
- `planner_fallback`
- `planner_output`
- `planner_validation`
- `response_payload`

## 해석 기준

- `response_payload`가 있으면 response_packager까지 도달한 것이다.
- `planner_fallback.used=true`면 planner가 primary city를 그대로 쓰지 않고 alternative fallback을 사용한 것이다.
- `selected_city.selection_reason_code`와 top-level `selection_reason_code`는 서로 다른 단계의 근거일 수 있다.
- profile 적용 여부는 결과의 `intent.city_select_input.theme_weights` 또는 city_select score 변화를 통해 확인한다.

## 주의

- 이 스크립트는 live harness를 사용하므로 `.env.v2.local`과 AWS 접근 권한이 필요하다.
- `--mock-contract-nodes`는 intent/profile 팀 작업을 우회하기 위한 임시 경로다.
- 일정 수정 intent까지 포함한 full graph smoke는 별도 modify fixture와 계약이 확정된 뒤 같은 방식으로 확장한다.
