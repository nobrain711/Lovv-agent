"""Factories that assemble in-process tool graphs from ``RuntimeConfig``.

Consolidates the city_select and festival_verifier default-builder functions
that used to live in per-agent ``tools.py`` modules. See
docs/specs/v2/LOVV_V2_TOOL_CODE_CONSOLIDATION_SPEC.md section 3.1.

``DynamoLookupTool`` itself stays in ``lovv_agent_v2.infra.dynamo_lookup``
(not moved in this pass - see spec section 3.1/12); these factories import
and wire it, but do not own it.
"""

from __future__ import annotations

from lovv_agent_v2.infra.adapters.embeddings import BedrockEmbeddingAdapter
from lovv_agent_v2.infra.aws_clients import (
    AwsClientFactory,
    AwsClientProvider,
    create_boto3_client_factory,
)
from lovv_agent_v2.infra.config import RuntimeConfig
from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool
from lovv_agent_v2.infra.repositories.dynamodb import DynamoDbRepository
from lovv_agent_v2.infra.repositories.s3_vectors import S3VectorRepository
from lovv_agent_v2.models.schemas import SchemaValidationError
from lovv_agent_v2.tools.destination_search import DestinationSearchTool
from lovv_agent_v2.tools.runtime_containers import (
    CitySelectScoringTools,
    CitySelectTools,
    FestivalVerifierTools,
)


def build_city_select_tools(
    config: RuntimeConfig,
    client_factory: AwsClientFactory,
) -> CitySelectTools:
    provider = AwsClientProvider.from_factory(
        client_factory,
        config=config,
    )
    runtime_clients = provider.create_runtime_clients()
    return CitySelectTools(
        destination_search=DestinationSearchTool(
            s3_vectors=S3VectorRepository(
                client=runtime_clients.s3_vectors,
                settings=config.s3_vectors,
            ),
            search_budget=config.search_budget,
        ),
        dynamo_lookup=DynamoLookupTool(
            dynamodb=DynamoDbRepository(
                client=runtime_clients.dynamodb,
                settings=config.dynamodb,
            ),
            search_budget=config.search_budget,
        ),
        embedding=BedrockEmbeddingAdapter(
            client=runtime_clients.bedrock_runtime,
            model_id=_required_embedding_model_id(config.embeddings.model_id),
        ),
    )


def build_city_select_scoring_tools(
    config: RuntimeConfig,
    client_factory: AwsClientFactory,
) -> CitySelectScoringTools:
    provider = AwsClientProvider.from_factory(
        client_factory,
        config=config,
    )
    return CitySelectScoringTools(
        dynamo_lookup=DynamoLookupTool(
            dynamodb=DynamoDbRepository(
                client=provider.create_dynamodb_client(),
                settings=config.dynamodb,
            ),
            search_budget=config.search_budget,
        ),
    )


def build_default_city_select_tools() -> CitySelectTools:
    config = RuntimeConfig.from_env()
    return build_city_select_tools(
        config,
        create_boto3_client_factory(profile_name=config.aws.profile_name),
    )


def build_default_city_select_scoring_tools() -> CitySelectScoringTools:
    config = RuntimeConfig.from_env()
    return build_city_select_scoring_tools(
        config,
        create_boto3_client_factory(profile_name=config.aws.profile_name),
    )


def _required_embedding_model_id(model_id: str | None) -> str:
    if model_id is None:
        raise SchemaValidationError("LOVV_EMBEDDING_MODEL_ID is required for city_select")
    return model_id


def build_festival_verifier_tools(
    config: RuntimeConfig | None = None,
) -> FestivalVerifierTools:
    runtime_config = RuntimeConfig.from_env() if config is None else config
    client_factory = create_boto3_client_factory(
        profile_name=runtime_config.aws.profile_name,
    )
    dynamodb_client = client_factory("dynamodb", region_name=runtime_config.aws.region)
    return FestivalVerifierTools(
        festival_lookup=DynamoLookupTool(
            dynamodb=DynamoDbRepository(
                client=dynamodb_client,
                settings=runtime_config.dynamodb,
            ),
            search_budget=runtime_config.search_budget,
        ),
    )


__all__ = [
    "build_city_select_scoring_tools",
    "build_city_select_tools",
    "build_default_city_select_scoring_tools",
    "build_default_city_select_tools",
    "build_festival_verifier_tools",
]
