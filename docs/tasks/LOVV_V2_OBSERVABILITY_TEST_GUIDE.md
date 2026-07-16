# LOVV V2 Observability Test Guide

작성일: 2026-07-08

이 문서는 V2 live harness 실행 후 observability 로그를 수집하고, 결과 파일을 분석하는 절차를 정리한다. 대상은 `src/lovv_agent_v2` 및 배포 mirror `app/LovvAgentV2`에 적용된 V2 observability이다.

## 1. 관측 대상

V2 runtime은 실행 중 아래 JSON line 로그를 stdout/CloudWatch에 출력한다.

| logType | 의미 | 주요 확인값 |
| --- | --- | --- |
| `AGENT_NODE_METRIC` | LangGraph node/내부 step 실행 시간 | `nodeName`, `durationMs`, `status`, `inputSummary`, `outputSummary` |
| `AGENT_INVOCATION_METRIC` | 요청 1건 전체 실행 시간 | `durationMs`, `status`, `responseStatus`, `toolMetrics`, `traceSummary` |
| `AGENT_LIFECYCLE_METRIC` | 사용자 흐름 상태 | `lifecycleType=modify/weather/clarification`, `event`, `details` |
| `AGENT_MEMORY_GUARD` | memory/checkpointer 비용 위험 guard | `memorySaverType`, `memoryEnabled`, `hasMoreEvents` |

중요: observability 로그는 checkpoint state에 누적하지 않는다. 따라서 metric 출력 자체가 `AgentCoreMemorySaver` event write 수를 늘리지는 않는다. 단, AgentCore Memory가 켜진 경우 memory guard가 invocation당 `ListEvents` 1페이지를 읽을 수 있다.

## 2. 실행 전 확인

로컬 live test에서 AgentCore Memory 과금을 피하려면 `.env.v2.local`에서 memory off 경로를 사용한다.

```powershell
Select-String -Path .env.v2.local -Pattern "LOVV_MEMORY|AGENTCORE|MEMORY"
```

권장:

```text
LOVV_MEMORY_ENABLED=false
```

필수 AWS 의존성:

- Bedrock embedding/runtime
- S3 Vectors
- DynamoDB
- ORS 사용 시 ORS credential 또는 AgentCore credential resolver

## 3. 단일 요청 실행

일반 live smoke runner를 사용한다.

```powershell
.venv\Scripts\python.exe scripts\v2\run_general_live_smoke.py `
  --input docs\tasks\results\v2_intent_mocks\generation\v2_gen_04_history_2d1n.json `
  --session-id obs-guide-create-001 `
  --actor-id local-observer `
  --request-id obs-guide-create-001 `
  --label create-history `
  --out-dir docs\tasks\results\v2_observability_manual
```

결과 JSON은 `--out-dir` 아래에 생성된다. stdout에 출력되는 `AGENT_*` JSON line은 터미널에 표시된다.

## 4. stdout 로그 파일로 저장

PowerShell에서는 `Tee-Object`로 stdout을 파일에도 남긴다.

```powershell
$out = "docs\tasks\results\v2_observability_manual"
New-Item -ItemType Directory -Force $out | Out-Null

.venv\Scripts\python.exe scripts\v2\run_general_live_smoke.py `
  --input docs\tasks\results\v2_intent_mocks\generation\v2_gen_04_history_2d1n.json `
  --session-id obs-guide-create-002 `
  --actor-id local-observer `
  --request-id obs-guide-create-002 `
  --label create-history `
  --out-dir $out |
  Tee-Object -FilePath "$out\create-history.stdout.log"
```

수정 요청은 같은 `session-id`와 `actor-id`를 유지해야 checkpointer state를 이어받는다.

```powershell
.venv\Scripts\python.exe scripts\v2\run_general_live_smoke.py `
  --input docs\tasks\results\v2_intent_mocks\modify\v2_modify_slot_replace_queryless.json `
  --session-id obs-guide-create-002 `
  --actor-id local-observer `
  --request-id obs-guide-modify-002 `
  --label modify-slot `
  --out-dir $out |
  Tee-Object -FilePath "$out\modify-slot.stdout.log"
```

## 5. 로그 파일 빠른 분석

JSON line만 파싱해서 log type 수를 확인한다.

```powershell
$entries = Get-Content "$out\create-history.stdout.log" |
  Where-Object { $_ -like "{*" } |
  ForEach-Object { $_ | ConvertFrom-Json }

$entries | Group-Object logType | Select-Object Name, Count
```

가장 오래 걸린 node/step을 확인한다.

```powershell
$entries |
  Where-Object { $_.logType -eq "AGENT_NODE_METRIC" } |
  Sort-Object durationMs -Descending |
  Select-Object -First 10 nodeName, durationMs, status
```

요청 전체 시간과 AWS/외부 tool latency aggregate를 확인한다.

```powershell
$invocation = $entries | Where-Object { $_.logType -eq "AGENT_INVOCATION_METRIC" } | Select-Object -Last 1
$invocation | Select-Object requestId, durationMs, status, responseStatus
$invocation.toolMetrics
```

modify/weather/clarification lifecycle을 확인한다.

```powershell
$entries |
  Where-Object { $_.logType -eq "AGENT_LIFECYCLE_METRIC" } |
  Select-Object lifecycleType, event, details
```

memory guard를 확인한다.

```powershell
$entries |
  Where-Object { $_.logType -eq "AGENT_MEMORY_GUARD" } |
  Select-Object level, memorySaverType, memoryEnabled, eventPageCount, hasMoreEvents
```

## 6. 결과 JSON 확인

runner가 만든 결과 JSON에서 public response 상태를 확인한다.

```powershell
$result = Get-ChildItem $out -Filter "*create-history*.json" |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

$payload = Get-Content $result.FullName -Raw | ConvertFrom-Json
$payload.responseStatus
$payload.response.destination
$payload.response.clarification
```

일정 생성/수정 성공 판정:

- `responseStatus = "modification_pending"` 또는 생성 완료 응답이면 정상 완료.
- `responseStatus = "END_WAIT_USER"`이면 clarification interrupt가 정상 발생한 것이다.
- `response.clarification.options[].helperText`가 있으면 front 표시 문구까지 포함된 상태이다.

## 7. E2E 단일 JSON 캡처

`run_general_live_smoke.py`는 response JSON과 stdout 로그를 분리해서 남긴다. 특정 이슈를 재현하며 한 파일 안에서 public response, `AGENT_*` 로그, 로컬 span 목록, public 출처 필드 노출 여부를 같이 확인하려면 아래처럼 inline capture를 사용한다.

주의:

- live AWS 호출이므로 sandbox 밖에서 실행한다.
- 비용/메모리 과금 방지를 위해 local live 검증에서는 `LOVV_MEMORY_ENABLED=false`를 강제한다.
- 이 캡처는 로컬 in-process span 확인용이다. AgentCore/X-Ray 화면에 표시되는 deployed trace 확인은 §10을 따른다.

```powershell
@'
import contextlib, datetime as dt, io, json, os
from pathlib import Path

for line in Path(".env.v2.local").read_text(encoding="utf-8").splitlines():
    stripped = line.strip()
    if stripped and not stripped.startswith("#") and "=" in stripped:
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

os.environ["LOVV_MEMORY_ENABLED"] = "false"
os.environ["LOVV_ENABLE_AGENTCORE_MEMORY"] = "false"
os.environ["AWS_REGION"] = os.environ.get("LOVV_AWS_REGION", "us-east-1")
os.environ["AWS_DEFAULT_REGION"] = os.environ.get("LOVV_AWS_REGION", "us-east-1")

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
try:
    from opentelemetry.sdk.trace.export import InMemorySpanExporter
except ImportError:
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

span_exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(span_exporter))
trace.set_tracer_provider(provider)

from lovv_agent_v2.agentcore_entrypoint import handle_v2_invocation

stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
session = f"sess-source-trace-{stamp.lower()}"
event = {
    "entryType": "create",
    "requestId": f"req-source-trace-{stamp.lower()}",
    "sessionId": session,
    "threadId": session,
    "actorId": "local-live-source-trace",
    "country": "KR",
    "travelYear": 2026,
    "travelMonth": 7,
    "tripType": "2d1n",
    "includeFestivals": False,
    "rawQuery": "7월에 동해 바다를 조용히 산책하는 1박 2일 여행을 추천해줘",
    "themes": ["바다·해안"],
    "preferredThemeIds": ["sea_coast"],
    "destinationId": "KR-51-170",
}

stdout = io.StringIO()
with contextlib.redirect_stdout(stdout):
    response = handle_v2_invocation(event)

logs = []
for line in stdout.getvalue().splitlines():
    try:
        entry = json.loads(line)
    except json.JSONDecodeError:
        continue
    if isinstance(entry, dict):
        logs.append(entry)

spans = [
    {
        "name": span.name,
        "status": str(span.status.status_code).split(".")[-1],
        "spanId": f"{span.context.span_id:016x}",
        "traceId": f"{span.context.trace_id:032x}",
    }
    for span in span_exporter.get_finished_spans()
]

items = [
    item
    for day in response.get("itinerary", {}).get("days", [])
    for item in day.get("items", [])
]
source_probe = [
    {
        "title": item.get("title"),
        "publicKeys": sorted(item.keys()),
        "contentId": item.get("contentId"),
        "source": item.get("source"),
        "sourceType": item.get("sourceType"),
        "sourceUrl": item.get("sourceUrl"),
        "evidence": item.get("evidence"),
        "links": item.get("links"),
        "indoorOutdoor": item.get("indoorOutdoor"),
    }
    for item in items[:5]
]

payload = {
    "capturedAt": stamp,
    "event": event,
    "response": response,
    "sourceFieldProbe": {
        "topLevelLinks": response.get("links"),
        "festivalDateVerifications": response.get("festivalDateVerifications"),
        "itemSamples": source_probe,
    },
    "logs": logs,
    "spanSummary": spans,
    "summary": {
        "logCount": len(logs),
        "nodeMetricCount": sum(1 for entry in logs if entry.get("logType") == "AGENT_NODE_METRIC"),
        "lifecycleMetricCount": sum(1 for entry in logs if entry.get("logType") == "AGENT_LIFECYCLE_METRIC"),
        "spanCount": len(spans),
        "spanNames": [span["name"] for span in spans],
        "clarificationReason": (response.get("clarification") or {}).get("reasonCode"),
        "destination": response.get("destination"),
        "itemCount": len(items),
    },
}

out_dir = Path("docs/tasks/results/v2_e2e_trace_live")
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / f"{stamp}_source_trace_e2e.json"
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(out_path)
print(json.dumps(payload["summary"], ensure_ascii=False, indent=2))
'@ | .venv\Scripts\python.exe -
```

생성된 JSON에서 바로 확인할 항목:

```powershell
$path = "docs\tasks\results\v2_e2e_trace_live\20260710T081655Z_source_trace_e2e.json"
$payload = Get-Content $path -Raw | ConvertFrom-Json
$payload.summary
$payload.sourceFieldProbe.topLevelLinks
$payload.sourceFieldProbe.itemSamples | Select-Object title, contentId, source, sourceType, sourceUrl, evidence, links
$payload.spanSummary | Select-Object name, status
$payload.logs | Group-Object logType | Select-Object Name, Count
```

2026-07-10 기준 샘플:

```text
docs/tasks/results/v2_e2e_trace_live/20260710T081655Z_source_trace_e2e.json
```

관측값:

- `spanCount`: 21
- `AGENT_NODE_METRIC`: 15
- `AGENT_LIFECYCLE_METRIC`: 3
- 주요 span: `LovvAgentInvocation`, `node.intent`, `node.planner.retrieve_places`, `node.planner.route_days`, `node.explain_itinerary`, `node.response_packager`, `s3vectors.QueryVectors`, `dynamodb.BatchGetItem`, `BedrockConverse`
- public response의 `links`: `{}`
- public itinerary item의 `source`, `sourceType`, `sourceUrl`, `evidence`, `links`: 현재 `null`
- public item에서 출처를 추적할 수 있는 값은 현재 `contentId` 정도다.

## 8. 기존 live E2E 예시

기준 결과:

```text
docs/tasks/results/v2_observability_live_e2e/20260708T160734Z/
```

포함 파일:

- `weather-create-v2.stdout.log`
- `modify-slot-v2.stdout.log`
- `weather-resume-chain-v3.stdout.log`
- `observability_summary.json`

확인된 관측값:

- `AGENT_NODE_METRIC`: intent, planner 내부 step, explain, response packager.
- `AGENT_INVOCATION_METRIC`: create, modify, clarification resume 전체 duration.
- `AGENT_LIFECYCLE_METRIC`: weather evaluated, clarification waiting, modify applied.
- `toolMetrics`: `bedrock.Converse`, `bedrock.InvokeModel`, `dynamodb.BatchGetItem`, `s3vectors.QueryVectors`, `ors.SnapPlaces`, `ors.GetMatrix`.
- `AGENT_MEMORY_GUARD`: local memory saver 또는 AgentCore memory event page 상태.

## 9. 분석 기준

우선 확인할 항목:

1. `AGENT_INVOCATION_METRIC.durationMs`
   - 사용자가 체감하는 총 응답 시간.
2. `toolMetrics`
   - Bedrock, S3Vectors, DynamoDB, ORS 중 병목이 어디인지 확인.
3. `AGENT_NODE_METRIC` 상위 `durationMs`
   - graph 내부에서 오래 걸리는 node/step 식별.
4. `AGENT_LIFECYCLE_METRIC`
   - modify/weather/clarification이 의도한 branch를 탔는지 확인.
5. `AGENT_MEMORY_GUARD`
   - AgentCore Memory event page가 비정상적으로 커지는지 확인.

위험 신호:

- `AGENT_INVOCATION_METRIC.status != "success"`
- 동일 요청에서 `AGENT_NODE_METRIC`의 같은 node pair가 반복됨.
- `AGENT_MEMORY_GUARD.hasMoreEvents = true`
- `toolMetrics.bedrock.Converse.maxMs` 또는 `ors.GetMatrix.maxMs`가 전체 지연 대부분을 차지함.
- clarification이 필요한 케이스인데 `END_WAIT_USER`가 아닌 완료 응답으로 내려감.

## 10. CloudWatch에서 확인할 때

배포 runtime에서는 같은 JSON line이 CloudWatch Logs에 남는다. Logs Insights에서는 `logType` 기준으로 필터링한다.

```sql
fields @timestamp, requestId, logType, nodeName, durationMs, status, responseStatus
| filter logType in ["AGENT_INVOCATION_METRIC", "AGENT_NODE_METRIC", "AGENT_LIFECYCLE_METRIC", "AGENT_MEMORY_GUARD"]
| sort @timestamp desc
| limit 100
```

특정 request 기준:

```sql
fields @timestamp, logType, nodeName, lifecycleType, event, durationMs, status
| filter requestId = "obs-guide-create-002"
| sort @timestamp asc
```

외부 tool 병목은 `AGENT_INVOCATION_METRIC.toolMetrics`를 펼쳐서 확인한다. CloudWatch Logs Insights에서 nested JSON 집계가 불편하면, stdout log를 내려받아 §5의 PowerShell 분석 절차를 사용한다.

## 11. 운영 메모

- live test를 많이 반복할 때는 memory off local harness로 라우팅/성능 문제를 먼저 해결한다.
- AgentCore Memory를 켠 검증은 session 수와 반복 횟수를 제한한다.
- observability field는 public response contract가 아니다. front/backend API 구현은 response payload를 기준으로 하고, `AGENT_*` 로그는 운영 진단용으로만 사용한다.
- `app/LovvAgentV2`는 deploy mirror이다. `src/lovv_agent_v2` 변경 검증 후 deploy 전에 mirror 반영 여부를 확인한다.
