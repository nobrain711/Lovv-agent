from __future__ import annotations

from collections.abc import Mapping

from lovv_agent_v2.core.state import UnifiedAgentState


def request_mapping(state: UnifiedAgentState) -> Mapping[str, object]:
    request = mapping_value(state.get("request"))
    if request is not None:
        return request
    intent = mapping_value(state.get("intent"))
    if intent is None:
        return {}
    city_input = mapping_value(intent.get("city_select_input"))
    return city_input or {}


def nested_mapping(state: Mapping[str, object], first: str, second: str) -> Mapping[str, object] | None:
    first_value = mapping_value(state.get(first))
    if first_value is None:
        return None
    return mapping_value(first_value.get(second))


def nested_text(
    state: Mapping[str, object],
    first: str,
    second: str,
    *,
    default: str,
) -> str:
    first_value = mapping_value(state.get(first))
    if first_value is None:
        return default
    return text_value(first_value.get(second)) or default


def mapping_value(value: object) -> Mapping[str, object] | None:
    return value if isinstance(value, Mapping) else None


def themes(request: Mapping[str, object]) -> tuple[str, ...]:
    value = request.get("themes", request.get("active_required_themes", ()))
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def text_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def bool_value(value: object) -> bool:
    return value if isinstance(value, bool) else False
