#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["boto3"]
# ///
# How to run:
#   uv run python scripts/v2/run_general_live_smoke.py --input event.json --session-id smoke-001
#   uv run python scripts/v2/run_general_live_smoke.py --input modify.json --session-id smoke-001 --actor-id user-001

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from lovv_agent_v2.agentcore_entrypoint import handle_v2_invocation

DEFAULT_ENV_FILE = Path(".env.v2.local")
DEFAULT_OUT_DIR = Path("docs/tasks/results/v2_general_live_smoke")


def main() -> int:
    args = parse_args()
    load_env_file(args.env_file)
    event = event_with_runtime_ids(
        load_json_object(args.input),
        session_id=args.session_id,
        thread_id=args.thread_id,
        actor_id=args.actor_id,
        request_id=args.request_id,
    )
    started_at = dt.datetime.now(dt.UTC)
    response = handle_v2_invocation(event)
    summary = summarize_response(event, response, started_at=started_at)
    out_path = output_path(args.out_dir, args.label, started_at)
    write_json(out_path, {"event": event, "response": response, "summary": summary})
    print(out_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run any V2 AgentCore-compatible event through the live harness.",
    )
    parser.add_argument("--input", type=Path, required=True, help="JSON event/request file.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--thread-id")
    parser.add_argument("--actor-id")
    parser.add_argument("--request-id")
    parser.add_argument("--label", default="general-live")
    return parser.parse_args()


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            parsed = parse_env_line(raw_line)
            if parsed is None:
                continue
            key, value = parsed
            os.environ[key] = value
    mirror_aws_region(os.environ)


def parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, value = line.split("=", 1)
    normalized_key = key.strip()
    normalized_value = value.strip().strip('"').strip("'")
    return (normalized_key, normalized_value) if normalized_key else None


def mirror_aws_region(env: Mapping[str, str]) -> None:
    region = env.get("LOVV_AWS_REGION")
    if not region:
        return
    os.environ.setdefault("AWS_REGION", region)
    os.environ.setdefault("AWS_DEFAULT_REGION", region)


def load_json_object(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise TypeError(f"input must be a JSON object: {path}")
    return payload


def event_with_runtime_ids(
    event: Mapping[str, Any],
    *,
    session_id: str,
    thread_id: str | None,
    actor_id: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    enriched = dict(event)
    enriched["sessionId"] = session_id
    enriched["threadId"] = thread_id or session_id
    if actor_id is not None:
        enriched["actorId"] = actor_id
    if request_id is not None:
        enriched["requestId"] = request_id
    else:
        enriched.setdefault("requestId", f"{session_id}-{entry_type(enriched)}")
    return enriched


def entry_type(event: Mapping[str, Any]) -> str:
    value = event.get("entryType", event.get("entry_type", "event"))
    return value if isinstance(value, str) and value.strip() else "event"


def summarize_response(
    event: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    started_at: dt.datetime,
) -> dict[str, Any]:
    destination = _mapping(response.get("destination"))
    itinerary = _mapping(response.get("itinerary"))
    days = itinerary.get("days")
    return {
        "entryType": entry_type(event),
        "sessionId": event.get("sessionId"),
        "threadId": event.get("threadId"),
        "actorId": event.get("actorId"),
        "requestId": event.get("requestId"),
        "elapsedSeconds": round((dt.datetime.now(dt.UTC) - started_at).total_seconds(), 3),
        "recommendationId": response.get("recommendationId"),
        "destinationId": destination.get("destinationId"),
        "destinationName": destination.get("name"),
        "dayCount": len(days) if isinstance(days, list) else 0,
        "itemCount": item_count(days),
        "clarificationReason": clarification_reason(response),
    }


def item_count(days: Any) -> int:
    if not isinstance(days, list):
        return 0
    return sum(
        len(day.get("items", ()))
        for day in days
        if isinstance(day, Mapping) and isinstance(day.get("items"), list)
    )


def clarification_reason(response: Mapping[str, Any]) -> str | None:
    clarification = response.get("clarification")
    if not isinstance(clarification, Mapping):
        return None
    value = clarification.get("reasonCode", clarification.get("reason_code"))
    return value if isinstance(value, str) else None


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def output_path(out_dir: Path, label: str, started_at: dt.datetime) -> Path:
    run_id = started_at.strftime("%Y%m%dT%H%M%SZ")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{run_id}_{safe_label(label)}.json"


def safe_label(label: str) -> str:
    normalized = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in label)
    return normalized.strip("-") or "general-live"


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
