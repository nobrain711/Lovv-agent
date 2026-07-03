from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.agents.city_select.retrieval.policy import (
    ATTRACTION_ENTITY_TYPE,
    DEFAULT_RETURN_DISTANCE,
    DEFAULT_RETURN_METADATA,
    AttractionCandidate,
    PrunedCityGroups,
    is_excluded_place_search_theme,
    normalize_attraction_candidate,
    normalize_query_vector,
    normalize_string_sequence,
    optional_text,
    prune_cities,
    resolve_place_search_theme,
)
from lovv_agent_v2.infra.adapters.embeddings import BedrockEmbeddingAdapter
from lovv_agent_v2.infra.aws_clients import (
    AwsClientFactory,
    AwsClientProvider,
    create_boto3_client_factory,
)
from lovv_agent_v2.infra.config import RuntimeConfig, SearchBudgetSettings
from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool
from lovv_agent_v2.infra.repositories.dynamodb import DynamoDbRepository
from lovv_agent_v2.infra.repositories.s3_vectors import S3VectorRepository, extract_vector_records
from lovv_agent_v2.models.schemas import SchemaValidationError

TOOL_NAME = "DestinationSearchTool"
RESPONSIBILITY = "Search and normalize S3 Vector attraction evidence."


@dataclass(frozen=True, slots=True)
class DestinationSearchTool:
    s3_vectors: S3VectorRepository
    search_budget: SearchBudgetSettings

    def search_candidates(
        self,
        query_vector: Sequence[float],
        *,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
        theme_tags: Sequence[str] | None = None,
        preferred_city_ids: Sequence[str] = (),
        disliked_city_ids: Sequence[str] = (),
        top_k: int | None = None,
    ) -> tuple[AttractionCandidate, ...]:
        search_theme = resolve_place_search_theme(theme, theme_tags)
        if search_theme is not None and is_excluded_place_search_theme(search_theme):
            return ()

        request = build_attraction_search_request(
            query_vector=query_vector,
            city_id=city_id,
            ddb_pk=ddb_pk,
            theme=search_theme,
            preferred_city_ids=preferred_city_ids,
            disliked_city_ids=disliked_city_ids,
            top_k=top_k,
            search_budget=self.search_budget,
        )
        response = self.s3_vectors.query_vectors(request)
        return tuple(
            normalize_attraction_candidate(record)
            for record in extract_vector_records(response)
        )

    def prune_cities(
        self,
        candidates: Sequence[AttractionCandidate],
        searchable_place_themes: Sequence[str],
        *,
        allowed_city_ids: Sequence[str] | None = None,
    ) -> PrunedCityGroups:
        return prune_cities(
            candidates,
            searchable_place_themes,
            allowed_city_ids=allowed_city_ids,
        )


def build_attraction_search_request(
    *,
    query_vector: Sequence[float],
    city_id: str | None = None,
    ddb_pk: str | None = None,
    theme: str | None = None,
    theme_tags: Sequence[str] | None = None,
    preferred_city_ids: Sequence[str] = (),
    disliked_city_ids: Sequence[str] = (),
    top_k: int | None = None,
    search_budget: SearchBudgetSettings,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "queryVector": {"float32": normalize_query_vector(query_vector)},
        "topK": _resolve_top_k(top_k, search_budget),
        "returnMetadata": DEFAULT_RETURN_METADATA,
        "returnDistance": DEFAULT_RETURN_DISTANCE,
    }
    metadata_filter = build_attraction_filter(
        city_id=city_id,
        ddb_pk=ddb_pk,
        theme=theme,
        theme_tags=theme_tags,
        preferred_city_ids=preferred_city_ids,
        disliked_city_ids=disliked_city_ids,
    )
    if metadata_filter is not None:
        request["filter"] = metadata_filter
    return request


def build_attraction_filter(
    *,
    city_id: str | None = None,
    ddb_pk: str | None = None,
    theme: str | None = None,
    theme_tags: Sequence[str] | None = None,
    preferred_city_ids: Sequence[str] = (),
    disliked_city_ids: Sequence[str] = (),
) -> dict[str, Any] | None:
    conditions: list[dict[str, Any]] = [{"entity_type": {"$eq": ATTRACTION_ENTITY_TYPE}}]
    normalized_city_id = optional_text(city_id, "city_id")
    if normalized_city_id is not None:
        conditions.append({"city_id": {"$eq": normalized_city_id}})
    optional_text(ddb_pk, "ddb_pk")
    conditions.extend(
        _city_id_filter_conditions(
            preferred_city_ids=preferred_city_ids,
            disliked_city_ids=disliked_city_ids,
        ),
    )

    normalized_theme = resolve_place_search_theme(theme, theme_tags)
    if normalized_theme is not None:
        if is_excluded_place_search_theme(normalized_theme):
            raise SchemaValidationError(
                "theme is not searchable through S3 Vector place search",
            )
        conditions.append({"theme_tags": {"$eq": normalized_theme}})

    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _city_id_filter_conditions(
    *,
    preferred_city_ids: Sequence[str],
    disliked_city_ids: Sequence[str],
) -> tuple[dict[str, Any], ...]:
    preferred = _normalized_city_ids(preferred_city_ids, "preferred_city_ids")
    disliked = _normalized_city_ids(disliked_city_ids, "disliked_city_ids")
    conditions: list[dict[str, Any]] = []
    if len(preferred) == 1:
        conditions.append({"city_id": {"$eq": preferred[0]}})
    elif preferred:
        conditions.append({"city_id": {"$in": list(preferred)}})
    if len(disliked) == 1:
        conditions.append({"city_id": {"$ne": disliked[0]}})
    elif disliked:
        conditions.append({"city_id": {"$nin": list(disliked)}})
    return tuple(conditions)


def _normalized_city_ids(values: Sequence[str], field_name: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(normalize_string_sequence(values, field_name)))


def _resolve_top_k(top_k: int | None, search_budget: SearchBudgetSettings) -> int:
    selected = search_budget.per_theme_attraction_top_k if top_k is None else top_k
    if isinstance(selected, bool) or not isinstance(selected, int) or selected <= 0:
        raise SchemaValidationError("top_k must be a positive integer")
    return selected


@dataclass(frozen=True, slots=True)
class CitySelectTools:
    destination_search: DestinationSearchTool
    dynamo_lookup: DynamoLookupTool
    embedding: BedrockEmbeddingAdapter


@dataclass(frozen=True, slots=True)
class CitySelectScoringTools:
    dynamo_lookup: DynamoLookupTool


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


__all__ = [
    "RESPONSIBILITY",
    "TOOL_NAME",
    "CitySelectTools",
    "CitySelectScoringTools",
    "DestinationSearchTool",
    "build_attraction_filter",
    "build_attraction_search_request",
    "build_city_select_tools",
    "build_city_select_scoring_tools",
    "build_default_city_select_scoring_tools",
    "build_default_city_select_tools",
]
