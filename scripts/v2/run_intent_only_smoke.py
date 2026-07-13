#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["boto3"]
# ///
# How to run:
#   uv run python scripts/v2/run_intent_only_smoke.py --limit 3
#   uv run python scripts/v2/run_intent_only_smoke.py --live --limit 2

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from lovv_agent_v2.agents.intent.node import intent_node
from lovv_agent_v2.core.runtime_state import invocation_runtime
from lovv_agent_v2.infra.adapters.bedrock_converse import create_bedrock_converse_runtime
from lovv_agent_v2.infra.aws_clients import create_boto3_client_provider
from lovv_agent_v2.infra.config import (
    LLM_NODE_INTENT,
    RuntimeConfig,
    resolve_llm_model_id,
)

DEFAULT_ENV_FILE = Path(".env.v2.local")
DEFAULT_CASE_DIR = Path("docs/tasks/results/v2_intent_mocks/generation")
DEFAULT_OUT_DIR = Path("docs/tasks/results/v2_intent_only_smoke")
DEFAULT_CUSTOM_CASES_FILE = Path("docs/tasks/results/v2_intent_mocks/intent_only_custom_cases.json")


def main() -> int:
    args = parse_args()
    if args.live:
        load_env_file(args.env_file)
    runtime = live_runtime() if args.live else None
    cases = selected_cases(args)
    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    results = [run_case(case, runtime=runtime) for case in cases]
    index = {
        "run_id": run_id,
        "live": args.live,
        "case_count": len(results),
        "results": results,
    }
    write_json(out_dir / "index.json", index)
    for result in results:
        write_json(out_dir / f"{result['case_id']}.json", result)
        print(summary_line(result))
    print(out_dir.as_posix())
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run V2 intent node only.")
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--custom-cases-file", type=Path, default=DEFAULT_CUSTOM_CASES_FILE)
    parser.add_argument("--case", help="Generation mock id without .json suffix.")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--live", action="store_true", help="Use Bedrock intent LLM.")
    parser.add_argument(
        "--no-custom",
        action="store_true",
        help="Run generation mock cases only.",
    )
    return parser.parse_args()


def selected_cases(args: argparse.Namespace) -> tuple[dict[str, Any], ...]:
    generation_cases = tuple(
        generation_case_from_file(path)
        for path in selected_generation_files(
            args.case_dir,
            case_id=args.case,
            limit=args.limit,
        )
    )
    if args.no_custom:
        return generation_cases
    return (*generation_cases, *custom_cases(args.custom_cases_file))


def selected_generation_files(
    case_dir: Path,
    *,
    case_id: str | None,
    limit: int | None,
) -> tuple[Path, ...]:
    if case_id:
        path = case_dir / f"{case_id}.json"
        if not path.exists():
            raise FileNotFoundError(path)
        return (path,)
    files = tuple(
        path for path in sorted(case_dir.glob("*.json")) if is_generation_case_file(path)
    )
    return files[:limit] if limit is not None else files


def is_generation_case_file(path: Path) -> bool:
    try:
        payload = load_json(path)
    except json.JSONDecodeError:
        return False
    return isinstance(payload, Mapping) and "id" in payload and "intent_output" in payload


def generation_case_from_file(path: Path) -> dict[str, Any]:
    case = load_json(path)
    return {
        "case_id": str(case["id"]),
        "source": path.as_posix(),
        "state": state_from_generation_case(case),
    }


def state_from_generation_case(case: Mapping[str, Any]) -> dict[str, Any]:
    intent_output = mapping(case["intent_output"], "intent_output")
    return {
        "request": {
            "entryType": "create",
            "country": intent_output["country"],
            "travel_month": intent_output["travel_month"],
            "travel_year": intent_output["travel_year"],
            "trip_type": intent_output["trip_type"],
            "themes": list(sequence(intent_output["active_required_themes"])),
            "include_festivals": intent_output["include_festivals"],
            "naturalLanguageQuery": intent_output["cleaned_raw_query"],
            "softPreferenceQuery": intent_output.get("soft_preference_query", ""),
            "destination_id": intent_output.get("destination_id"),
            "user_location": intent_output.get("user_location"),
        },
    }


def custom_cases(path: Path = DEFAULT_CUSTOM_CASES_FILE) -> tuple[dict[str, Any], ...]:
    payload = load_json(path)
    cases = sequence(payload.get("cases", ()))
    return tuple(dict(mapping(case, "custom_case")) for case in cases)


def run_case(case: Mapping[str, Any], *, runtime: Mapping[str, Any] | None) -> dict[str, Any]:
    with invocation_runtime(runtime):
        output = intent_node(mapping(case["state"], "state"))
    return {
        "case_id": case["case_id"],
        "source": case["source"],
        "summary": summarize_output(output),
        "output": jsonable(output),
    }


def summarize_output(output: Mapping[str, Any]) -> dict[str, Any]:
    intent = mapping(output["intent"], "intent")
    modify = intent.get("modify_intent")
    modify_intent = modify if isinstance(modify, Mapping) else None
    city_input = intent.get("city_select_input")
    city_select_input = city_input if isinstance(city_input, Mapping) else None
    active_intent = modify_intent or intent
    return {
        "intent_type": active_intent.get("intent_type"),
        "status": active_intent.get("status"),
        "kind": active_intent.get("kind"),
        "routing_hint": active_intent.get("routing_hint"),
        "edit_ops_count": len(sequence(active_intent.get("edit_ops", ()))),
        "clarification_reason": clarification_reason(active_intent),
        "themes": list(sequence(city_select_input.get("active_required_themes", ()))) if city_select_input else [],
        "soft_preference_query": city_select_input.get("soft_preference_query") if city_select_input else None,
        "congestion_pref": city_select_input.get("congestion_pref") if city_select_input else None,
        "transport_pref": city_select_input.get("transport_pref") if city_select_input else None,
    }


def clarification_reason(intent: Mapping[str, Any]) -> str | None:
    clarification = intent.get("clarification")
    if not isinstance(clarification, Mapping):
        return None
    reason = clarification.get("reason_code")
    return reason if isinstance(reason, str) else None


def live_runtime() -> dict[str, Any]:
    config = RuntimeConfig.from_env()
    model_id = resolve_llm_model_id(config.llm, LLM_NODE_INTENT)
    if model_id is None:
        raise RuntimeError("LOVV_INTENT_LLM_MODEL_ID or LOVV_LLM_MODEL_ID is required")
    client = create_boto3_client_provider(config=config).create_bedrock_runtime_client()
    runtime = create_bedrock_converse_runtime(client=client, model_id=model_id)
    return {
        "intent_prompt_runtime": {
            "runtime": runtime,
            "schema_retry_limit": config.retries.schema_retry_limit,
        },
    }


def load_env_file(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as handle:
        for raw_line in handle:
            parsed = parse_env_line(raw_line)
            if parsed is not None:
                key, value = parsed
                os.environ[key] = value


def parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    key, value = line.split("=", 1)
    normalized_key = key.strip()
    normalized_value = value.strip().strip('"').strip("'")
    return (normalized_key, normalized_value) if normalized_key else None


def summary_line(result: Mapping[str, Any]) -> str:
    return json.dumps(
        {
            "case_id": result["case_id"],
            **mapping(result["summary"], "summary"),
        },
        ensure_ascii=False,
    )


def load_json(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    return mapping(value, path.as_posix())


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(jsonable(payload), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else ()


def jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [jsonable(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
