"""Composition Root for Lovv Agent V2.

This module initializes dependencies (infra) and passes them to the graph components.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Sequence
from typing import Any

from langgraph.types import Command

from lovv_agent_v2.tools.destination_search import DestinationSearchTool
from lovv_agent_v2.tools.runtime_containers import (
    CitySelectScoringTools,
    CitySelectTools,
    FestivalVerifierTools,
    IntentPromptRuntime,
    ItineraryExplanationRuntime,
    PlannerRuntimeTools,
)
from lovv_agent_v2.common.telemetry import trace_invocation
from lovv_agent_v2.harness_runtime import (
    build_live_travel_time_provider,
    memory_event_runtime,
)
from lovv_agent_v2.infra.adapters.embeddings import BedrockEmbeddingAdapter
from lovv_agent_v2.infra.adapters.bedrock_converse import create_bedrock_converse_runtime
from lovv_agent_v2.infra.aws_clients import create_boto3_client_provider
from lovv_agent_v2.infra.config import RuntimeConfig
from lovv_agent_v2.infra.config import (
    LLM_NODE_EXPLANATION,
    LLM_NODE_INTENT,
    resolve_llm_model_id,
)
from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool
from lovv_agent_v2.infra.memory.checkpointer import build_checkpointer
from lovv_agent_v2.infra.repositories.dynamodb import DynamoDbRepository
from lovv_agent_v2.infra.repositories.s3_vectors import S3VectorRepository
from lovv_agent_v2.core.graph import compile_v2_graph
from lovv_agent_v2.core.runtime_state import invocation_runtime
from lovv_agent_v2.core.trace_context import (
    trace_context_from_graph_config,
    with_trace_context,
)
from lovv_agent_v2.models.schemas import SchemaValidationError


@dataclass(frozen=True, slots=True)
class PlannerEmbeddingAdapter:
    embedding: BedrockEmbeddingAdapter

    def embed_query(self, query: str) -> Sequence[float]:
        return self.embedding.embed_query(query)


@dataclass(frozen=True, slots=True)
class LovvLangGraphV2Harness:
    """Compiled LangGraph V2 plus its runtime configuration."""

    graph: Any
    config: RuntimeConfig
    runtime: dict[str, Any] | None = None
    itinerary_explanation_runtime: ItineraryExplanationRuntime | None = None

    def invoke(
        self,
        payload: Command | dict[str, Any],
        *,
        request_id: str | None = None,
        graph_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke the V2 graph and return the output."""

        config = dict(graph_config or {})
        graph_payload = (
            payload if isinstance(payload, Command) else _checkpoint_payload(payload)
        )
        runtime = (
            self.runtime
            if isinstance(payload, Command)
            else _runtime_payload(payload) or self.runtime
        )
        itinerary_runtime = self.itinerary_explanation_runtime
        if not isinstance(payload, Command):
            itinerary_runtime = (
                _itinerary_explanation_runtime_payload(payload)
                or self.itinerary_explanation_runtime
            )
            graph_payload = _payload_with_trace(
                graph_payload,
                request_id=request_id,
                graph_config=config,
            )
        with invocation_runtime(runtime, itinerary_runtime):
            if isinstance(graph_payload, dict):
                return trace_invocation(
                    graph_payload,
                    lambda: self.graph.invoke(graph_payload, config=config),
                )
            return trace_invocation(
                _payload_with_trace(
                    {"request": {"request_id": request_id or "resume"}},
                    request_id=request_id,
                    graph_config=config,
                ),
                lambda: self.graph.invoke(graph_payload, config=config),
            )


def build_v2_harness(
    config: RuntimeConfig,
    checkpointer: Any | None = None,
    runtime: dict[str, Any] | None = None,
    itinerary_explanation_runtime: ItineraryExplanationRuntime | None = None,
) -> LovvLangGraphV2Harness:
    """Build and compile the V2 recommendation graph."""

    graph = compile_v2_graph(checkpointer=checkpointer)
    return LovvLangGraphV2Harness(
        graph=graph,
        config=config,
        runtime=runtime,
        itinerary_explanation_runtime=itinerary_explanation_runtime,
    )


def build_live_harness(
    config: RuntimeConfig | None = None,
) -> LovvLangGraphV2Harness:
    """Build a live harness from injected or environment config with checkpointer."""

    resolved_config = RuntimeConfig.from_env() if config is None else config
    checkpointer = build_checkpointer(resolved_config.memory)
    runtime = _build_live_graph_runtime(resolved_config)
    return build_v2_harness(
        config=resolved_config,
        checkpointer=checkpointer,
        runtime=runtime,
        itinerary_explanation_runtime=runtime["itinerary_explanation_runtime"],
    )


def _checkpoint_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"runtime", "itinerary_explanation_runtime"}
    }


def _payload_with_trace(
    payload: dict[str, Any],
    *,
    request_id: str | None,
    graph_config: dict[str, Any],
) -> dict[str, Any]:
    return with_trace_context(
        payload,
        trace_context_from_graph_config(
            payload,
            request_id=request_id,
            graph_config=graph_config,
        ),
    )


def _runtime_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    runtime = payload.get("runtime")
    return dict(runtime) if isinstance(runtime, dict) else None


def _itinerary_explanation_runtime_payload(
    payload: dict[str, Any],
) -> ItineraryExplanationRuntime | None:
    runtime = payload.get("itinerary_explanation_runtime")
    return runtime if isinstance(runtime, ItineraryExplanationRuntime) else None


def _build_live_graph_runtime(config: RuntimeConfig) -> dict[str, Any]:
    client_provider = create_boto3_client_provider(config=config)
    runtime_clients = client_provider.create_runtime_clients()
    dynamo_lookup = DynamoLookupTool(
        dynamodb=DynamoDbRepository(
            client=runtime_clients.dynamodb,
            settings=config.dynamodb,
        ),
        search_budget=config.search_budget,
    )
    destination_search = DestinationSearchTool(
        s3_vectors=S3VectorRepository(
            client=runtime_clients.s3_vectors,
            settings=config.s3_vectors,
        ),
        search_budget=config.search_budget,
    )
    embedding = BedrockEmbeddingAdapter(
        client=runtime_clients.bedrock_runtime,
        model_id=_required_embedding_model_id(config.embeddings.model_id),
    )
    city_select_tools = CitySelectTools(
        destination_search=destination_search,
        dynamo_lookup=dynamo_lookup,
        embedding=embedding,
    )
    planner_runtime = PlannerRuntimeTools(
        destination_search=destination_search,
        embedding=PlannerEmbeddingAdapter(embedding),
    )
    itinerary_runtime = _build_live_itinerary_explanation_runtime(
        config,
        dynamo_lookup=dynamo_lookup,
        bedrock_runtime_client=runtime_clients.bedrock_runtime,
    )
    return {
        "interrupts_enabled": True,
        "city_select_tools": city_select_tools,
        "city_select_scoring_tools": CitySelectScoringTools(
            dynamo_lookup=dynamo_lookup,
        ),
        "festival_verifier_tools": FestivalVerifierTools(
            festival_lookup=dynamo_lookup,
        ),
        "intent_prompt_runtime": _build_live_intent_prompt_runtime(
            config,
            bedrock_runtime_client=runtime_clients.bedrock_runtime,
        ),
        "planner_runtime": planner_runtime,
        "travel_time_provider": build_live_travel_time_provider(client_provider),
        "itinerary_explanation_runtime": itinerary_runtime,
        **memory_event_runtime(config, client_provider),
    }


def _build_live_intent_prompt_runtime(
    config: RuntimeConfig,
    *,
    bedrock_runtime_client: Any,
) -> IntentPromptRuntime:
    model_id = resolve_llm_model_id(config.llm, LLM_NODE_INTENT)
    bedrock_runtime = (
        None
        if model_id is None
        else create_bedrock_converse_runtime(
            client=bedrock_runtime_client,
            model_id=model_id,
        )
    )
    return IntentPromptRuntime(
        runtime=bedrock_runtime,
        schema_retry_limit=config.retries.schema_retry_limit,
    )


def _build_live_itinerary_explanation_runtime(
    config: RuntimeConfig,
    *,
    dynamo_lookup: DynamoLookupTool,
    bedrock_runtime_client: Any,
) -> ItineraryExplanationRuntime:
    model_id = resolve_llm_model_id(config.llm, LLM_NODE_EXPLANATION)
    bedrock_runtime = (
        None
        if model_id is None
        else create_bedrock_converse_runtime(
            client=bedrock_runtime_client,
            model_id=model_id,
        )
    )
    return ItineraryExplanationRuntime(
        explanation_runtime=bedrock_runtime,
        dynamo_lookup=dynamo_lookup,
        schema_retry_limit=config.retries.schema_retry_limit,
    )


def _required_embedding_model_id(model_id: str | None) -> str:
    if model_id is None:
        raise SchemaValidationError("LOVV_EMBEDDING_MODEL_ID is required for live V2 harness")
    return model_id


__all__ = ["LovvLangGraphV2Harness", "build_v2_harness", "build_live_harness"]
