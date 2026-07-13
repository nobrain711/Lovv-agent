from __future__ import annotations

from collections.abc import Mapping, Sequence

from lovv_agent_v2.agents.planner.state.scratch import planner_scratch
from lovv_agent_v2.agents.planner.steps.retrieve_places.festival_seed import festival_seed_refs
from lovv_agent_v2.agents.planner.steps.route_days.day_profile import trip_min_place_target, trip_place_target
from lovv_agent_v2.tools.travel_time_provider import TravelTimeProvider
from lovv_agent_v2.tools.runtime_containers import PlannerRuntimeTools
from lovv_agent_v2.tools.runtime_extractors import runtime_tools_from_value
from lovv_agent_v2.tools.travel_time import travel_time_provider_from_value
from lovv_agent_v2.core.runtime_state import runtime_value
from lovv_agent_v2.models.schemas import SchemaValidationError
from lovv_agent_v2.models.trip_intent import city_select_input_from_trip_intent

THEME_ID_TO_LABEL = {
    "sea_coast": "바다·해안",
    "nature_trekking": "자연·트레킹",
    "history_tradition": "역사·전통",
    "art_sense": "예술·감성",
    "healing_rest": "온천·휴양",
    "food_local": "미식·노포",
}
UNSEARCHABLE_PLACE_THEMES = frozenset({"미식·노포"})


def planner_input(state: Mapping[str, object]) -> dict[str, object]:
    city_selection = city_selection_result(state)
    selected_city_payload = mapping(city_selection.get("selected_city"), "selected_city")
    city_input = planner_city_input(state)
    passthrough = optional_mapping(city_selection.get("passthrough"))
    planner_hints = optional_mapping(city_selection.get("planner_hints"))
    trip_type = text(
        first_present(passthrough, "trip_duration", city_input.get("trip_type", "3d2n")),
        "trip_type",
    )
    return {
        "city_selection_result": city_selection,
        "selected_city": selected_city_payload,
        "city_id": selected_city_payload.get("city_id", selected_city_payload.get("destination_id", "")),
        "ddb_pk": selected_city_payload.get("ddb_pk", city_input.get("ddb_pk", "")),
        "seeds": (
            *mapping_sequence(city_selection.get("seeds")),
            *festival_seed_refs(state, selected_city_payload),
        ),
        "raw_query": city_input.get("cleaned_raw_query", city_input.get("raw_query", "")),
        "soft_query": city_input.get("soft_preference_query", ""),
        "active_themes": string_tuple(
            first_present(passthrough, "active_themes", city_input.get("active_required_themes", ())),
        ),
        "preferred_themes": preferred_theme_labels(city_input),
        "theme_weights": first_present(passthrough, "theme_weights", city_input.get("theme_weights")),
        "trip_type": trip_type,
        "transport_pref": text(
            first_present(passthrough, "transport_pref", city_input.get("transport_pref", "unknown")),
            "transport_pref",
        ),
        "min_count": trip_min_place_target(trip_type),
        "target_count": trip_place_target(trip_type),
        "raw_query_vector": float_tuple(planner_hints.get("raw_query_vector") if planner_hints else ()),
    }


def runtime_tools(state: Mapping[str, object]) -> PlannerRuntimeTools | None:
    scratch_runtime = runtime_tools_from_value(planner_scratch(state).get("runtime"))
    if scratch_runtime is not None:
        return scratch_runtime
    return runtime_tools_from_value(runtime_value(state, "planner_runtime"))


def travel_time_provider(state: Mapping[str, object]) -> TravelTimeProvider:
    scratch_provider = planner_scratch(state).get("travel_time_provider")
    if scratch_provider is not None:
        return travel_time_provider_from_value(scratch_provider)
    return travel_time_provider_from_value(runtime_value(state, "travel_time_provider"))


def fallback_places(
    state: Mapping[str, object],
) -> tuple[tuple[Mapping[str, object], ...], tuple[Mapping[str, object], ...]]:
    del state
    return (), ()


def selected_city(state: Mapping[str, object]) -> Mapping[str, object]:
    return mapping(city_selection_result(state).get("selected_city"), "selected_city")


def city_selection_result(state: Mapping[str, object]) -> Mapping[str, object]:
    city_select = optional_mapping(state.get("city_select"))
    if city_select is None or not city_select:
        direct_anchor = direct_anchor_city_selection_result(state)
        if direct_anchor is not None:
            return direct_anchor
        raise SchemaValidationError("city_select must be present before planner")
    return mapping(city_select.get("city_selection_result"), "city_select.city_selection_result")


def direct_anchor_city_selection_result(state: Mapping[str, object]) -> Mapping[str, object] | None:
    city_input = planner_city_input(state)
    destination_id = optional_text(city_input.get("destination_id"))
    if destination_id is None:
        return None
    selection_source = _direct_anchor_selection_source(state, city_input, destination_id)
    if selection_source is None:
        return None
    selected_city: dict[str, object] = {
        "city_id": destination_id,
        "destination_id": destination_id,
        "selection_source": selection_source,
    }
    ddb_pk = optional_text(city_input.get("city_key")) or optional_text(city_input.get("ddb_pk"))
    if ddb_pk is not None:
        selected_city["ddb_pk"] = ddb_pk
    destination_label = optional_text(city_input.get("destination_label"))
    if destination_label is not None:
        selected_city["city_name_ko"] = destination_label
    return {
        "selected_city": selected_city,
        "alternative_city": None,
        "seeds": (),
        "passthrough": {
            "active_themes": city_input.get("active_required_themes", ()),
            "theme_weights": city_input.get("theme_weights"),
            "trip_duration": city_input.get("trip_type", "3d2n"),
            "transport_pref": city_input.get("transport_pref", "unknown"),
        },
        "selection_reason_code": (selection_source,),
        "planner_hints": {selection_source: True},
    }


def _festivals_excluded(
    state: Mapping[str, object],
    city_input: Mapping[str, object],
) -> bool:
    request = optional_mapping(state.get("request"))
    if request is not None and request.get("include_festivals") is False:
        return True
    return city_input.get("include_festivals") is False


def _direct_anchor_selection_source(
    state: Mapping[str, object],
    city_input: Mapping[str, object],
    destination_id: str,
) -> str | None:
    if _festivals_excluded(state, city_input):
        return "direct_anchor_without_city_select"
    if _festival_gate_confirms_anchor(state, destination_id):
        return "festival_gated_anchor_without_city_select"
    return None


def _festival_gate_confirms_anchor(
    state: Mapping[str, object],
    destination_id: str,
) -> bool:
    festival_gate = optional_mapping(state.get("festival_gate"))
    if festival_gate is None:
        return False
    result = optional_mapping(festival_gate.get("result"))
    if result is None or result.get("status") != "ok":
        return False
    allowed_city_ids = result.get("allowed_city_ids")
    if not isinstance(allowed_city_ids, (list, tuple)):
        return False
    return destination_id in allowed_city_ids


def planner_city_input(state: Mapping[str, object]) -> Mapping[str, object]:
    intent = optional_mapping(state.get("intent"))
    if intent is None:
        return {}
    trip_intent = intent.get("trip_intent")
    if isinstance(trip_intent, Mapping):
        return city_select_input_from_trip_intent(trip_intent)
    city_input = intent.get("city_select_input")
    return city_input if isinstance(city_input, Mapping) else {}


def preferred_theme_labels(city_input: Mapping[str, object]) -> tuple[str, ...]:
    labels: list[str] = []
    active = set(string_tuple(city_input.get("active_required_themes", ())))
    for theme_id in string_tuple(city_input.get("preferred_theme_ids", ())):
        label = THEME_ID_TO_LABEL.get(theme_id, theme_id)
        if label not in active and label not in UNSEARCHABLE_PLACE_THEMES:
            labels.append(label)
    return tuple(dict.fromkeys(labels))


def candidate_payloads(
    candidates: Sequence[object],
    *,
    similarity_key: str,
) -> tuple[Mapping[str, object], ...]:
    payloads: list[Mapping[str, object]] = []
    for candidate in candidates:
        payload = candidate_payload(candidate)
        distance = payload.get("distance")
        if isinstance(distance, (int, float)) and not isinstance(distance, bool):
            similarity = max(0.0, 1.0 - float(distance))
            payload = {
                **payload,
                similarity_key: similarity,
                "score_audit": {"score_components": {similarity_key: similarity}},
            }
        payloads.append(payload)
    return tuple(payloads)


def candidate_payload(candidate: object) -> Mapping[str, object]:
    if isinstance(candidate, Mapping):
        return candidate
    to_dict = getattr(candidate, "to_dict", None)
    if callable(to_dict):
        return mapping(to_dict(), "candidate.to_dict")
    raise SchemaValidationError("candidate must be a mapping or expose to_dict")


def mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(mapping(item, "mapping sequence item") for item in value)


def mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise SchemaValidationError(f"{field_name} must be a mapping")
    return value


def optional_mapping(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (text(value, "theme"),)
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(text(item, "theme") for item in value)


def theme_weights(value: object) -> Mapping[str, float] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        str(key): float(weight)
        for key, weight in value.items()
        if isinstance(weight, (int, float)) and not isinstance(weight, bool)
    }


def float_tuple(value: object) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    vector: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            return ()
        vector.append(float(item))
    return tuple(vector)


def first_present(mapping_value: Mapping[str, object] | None, key: str, default: object) -> object:
    if mapping_value is not None and key in mapping_value:
        return mapping_value[key]
    return default


def text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return value.strip()


def optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def int_value(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    return value


def place_id(place: Mapping[str, object]) -> str:
    value = place.get("place_id", place.get("placeId"))
    return text(value, "place_id")


def float_value(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    return float(value)
