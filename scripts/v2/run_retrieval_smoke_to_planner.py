#!/usr/bin/env python3
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# How to run:
#   uv run python scripts/v2/run_retrieval_smoke_to_planner.py --smoke-dir docs/tasks/results/v2_retrieval_smoke/20260630T094517 --limit 3

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lovv_agent_v2.tools.travel_time_provider import HaversineTravelTimeProvider
from lovv_agent_v2.agents.planner.subgraph import compile_planner_subgraph
from lovv_agent_v2.tools.runtime_containers import PlannerRuntimeTools

DEFAULT_OUT_DIR = Path("docs/tasks/results/v2_retrieval_planner_smoke")
RAW_VECTOR = (0.0,)
SOFT_VECTOR = (1.0,)


@dataclass(frozen=True, slots=True)
class SmokePlannerCase:
    case_id: str
    selected_ddb_pk: str
    smoke: Mapping[str, Any]
    transport_pref: str


@dataclass(frozen=True, slots=True)
class SmokeDestinationSearch:
    raw_candidates: tuple[Mapping[str, Any], ...]
    soft_candidates: tuple[Mapping[str, Any], ...]

    def search_candidates(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
    ) -> tuple[Mapping[str, Any], ...]:
        del city_id, ddb_pk, theme
        candidates = self.soft_candidates if tuple(query_vector) == SOFT_VECTOR else self.raw_candidates
        return candidates[:top_k]


@dataclass(frozen=True, slots=True)
class SmokeEmbedding:
    def embed_query(self, query: str) -> tuple[float, ...]:
        del query
        return SOFT_VECTOR


def main() -> int:
    args = parse_args()
    selected = load_selected_cities(args.selected_cities or args.smoke_dir / "selected_cities.json")
    run_id = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    for path in select_case_files(args.smoke_dir, case_id=args.case, limit=args.limit):
        smoke = load_mapping(path)
        case_id = text(smoke.get("case_id", path.stem), "case_id")
        selected_ddb_pk = selected.get(case_id)
        if selected_ddb_pk is None:
            summaries.append(
                {
                    "case_id": case_id,
                    "case_file": str(path),
                    "skipped": True,
                    "reason": "missing_selected_city",
                },
            )
            continue
        result = run_case(
            SmokePlannerCase(
                case_id=case_id,
                selected_ddb_pk=selected_ddb_pk,
                smoke=smoke,
                transport_pref=args.transport_pref,
            ),
        )
        summary = summarize_result(case_id, path, result)
        summaries.append(summary)
        write_json(out_dir / f"{case_id}.json", summary)

    write_json(out_dir / "index.json", {"run_id": run_id, "smoke_dir": str(args.smoke_dir), "cases": summaries})
    print(out_dir)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run saved V2 retrieval smoke candidates through the real planner.")
    parser.add_argument("--smoke-dir", type=Path, required=True)
    parser.add_argument("--selected-cities", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--case", help="Run one retrieval smoke case id, without .json suffix.")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--transport-pref", default="unknown")
    return parser.parse_args()


def run_case(case: SmokePlannerCase) -> Mapping[str, Any]:
    return compile_planner_subgraph().invoke(build_planner_state(case))


def build_planner_state(case: SmokePlannerCase) -> dict[str, Any]:
    raw_candidates = planner_candidates(case.smoke, case.selected_ddb_pk, channel="raw")
    soft_candidates = planner_candidates(case.smoke, case.selected_ddb_pk, channel="soft")
    selected_city = selected_city_payload(case.selected_ddb_pk, raw_candidates or soft_candidates)
    return {
        "intent": {"city_select_input": city_select_input(case, selected_city)},
        "city_select": {
            "city_selection_result": {
                "selected_city": selected_city,
                "seeds": (),
                "planner_hints": {"raw_query_vector": RAW_VECTOR},
            },
        },
        "planner": {
            "scratch": {
                "runtime": PlannerRuntimeTools(
                    destination_search=SmokeDestinationSearch(raw_candidates, soft_candidates),
                    embedding=SmokeEmbedding(),
                ),
                "travel_time_provider": HaversineTravelTimeProvider(),
            },
        },
    }


def city_select_input(case: SmokePlannerCase, selected_city: Mapping[str, Any]) -> dict[str, Any]:
    query = mapping(case.smoke.get("query"), "query")
    return {
        "cleaned_raw_query": query.get("raw_query", ""),
        "soft_preference_query": query.get("soft_query", ""),
        "trip_type": trip_type_from_case_id(case.case_id),
        "active_required_themes": tuple(query.get("themes", ())),
        "theme_weights": None,
        "transport_pref": case.transport_pref,
        "destination_id": selected_city.get("city_id"),
        "ddb_pk": selected_city.get("ddb_pk"),
    }


def planner_candidates(
    smoke: Mapping[str, Any],
    selected_ddb_pk: str,
    *,
    channel: str,
) -> tuple[Mapping[str, Any], ...]:
    channels = mapping(smoke.get("channels"), "channels")
    source = mapping(channels.get(channel), channel)
    ranked = ranked_candidates(source)
    if not ranked:
        ranked = per_theme_candidates(source)
    selected = []
    seen: set[str] = set()
    for row in ranked:
        place = planner_place(row)
        if place.get("ddb_pk") != selected_ddb_pk:
            continue
        place_id = text(place.get("place_id"), "place_id")
        if place_id in seen:
            continue
        seen.add(place_id)
        selected.append(place)
    return tuple(selected)


def ranked_candidates(channel: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    no_theme = mapping(channel.get("no_theme"), "no_theme")
    return mapping_sequence(no_theme.get("ranked"))


def per_theme_candidates(channel: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    per_theme = mapping(channel.get("per_theme"), "per_theme")
    rows: list[Mapping[str, Any]] = []
    for block in per_theme.values():
        rows.extend(mapping_sequence(mapping(block, "theme block").get("ranked")))
    return tuple(rows)


def planner_place(row: Mapping[str, Any]) -> dict[str, Any]:
    similarity = similarity_from_distance(row.get("distance"))
    return {
        **dict(row),
        "assigned_theme": first_theme(row.get("theme_tags")),
        "latitude": row.get("latitude", row.get("lat")),
        "longitude": row.get("longitude", row.get("lon")),
        "score_audit": {"score_components": {"raw_similarity": similarity}},
        "soft_similarity": similarity,
    }


def selected_city_payload(selected_ddb_pk: str, candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    for candidate in candidates:
        return {
            "city_id": candidate.get("city_id", selected_ddb_pk),
            "city_name_ko": candidate.get("city_name_ko", selected_ddb_pk),
            "country": "KR",
            "ddb_pk": selected_ddb_pk,
        }
    return {"city_id": selected_ddb_pk, "city_name_ko": selected_ddb_pk, "country": "KR", "ddb_pk": selected_ddb_pk}


def load_selected_cities(path: Path) -> dict[str, str]:
    payload = load_mapping(path)
    return {str(key): value for key, value in payload.items() if isinstance(value, str) and value.strip()}


def select_case_files(smoke_dir: Path, *, case_id: str | None, limit: int | None) -> tuple[Path, ...]:
    if case_id:
        return (smoke_dir / f"{case_id}.json",)
    files = tuple(
        path
        for path in sorted(smoke_dir.glob("*.json"))
        if not path.name.startswith(("_summary", "selected_", "rescore_", "city_stats", "attraction_data_audit"))
    )
    return files[:limit] if limit is not None else files


def summarize_result(case_id: str, case_file: Path, result: Mapping[str, Any]) -> dict[str, Any]:
    planner = mapping(result.get("planner"), "planner")
    output = planner.get("planner_output")
    validation = output.get("validation_result") if isinstance(output, Mapping) else None
    return {
        "case_id": case_id,
        "case_file": str(case_file),
        "planner_output": jsonable(output),
        "validation_result": jsonable(validation),
        "fallback": jsonable(planner.get("fallback")),
    }


def load_mapping(path: Path) -> Mapping[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    return mapping(payload, str(path))


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def mapping_sequence(value: Any) -> tuple[Mapping[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(mapping(item, "sequence item") for item in value)


def text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    return value.strip()


def first_theme(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)) and value and isinstance(value[0], str):
        return value[0]
    return None


def similarity_from_distance(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return max(0.0, 1.0 - float(value))


def trip_type_from_case_id(case_id: str) -> str:
    for value in ("daytrip", "2d1n", "3d2n", "4d3n", "5d4n"):
        if value in case_id:
            return value
    return "2d1n"


def jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
