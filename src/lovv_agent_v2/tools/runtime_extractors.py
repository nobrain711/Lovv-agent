"""Runtime/state extraction helpers for tool dependency containers.

Consolidates ``intent_prompt_runtime_from_state`` (formerly
``agents.intent.tools``), ``itinerary_explanation_runtime_from_state``
(formerly ``agents.response_packager.tools``), and ``runtime_tools_from_value``
(formerly ``agents.planner.tools``) into one module, deduplicating the
``_int`` coercion helper that used to be copy-pasted in both the intent and
response-packager tool modules. See
docs/specs/v2/LOVV_V2_TOOL_CODE_CONSOLIDATION_SPEC.md section 3.1.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from lovv_agent_v2.core.runtime_state import runtime_value
from lovv_agent_v2.infra.adapters.bedrock_converse import RuntimeInvoker
from lovv_agent_v2.models.schemas import SchemaValidationError
from lovv_agent_v2.tools.runtime_containers import (
    DEFAULT_SCHEMA_RETRY_LIMIT,
    DestinationSearchPort,
    EmbeddingPort,
    IntentPromptRuntime,
    ItineraryExplanationRuntime,
    PlannerRuntimeTools,
)


def _int(value: object) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool)
        else DEFAULT_SCHEMA_RETRY_LIMIT
    )


def intent_prompt_runtime_from_state(state: Mapping[str, Any]) -> IntentPromptRuntime:
    direct = _runtime_from_value(state.get("intent_prompt_runtime"))
    if direct is not None:
        return direct
    bucket = _runtime_from_value(runtime_value(state, "intent_prompt_runtime"))
    return bucket or IntentPromptRuntime()


def _runtime_from_value(value: Any) -> IntentPromptRuntime | None:
    if isinstance(value, IntentPromptRuntime):
        return value
    if isinstance(value, Mapping):
        runtime = value.get("runtime")
        return IntentPromptRuntime(
            runtime=runtime if callable(runtime) else None,
            schema_retry_limit=_int(value.get("schema_retry_limit")),
        )
    return None


def itinerary_explanation_runtime_from_state(
    state: Mapping[str, object],
) -> ItineraryExplanationRuntime:
    runtime = state.get("itinerary_explanation_runtime")
    if isinstance(runtime, ItineraryExplanationRuntime):
        return runtime
    if isinstance(runtime, Mapping):
        runtime_mapping = cast(Mapping[str, object], runtime)
        explanation_runtime = runtime_mapping.get("explanation_runtime")
        return ItineraryExplanationRuntime(
            explanation_runtime=cast(RuntimeInvoker, explanation_runtime)
            if callable(explanation_runtime)
            else None,
            dynamo_lookup=runtime_mapping.get("dynamo_lookup"),
            schema_retry_limit=_int(runtime_mapping.get("schema_retry_limit")),
        )
    runtime_bucket_value = runtime_value(state, "itinerary_explanation_runtime")
    if isinstance(runtime_bucket_value, ItineraryExplanationRuntime):
        return runtime_bucket_value
    return ItineraryExplanationRuntime()


def runtime_tools_from_value(runtime: object) -> PlannerRuntimeTools | None:
    if runtime is None:
        return None
    destination_search = getattr(runtime, "destination_search", None)
    embedding = getattr(runtime, "embedding", None)
    if destination_search is None or embedding is None:
        raise SchemaValidationError("planner runtime must include destination_search and embedding")
    return PlannerRuntimeTools(
        destination_search=cast(DestinationSearchPort, destination_search),
        embedding=cast(EmbeddingPort, embedding),
    )


__all__ = [
    "intent_prompt_runtime_from_state",
    "itinerary_explanation_runtime_from_state",
    "runtime_tools_from_value",
]
