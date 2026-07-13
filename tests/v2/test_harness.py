from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Mapping
from typing import Any

import lovv_agent_v2.harness as harness_module
from lovv_agent_v2.tools.runtime_containers import IntentPromptRuntime, ItineraryExplanationRuntime
from lovv_agent_v2.core.runtime_state import runtime_value
from lovv_agent_v2.harness import LovvLangGraphV2Harness
from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool
from lovv_agent_v2.infra.aws_clients import AwsRuntimeClients
from lovv_agent_v2.infra.config import (
    EmbeddingSettings,
    LLM_NODE_EXPLANATION,
    LLM_NODE_INTENT,
    LlmSettings,
    RuntimeConfig,
)
from lovv_agent_v2.infra.repositories.dynamodb import DynamoDbRepository


@dataclass(slots=True)
class CapturingGraph:
    payloads: list[dict[str, Any]] = field(default_factory=list)
    runtime_values: list[dict[str, Any]] = field(default_factory=list)

    def invoke(
        self,
        payload: dict[str, Any],
        *,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.payloads.append(payload)
        self.runtime_values.append(
            {
                "intent": runtime_value(payload, "intent_prompt_runtime"),
                "runtime": runtime_value(payload, "itinerary_explanation_runtime"),
            },
        )
        return {"config": config or {}}


def test_harness_uses_context_runtime_without_checkpoint_payload_injection() -> None:
    graph = CapturingGraph()
    runtime = ItineraryExplanationRuntime()
    graph_runtime = {"itinerary_explanation_runtime": runtime}
    harness = LovvLangGraphV2Harness(
        graph=graph,
        config=RuntimeConfig(),
        runtime=graph_runtime,
        itinerary_explanation_runtime=runtime,
    )
    payload: dict[str, Any] = {"request": {"request_id": "REQ-1"}}

    result = harness.invoke(payload, graph_config={"configurable": {"thread_id": "t-1"}})

    assert result["config"]["configurable"]["thread_id"] == "t-1"
    assert "runtime" not in graph.payloads[0]
    assert "itinerary_explanation_runtime" not in graph.payloads[0]
    assert graph.runtime_values[0]["runtime"] is runtime
    assert "itinerary_explanation_runtime" not in payload
    assert "runtime" not in payload


def test_harness_uses_explicit_runtime_context_without_checkpoint_payload() -> None:
    graph = CapturingGraph()
    default_runtime = ItineraryExplanationRuntime()
    explicit_runtime = ItineraryExplanationRuntime(schema_retry_limit=7)
    explicit_graph_runtime = {"itinerary_explanation_runtime": explicit_runtime}
    harness = LovvLangGraphV2Harness(
        graph=graph,
        config=RuntimeConfig(),
        runtime={"itinerary_explanation_runtime": default_runtime},
        itinerary_explanation_runtime=default_runtime,
    )

    harness.invoke(
        {
            "request": {"request_id": "REQ-1"},
            "runtime": explicit_graph_runtime,
            "itinerary_explanation_runtime": explicit_runtime,
        },
    )

    assert "runtime" not in graph.payloads[0]
    assert "itinerary_explanation_runtime" not in graph.payloads[0]
    assert graph.runtime_values[0]["runtime"] is explicit_runtime


def test_build_live_harness_wires_default_itinerary_explanation_runtime(
    monkeypatch: Any,
) -> None:
    graph = CapturingGraph()
    runtime = ItineraryExplanationRuntime()
    graph_runtime = {"itinerary_explanation_runtime": runtime}
    monkeypatch.setattr(harness_module, "build_checkpointer", lambda memory: None)
    monkeypatch.setattr(harness_module, "compile_v2_graph", lambda checkpointer=None: graph)
    monkeypatch.setattr(
        harness_module,
        "_build_live_graph_runtime",
        lambda config: graph_runtime,
    )

    harness = harness_module.build_live_harness(config=RuntimeConfig())

    harness.invoke({"request": {"request_id": "REQ-1"}})
    assert "runtime" not in graph.payloads[0]
    assert "itinerary_explanation_runtime" not in graph.payloads[0]
    assert graph.runtime_values[0]["runtime"] is runtime


def test_live_graph_runtime_uses_injected_aws_runtime_clients(monkeypatch: Any) -> None:
    s3_client = object()
    dynamodb_client = object()
    bedrock_client = object()

    class FakeClientProvider:
        def create_runtime_clients(self) -> AwsRuntimeClients:
            return AwsRuntimeClients(
                s3_vectors=s3_client,
                dynamodb=dynamodb_client,
                bedrock_runtime=bedrock_client,
            )

    monkeypatch.setattr(
        harness_module,
        "create_boto3_client_provider",
        lambda config: FakeClientProvider(),
    )
    runtime = harness_module._build_live_graph_runtime(
        RuntimeConfig(
            embeddings=EmbeddingSettings(model_id="embed-model"),
            llm=LlmSettings(model_id="global-model"),
        ),
    )

    city_select_tools = runtime["city_select_tools"]
    assert city_select_tools.destination_search.s3_vectors.client is s3_client
    assert city_select_tools.dynamo_lookup.dynamodb.client is dynamodb_client
    assert city_select_tools.embedding.client is bedrock_client
    assert runtime["city_select_scoring_tools"].dynamo_lookup is city_select_tools.dynamo_lookup
    assert runtime["festival_verifier_tools"].festival_lookup is city_select_tools.dynamo_lookup
    assert runtime["planner_runtime"].destination_search is city_select_tools.destination_search
    assert runtime["planner_runtime"].embedding.embedding is city_select_tools.embedding
    assert runtime["travel_time_provider"] is not None
    assert runtime["itinerary_explanation_runtime"].dynamo_lookup is city_select_tools.dynamo_lookup


def test_live_itinerary_explanation_runtime_uses_explanation_model(
    monkeypatch: Any,
) -> None:
    captured: dict[str, str] = {}

    def create_runtime(*, client: Any, model_id: str) -> object:
        captured["model_id"] = model_id
        return object()

    monkeypatch.setattr(
        harness_module,
        "create_bedrock_converse_runtime",
        create_runtime,
    )

    runtime = harness_module._build_live_itinerary_explanation_runtime(
        RuntimeConfig(
            llm=LlmSettings(
                model_ids_by_node={
                    LLM_NODE_EXPLANATION: "explanation-model",
                },
            ),
        ),
        dynamo_lookup=_dynamo_lookup(),
        bedrock_runtime_client=object(),
    )

    assert captured["model_id"] == "explanation-model"
    assert runtime.explanation_runtime is not None


def test_harness_uses_context_intent_prompt_runtime() -> None:
    graph = CapturingGraph()
    intent_runtime = IntentPromptRuntime(runtime=lambda request: {})
    harness = LovvLangGraphV2Harness(
        graph=graph,
        config=RuntimeConfig(),
        runtime={"intent_prompt_runtime": intent_runtime},
    )

    harness.invoke({"request": {"request_id": "REQ-1"}})

    assert "runtime" not in graph.payloads[0]
    assert graph.runtime_values[0]["intent"] is intent_runtime


def test_live_intent_prompt_runtime_uses_intent_model(monkeypatch: Any) -> None:
    captured: dict[str, str] = {}

    def create_runtime(*, client: Any, model_id: str) -> object:
        captured["model_id"] = model_id
        return object()

    monkeypatch.setattr(
        harness_module,
        "create_bedrock_converse_runtime",
        create_runtime,
    )

    runtime = harness_module._build_live_intent_prompt_runtime(
        RuntimeConfig(
            llm=LlmSettings(
                model_ids_by_node={
                    LLM_NODE_INTENT: "intent-model",
                },
            ),
        ),
        bedrock_runtime_client=object(),
    )

    assert captured["model_id"] == "intent-model"
    assert runtime.runtime is not None


class FakeDynamoDbClient:
    def get_item(self, **request: Any) -> Mapping[str, Any]:
        return {}

    def query(self, **request: Any) -> Mapping[str, Any]:
        return {}

    def scan(self, **request: Any) -> Mapping[str, Any]:
        return {}

    def batch_get_item(self, **request: Any) -> Mapping[str, Any]:
        return {}


def _dynamo_lookup() -> DynamoLookupTool:
    config = RuntimeConfig()
    return DynamoLookupTool(
        dynamodb=DynamoDbRepository(
            client=FakeDynamoDbClient(),
            settings=config.dynamodb,
        ),
        search_budget=config.search_budget,
    )
