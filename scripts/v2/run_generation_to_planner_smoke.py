#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = ["boto3"]
# ///
# How to run:
#   uv run python scripts/v2/run_generation_to_planner_smoke.py --limit 1
#   uv run python scripts/v2/run_generation_to_planner_smoke.py --case v2_gen_01_coast_quiet_2d1n

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from lovv_agent_v2.agentcore_entrypoint import extract_graph_payload
from lovv_agent_v2.core.mock_graph import compile_v2_mock_graph
from lovv_agent_v2.harness import LovvLangGraphV2Harness, build_live_harness

DEFAULT_ENV_FILE = Path(".env.v2.local")
DEFAULT_CASE_DIR = Path("docs/tasks/results/v2_intent_mocks/generation")
DEFAULT_OUT_DIR = Path("docs/tasks/results/v2_generation_planner_smoke")
DEFAULT_PROFILES_FILE = Path("src/lovv_agent_v2/resources/mock_user_profiles.json")


def main() -> int:
    args = parse_args()
    load_env_file(args.env_file)
    cases = select_cases(args.case_dir, case_id=args.case, limit=args.limit)
    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    profile_record = load_profile_record(args.profiles, args.actor_id or args.persona_id)
    harness = build_smoke_harness(use_mock_contract_nodes=args.mock_contract_nodes)
    summaries: list[dict[str, Any]] = []
    for case_file in cases:
        case = load_case(case_file)
        case_id = str(case["id"])
        initial_state = build_initial_state(case, profile_record=profile_record)
        result = invoke_harness(
            harness,
            initial_state,
            case_id=case_id,
            actor_id=args.actor_id or args.persona_id or "v2-smoke",
        )
        summary = summarize_result(case_id, case_file, result)
        summaries.append(summary)
        write_json(out_dir / f"{case_id}.json", summary)

    index = {
        "run_id": run_id,
        "env_file": str(args.env_file),
        "case_count": len(summaries),
        "cases": summaries,
    }
    write_json(out_dir / "index.json", index)
    print(out_dir)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run V2 generation intent mocks through live graph to planner output.",
    )
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--case-dir", type=Path, default=DEFAULT_CASE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--case", help="Run one case id, without .json suffix.")
    parser.add_argument("--limit", type=int, help="Run the first N cases.")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES_FILE)
    parser.add_argument("--actor-id")
    parser.add_argument("--persona-id")
    parser.add_argument(
        "--mock-contract-nodes",
        action="store_true",
        help="Start graph from temporary mock intent/profile nodes.",
    )
    return parser.parse_args()


def build_smoke_harness(*, use_mock_contract_nodes: bool) -> LovvLangGraphV2Harness:
    if use_mock_contract_nodes:
        return build_mock_live_harness()
    return build_live_harness()


def build_mock_live_harness() -> LovvLangGraphV2Harness:
    live_harness = build_live_harness()
    return LovvLangGraphV2Harness(
        graph=compile_v2_mock_graph(),
        config=live_harness.config,
        runtime=live_harness.runtime,
        itinerary_explanation_runtime=live_harness.itinerary_explanation_runtime,
    )


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
    if not line or line.startswith("#"):
        return None
    if "=" not in line:
        return None
    key, value = line.split("=", 1)
    key = key.strip()
    value = value.strip().strip('"').strip("'")
    return (key, value) if key else None


def mirror_aws_region(env: Mapping[str, str]) -> None:
    region = env.get("LOVV_AWS_REGION")
    if not region:
        return
    os.environ.setdefault("AWS_REGION", region)
    os.environ.setdefault("AWS_DEFAULT_REGION", region)


def select_cases(case_dir: Path, *, case_id: str | None, limit: int | None) -> tuple[Path, ...]:
    if case_id:
        path = case_dir / f"{case_id}.json"
        if not path.exists():
            raise FileNotFoundError(path)
        return (path,)
    cases = tuple(sorted(case_dir.glob("*.json")))
    return cases[:limit] if limit is not None else cases


def load_case(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise TypeError(f"case must be a JSON object: {path}")
    if "id" not in payload or "intent_output" not in payload:
        raise KeyError(f"case requires id and intent_output: {path}")
    return payload


def build_initial_state(
    case: Mapping[str, Any],
    *,
    profile_record: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    intent_output = case["intent_output"]
    if not isinstance(intent_output, Mapping):
        raise TypeError("intent_output must be an object")
    case_id = str(case["id"])
    state = extract_graph_payload(
        _front_request_from_intent_output(intent_output),
        request_id=case_id,
    )
    if profile_record:
        state["profile"] = {"profile_record": dict(profile_record)}
    return state


def _front_request_from_intent_output(intent_output: Mapping[str, Any]) -> dict[str, Any]:
    payload = {
        "entryType": "create",
        "country": intent_output["country"],
        "travelMonth": intent_output["travel_month"],
        "travelYear": intent_output.get("travel_year"),
        "tripType": intent_output["trip_type"],
        "themes": list(intent_output["active_required_themes"]),
        "includeFestivals": intent_output["include_festivals"],
        "naturalLanguageQuery": intent_output["cleaned_raw_query"],
        "destinationId": intent_output.get("destination_id"),
        "userLocation": intent_output.get("user_location"),
    }
    return {key: value for key, value in payload.items() if value is not None}


def load_profile_record(path: Path, actor_id: str | None) -> Mapping[str, Any] | None:
    if actor_id is None:
        return None
    store = load_profile_store(path)
    records = store.get("records")
    if not isinstance(records, list):
        raise TypeError(f"profile store requires records: {path}")
    candidates = {actor_id}
    if not actor_id.startswith("mock://profile/"):
        candidates.add(f"mock://profile/{actor_id}")
    for record in records:
        if not isinstance(record, Mapping):
            continue
        if record.get("actor_id") in candidates or record.get("profile_id") == actor_id:
            return record
    raise KeyError(f"unknown profile actor_id: {actor_id}")


def load_profile_store(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, Mapping):
        raise TypeError(f"profile store must be a JSON object: {path}")
    return payload


def invoke_harness(
    harness: LovvLangGraphV2Harness,
    initial_state: dict[str, Any],
    *,
    case_id: str,
    actor_id: str,
) -> Mapping[str, Any]:
    result = harness.invoke(
        initial_state,
        graph_config={
            "configurable": {
                "thread_id": f"v2-smoke-{case_id}",
                "actor_id": actor_id,
            },
        },
    )
    if not isinstance(result, Mapping):
        raise TypeError("harness result must be a mapping")
    return result


def summarize_result(case_id: str, case_file: Path, result: Mapping[str, Any]) -> dict[str, Any]:
    city_select = mapping_or_empty(result.get("city_select"))
    city_result = mapping_or_empty(city_select.get("city_selection_result"))
    planner = mapping_or_empty(result.get("planner"))
    interrupt_response = interrupt_payload(result)
    response = interrupt_response or mapping_or_empty(result.get("response"))
    festival_gate = mapping_or_empty(result.get("festival_gate"))
    return {
        "case_id": case_id,
        "case_file": str(case_file),
        "response_status": (
            "END_WAIT_USER"
            if interrupt_response is not None
            else response.get("response_status")
        ),
        "selected_city": jsonable(city_result.get("selected_city")),
        "selection_reason_code": jsonable(city_result.get("selection_reason_code")),
        "festival_gate": jsonable(festival_gate.get("result")),
        "planner_fallback": jsonable(planner.get("fallback")),
        "planner_output": jsonable(planner.get("planner_output")),
        "planner_validation": jsonable(planner.get("validation_result")),
        "response_payload": jsonable(
            response if interrupt_response is not None else response.get("response_payload"),
        ),
    }


def mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def interrupt_payload(result: Mapping[str, Any]) -> Mapping[str, Any] | None:
    interrupts = result.get("__interrupt__")
    if not isinstance(interrupts, (list, tuple)) or not interrupts:
        return None
    value = getattr(interrupts[0], "value", None)
    return value if isinstance(value, Mapping) else None


def jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
