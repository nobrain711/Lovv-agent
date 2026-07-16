"""Invoke a DEPLOYED Lovv AgentCore Runtime (Tier 2 / Observability).

Unlike ``invoke_live_recommendation.py`` and ``capture_e2e_state.py`` — which run
the LangGraph in-process — this script calls the deployed AgentCore Runtime via
``bedrock-agentcore:InvokeAgentRuntime``. Only this path emits OTel spans through
the runtime's ADOT collector to X-Ray / CloudWatch, so it is required for the
Observability (NF-*, OB-*) sections of the test result report.

Each invocation returns a ``traceId`` which is printed and saved, so the report
can look the trace up in X-Ray ServiceLens (OB-04). Use ``--arn`` for V2; the
default ARN remains the historical V1 runtime for backward compatibility.

Examples:
    uv run python scripts/invoke_deployed_runtime.py \
        --input docs/tasks/results/agent_input_payloads/tc009_chat_nature_coast_quiet.json

    uv run python scripts/invoke_deployed_runtime.py \
        --input docs/tasks/results/v2_intent_mocks/generation/v2_gen_04_history_2d1n_live_payload.json \
        --arn arn:aws:bedrock-agentcore:us-east-1:925273580929:runtime/<V2_RUNTIME_ID> \
        --session-id lovv-v2-warm-0000000000000000000000 \
        --repeat 6

Requirements:
    - AWS credentials with ``bedrock-agentcore:InvokeAgentRuntime``
    - boto3/botocore recent enough to expose the ``bedrock-agentcore`` client
    - The runtime code must actually emit node spans/metrics for OB-01 to pass
      (instrumentation = SPEC Phase A; otherwise only auto-instrumented spans appear).
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import boto3

DEFAULT_ARN = (
    "arn:aws:bedrock-agentcore:us-east-1:925273580929:runtime/"
    "LovvAgentCore_LovvAgentV1-PumZyEGRsT"
)
DEFAULT_REGION = "us-east-1"
DEFAULT_QUALIFIER = "DEFAULT"
DEFAULT_OUT_DIR = Path("docs/tasks/results/deployed_agentcore_runtime")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Invoke a deployed Lovv AgentCore runtime.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--input", type=Path, help="One fixture JSON file.")
    src.add_argument("--input-dir", type=Path, help="Directory of fixture JSON files.")
    parser.add_argument("--arn", default=DEFAULT_ARN, help="AgentCore Runtime ARN.")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument(
        "--profile",
        default=None,
        help="AWS 프로필명. 미지정 시 기본 자격증명 체인(default 프로필/env/role) 사용.",
    )
    parser.add_argument("--qualifier", default=DEFAULT_QUALIFIER, help="Runtime endpoint qualifier.")
    parser.add_argument(
        "--session-id",
        default=None,
        help="AgentCore runtimeSessionId(33+자). **미지정(기본)=호출마다 새 세션→새 MicroVM(격리·콜드, 기능 테스트용)**. "
        "고정값 지정 시 모든 호출이 그 세션 공유→워밍 MicroVM 재사용(latency 측정용).",
    )
    parser.add_argument(
        "--graph-session-id",
        default=None,
        help="V2 payload sessionId. AgentCoreMemorySaver 검증용 graph session 식별자.",
    )
    parser.add_argument(
        "--graph-thread-id",
        default=None,
        help="V2 payload threadId. 생략하면 --graph-session-id를 사용.",
    )
    parser.add_argument(
        "--actor-id",
        default=None,
        help="V2 payload actorId. 생략하면 graph threadId를 사용.",
    )
    parser.add_argument(
        "--request-id",
        default=None,
        help="V2 payload requestId. 단일 fixture 실행에서 추적용으로 사용.",
    )
    parser.add_argument("--repeat", type=int, default=1, help="Repeat each input N times.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional path to write invocation rows.",
    )
    return parser.parse_args()


def _session_id() -> str:
    # AgentCore requires runtimeSessionId length >= 33; uuid4 hex with a prefix is safe.
    return f"lovv-test-{uuid.uuid4().hex}"


def payload_with_graph_ids(
    payload: Mapping[str, Any],
    *,
    graph_session_id: str | None,
    graph_thread_id: str | None,
    actor_id: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    enriched = dict(payload)
    if graph_session_id is not None:
        enriched["sessionId"] = graph_session_id
    thread_id = graph_thread_id or graph_session_id
    if thread_id is not None:
        enriched["threadId"] = thread_id
    resolved_actor_id = actor_id or thread_id
    if resolved_actor_id is not None:
        enriched["actorId"] = resolved_actor_id
    if request_id is not None:
        enriched["requestId"] = request_id
    return enriched


def _read_response_body(response: Any) -> Any:
    """Read a buffered StreamingBody or a streamed EventStream into text/JSON."""

    body = response.get("response")
    if body is None:
        return None
    if hasattr(body, "read"):  # botocore StreamingBody (buffered)
        raw = body.read()
        text = raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
    else:  # EventStream (chunked) — concatenate chunk payloads
        chunks: list[str] = []
        for event in body:
            if isinstance(event, (bytes, bytearray)):
                chunks.append(event.decode("utf-8"))
            elif isinstance(event, dict):
                part = event.get("chunk", {}).get("bytes") or event.get("bytes")
                if isinstance(part, (bytes, bytearray)):
                    chunks.append(part.decode("utf-8"))
        text = "".join(chunks)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def invoke_one(
    client: Any,
    *,
    arn: str,
    qualifier: str,
    payload: dict[str, Any],
    session_id: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    response = client.invoke_agent_runtime(
        agentRuntimeArn=arn,
        qualifier=qualifier,
        runtimeSessionId=session_id,
        contentType="application/json",
        payload=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )
    return {
        "statusCode": response.get("statusCode"),
        "traceId": response.get("traceId"),
        "contentType": response.get("contentType"),
        "elapsedSeconds": round(time.perf_counter() - started, 3),
        "body": _read_response_body(response),
    }


def response_status(result: dict[str, Any]) -> str | None:
    body = result.get("body")
    if not isinstance(body, dict):
        return None
    value = body.get("responseStatus", body.get("status"))
    return value if isinstance(value, str) else None


def invoke_rows(
    client: Any,
    *,
    arn: str,
    qualifier: str,
    payload: dict[str, Any],
    fixture: str,
    repeat: int,
    fixed_session_id: str | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for iteration in range(1, repeat + 1):
        session_id = fixed_session_id or _session_id()
        result = invoke_one(
            client,
            arn=arn,
            qualifier=qualifier,
            payload=payload,
            session_id=session_id,
        )
        row = {
            "fixture": fixture,
            "iteration": iteration,
            "runtimeSessionId": session_id,
            "statusCode": result.get("statusCode"),
            "traceId": result.get("traceId"),
            "elapsedSeconds": result.get("elapsedSeconds"),
            "responseStatus": response_status(result),
            "body": result.get("body"),
        }
        rows.append(row)
        print(
            f"[ok] {fixture}#{iteration} status={row['statusCode']} "
            f"elapsed={row['elapsedSeconds']}s traceId={row['traceId']} "
            f"responseStatus={row['responseStatus']}",
        )
    return rows


def main() -> int:
    args = parse_args()
    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    client = session.client("bedrock-agentcore", region_name=args.region)
    if args.repeat < 1:
        print("--repeat must be >= 1", file=sys.stderr)
        return 2

    if args.input is not None:
        payload = payload_with_graph_ids(
            json.loads(args.input.read_text(encoding="utf-8")),
            graph_session_id=args.graph_session_id,
            graph_thread_id=args.graph_thread_id,
            actor_id=args.actor_id,
            request_id=args.request_id,
        )
        rows = invoke_rows(
            client,
            arn=args.arn,
            qualifier=args.qualifier,
            payload=payload,
            fixture=args.input.name,
            repeat=args.repeat,
            fixed_session_id=args.session_id,
        )
        out = args.out or output_path(args.out_dir, args.input.stem)
        out.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"summary -> {out}")
        return 0

    files = sorted(p for p in args.input_dir.glob("*.json"))
    summary: list[dict[str, Any]] = []
    for path in files:
        payload = payload_with_graph_ids(
            json.loads(path.read_text(encoding="utf-8")),
            graph_session_id=args.graph_session_id,
            graph_thread_id=args.graph_thread_id,
            actor_id=args.actor_id,
            request_id=args.request_id,
        )
        try:
            summary.extend(
                invoke_rows(
                    client,
                    arn=args.arn,
                    qualifier=args.qualifier,
                    payload=payload,
                    fixture=path.name,
                    repeat=args.repeat,
                    fixed_session_id=args.session_id,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - record per-fixture failure, continue batch.
            summary.append({"fixture": path.name, "error": str(exc)})
            print(f"[ERR] {path.name}  {exc}")

    out = args.out or (args.input_dir.parent / "deployed_invoke_trace_summary.json")
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsummary -> {out}")
    return 0


def output_path(out_dir: Path, label: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_label = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in label)
    return out_dir / f"{safe_label.strip('-') or 'deployed-runtime'}.json"


if __name__ == "__main__":
    raise SystemExit(main())
