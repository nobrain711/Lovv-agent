"""Tests for DestinationSearchTool and DynamoLookupTool boundaries."""

from __future__ import annotations

import json
import unittest
from typing import Any

from lovv_agent_v2.infra.aws_clients import (
    AwsClientConfigurationError,
    AwsClientProvider,
)
from lovv_agent_v2.infra.config import (
    DynamoDbSettings,
    EmbeddingSettings,
    RuntimeConfig,
    S3VectorSettings,
    SearchBudgetSettings,
)
from lovv_agent_v2.models.schemas import SchemaValidationError
from lovv_agent_v2.infra.repositories.dynamodb import DynamoDbRepository
from lovv_agent_v2.infra.repositories.s3_vectors import S3VectorRepository
from lovv_agent_v2.infra.dynamo_lookup import (
    DynamoLookupTool,
    normalize_festival_candidate,
)
from lovv_agent_v2.tools.destination_policy import (
    ATTRACTION_ENTITY_TYPE,
    normalize_attraction_candidate,
    prune_cities,
)
from lovv_agent_v2.agents.city_select.retrieval.flow import (
    retrieve_allowed_city_pool_by_theme,
)
from lovv_agent_v2.tools.destination_search import (
    DestinationSearchTool,
    build_attraction_filter,
    build_attraction_search_request,
)
from lovv_agent_v2.tools.factories import build_city_select_tools


class RecordingAwsFactory:
    """Record lazy AWS client creation calls without touching real AWS."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, service_name: str, *, region_name: str) -> dict[str, str]:
        self.calls.append((service_name, region_name))
        return {"service": service_name, "region": region_name}


class RecordingRuntimeAwsFactory:
    def __init__(
        self,
        *,
        s3_vectors_client: Any,
        dynamodb_client: Any,
        bedrock_runtime_client: Any,
    ) -> None:
        self.calls: list[tuple[str, str]] = []
        self.clients = {
            "s3vectors": s3_vectors_client,
            "dynamodb": dynamodb_client,
            "bedrock-runtime": bedrock_runtime_client,
        }

    def __call__(self, service_name: str, *, region_name: str) -> Any:
        self.calls.append((service_name, region_name))
        if service_name not in self.clients:
            raise AssertionError(f"unexpected service: {service_name}")
        return self.clients[service_name]


class RecordingS3VectorClient:
    """Mock S3 Vector client used by repository tests."""

    def __init__(self, response: dict[str, Any] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.response = {"vectors": [{"key": "chunk-1"}]} if response is None else response

    def query_vectors(self, **request: Any) -> dict[str, Any]:
        self.requests.append(dict(request))
        return self.response


class RecordingDynamoDbClient:
    """Mock DynamoDB client used by repository tests."""

    def __init__(
        self,
        query_response: dict[str, Any] | None = None,
        get_item_response: dict[str, Any] | None = None,
        batch_get_response: dict[str, Any] | None = None,
        get_item_exception: Exception | None = None,
        batch_get_exception: Exception | None = None,
    ) -> None:
        self.get_item_requests: list[dict[str, Any]] = []
        self.batch_get_item_requests: list[dict[str, Any]] = []
        self.query_requests: list[dict[str, Any]] = []
        self.scan_requests: list[dict[str, Any]] = []
        self.query_response = (
            {"Items": [{"pk": {"S": "FESTIVAL#1"}}]}
            if query_response is None
            else query_response
        )
        self.get_item_response = (
            {"Item": {"pk": {"S": "PLACE#1"}}}
            if get_item_response is None
            else get_item_response
        )
        self.batch_get_response = (
            {"Responses": {}}
            if batch_get_response is None
            else batch_get_response
        )
        self.get_item_exception = get_item_exception
        self.batch_get_exception = batch_get_exception

    def get_item(self, **request: Any) -> dict[str, Any]:
        self.get_item_requests.append(dict(request))
        if self.get_item_exception is not None:
            raise self.get_item_exception
        return self.get_item_response

    def query(self, **request: Any) -> dict[str, Any]:
        self.query_requests.append(dict(request))
        return self.query_response

    def scan(self, **request: Any) -> dict[str, Any]:
        self.scan_requests.append(dict(request))
        return self.query_response

    def batch_get_item(self, **request: Any) -> dict[str, Any]:
        self.batch_get_item_requests.append(dict(request))
        if self.batch_get_exception is not None:
            raise self.batch_get_exception
        return self.batch_get_response


class RecordingBedrockRuntimeClient:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []

    def invoke_model(self, **request: Any) -> dict[str, Any]:
        self.requests.append(dict(request))
        body = json.loads(request["body"].decode("utf-8"))
        return {"body": json.dumps({"embedding": [0.1] * body["dimensions"]})}


class RecordingDestinationSearch:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def search_candidates(
        self,
        query_vector: list[float],
        *,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
    ) -> tuple[Any, ...]:
        self.calls.append(
            {
                "query_vector": query_vector,
                "city_id": city_id,
                "ddb_pk": ddb_pk,
                "theme": theme,
            },
        )
        return (
            normalize_attraction_candidate(
                {
                    "key": f"{city_id}-{theme}",
                    "distance": 0.1,
                    "metadata": {
                        "entity_type": "attraction",
                        "city_id": city_id or "KR-NONE",
                        "title": f"{city_id} {theme}",
                        "theme_tags": [theme or "history"],
                        "ddb_pk": f"CITY#{city_id}",
                    },
                },
            ),
        )


def make_dynamo_lookup_tool(
    dynamodb_client: RecordingDynamoDbClient,
    *,
    search_budget: SearchBudgetSettings | None = None,
) -> DynamoLookupTool:
    """Build a DynamoLookupTool with a mock DynamoDB repository."""

    return DynamoLookupTool(
        dynamodb=DynamoDbRepository(
            client=dynamodb_client,
            settings=DynamoDbSettings(table_name="lovv-table"),
        ),
        search_budget=search_budget or SearchBudgetSettings(),
    )


class AwsClientProviderTest(unittest.TestCase):
    """Validate lazy AWS client construction for Task 4.1."""

    def test_provider_does_not_create_clients_until_requested(self) -> None:
        factory = RecordingAwsFactory()
        config = RuntimeConfig()

        provider = AwsClientProvider.from_factory(factory, config=config)

        self.assertEqual(factory.calls, [])
        s3_client = provider.create_s3_vectors_client()
        dynamodb_client = provider.create_dynamodb_client()

        self.assertEqual(
            factory.calls,
            [
                ("s3vectors", config.aws.region),
                ("dynamodb", config.aws.region),
            ],
        )
        self.assertEqual(s3_client["service"], "s3vectors")
        self.assertEqual(dynamodb_client["service"], "dynamodb")

    def test_provider_requires_injected_factory(self) -> None:
        provider = AwsClientProvider(config=RuntimeConfig())

        with self.assertRaises(AwsClientConfigurationError):
            provider.create_dynamodb_client()


class RepositoryBoundaryTest(unittest.TestCase):
    """Validate mockable repository boundaries without AWS credentials."""

    def test_s3_vector_repository_uses_injected_client_and_settings(self) -> None:
        client = RecordingS3VectorClient()
        repository = S3VectorRepository(
            client=client,
            settings=S3VectorSettings(
                bucket_name="lovv-vector-bucket",
                index_name="attractions-index",
            ),
        )

        response = repository.query_vectors({"query_vector": [0.1, 0.2], "top_k": 3})

        self.assertEqual(response["vectors"][0]["key"], "chunk-1")
        self.assertEqual(
            client.requests,
            [
                {
                    "query_vector": [0.1, 0.2],
                    "top_k": 3,
                    "vectorBucketName": "lovv-vector-bucket",
                    "indexName": "attractions-index",
                },
            ],
        )

    def test_dynamodb_repository_uses_injected_client_and_table(self) -> None:
        client = RecordingDynamoDbClient()
        repository = DynamoDbRepository(
            client=client,
            settings=DynamoDbSettings(table_name="lovv-table"),
        )

        item_response = repository.get_item(
            {"pk": {"S": "PLACE#1"}, "sk": {"S": "DETAIL#1"}},
        )
        query_response = repository.query_items(
            {"KeyConditionExpression": "pk = :pk"},
        )

        self.assertEqual(item_response["Item"]["pk"]["S"], "PLACE#1")
        self.assertEqual(query_response["Items"][0]["pk"]["S"], "FESTIVAL#1")
        self.assertEqual(client.get_item_requests[0]["TableName"], "lovv-table")
        self.assertEqual(client.query_requests[0]["TableName"], "lovv-table")

    def test_repositories_validate_request_and_response_shapes(self) -> None:
        s3_repository = S3VectorRepository(
            client=RecordingS3VectorClient(),
            settings=S3VectorSettings(),
        )
        dynamodb_repository = DynamoDbRepository(
            client=RecordingDynamoDbClient(),
            settings=DynamoDbSettings(),
        )

        with self.assertRaises(SchemaValidationError):
            s3_repository.query_vectors(["not", "a", "mapping"])  # type: ignore[arg-type]

        with self.assertRaises(SchemaValidationError):
            dynamodb_repository.get_item(["not", "a", "mapping"])  # type: ignore[arg-type]


class CitySelectRuntimeToolTest(unittest.TestCase):
    def test_runtime_tools_use_current_repository_contract_and_embedding_adapter(self) -> None:
        s3_client = RecordingS3VectorClient(
            response={
                "vectors": [
                    {
                        "key": "place-1",
                        "distance": 0.2,
                        "metadata": {
                            "entity_type": "attraction",
                            "city_id": "city-1",
                            "title": "바다 산책로",
                            "theme_tags": ["sea_coast"],
                        },
                    },
                ],
            },
        )
        dynamodb_client = RecordingDynamoDbClient()
        bedrock_client = RecordingBedrockRuntimeClient()
        factory = RecordingRuntimeAwsFactory(
            s3_vectors_client=s3_client,
            dynamodb_client=dynamodb_client,
            bedrock_runtime_client=bedrock_client,
        )
        config = RuntimeConfig(
            s3_vectors=S3VectorSettings(
                bucket_name="bucket",
                index_name="index",
            ),
            dynamodb=DynamoDbSettings(table_name="table"),
            embeddings=EmbeddingSettings(model_id="embed-model"),
        )

        tools = build_city_select_tools(
            config,
            factory,
        )

        vector = tools.embedding.embed_query("조용한 바다 여행")
        tools.destination_search.search_candidates(vector, theme="sea_coast")

        self.assertEqual(factory.calls[0][0], "s3vectors")
        self.assertEqual(factory.calls[1][0], "dynamodb")
        self.assertEqual(factory.calls[2][0], "bedrock-runtime")
        self.assertIs(tools.dynamo_lookup.dynamodb.client, dynamodb_client)
        self.assertEqual(s3_client.requests[0]["vectorBucketName"], "bucket")
        self.assertEqual(s3_client.requests[0]["indexName"], "index")
        self.assertEqual(bedrock_client.requests[0]["modelId"], "embed-model")


class AttractionSearchTest(unittest.TestCase):
    """Validate attraction search request construction for Task 4.2."""

    def test_search_candidates_builds_attraction_only_filter(self) -> None:
        client = RecordingS3VectorClient(
            response={
                "vectors": [
                    {
                        "key": "place-1::chunk-3",
                        "distance": 0.12,
                        "metadata": {
                            "entity_type": ATTRACTION_ENTITY_TYPE,
                            "city_id": "city-1",
                            "city_name_ko": "샘플시",
                            "theme_tags": ["sea_coast", "walk"],
                            "title": "조용한 해변 산책로",
                            "latitude": 35.1,
                            "longitude": 129.1,
                            "ddb_pk": "PLACE#1",
                            "ddb_sk": "DETAIL#1",
                        },
                    },
                ],
            },
        )
        repository = S3VectorRepository(client=client, settings=S3VectorSettings())
        tool = DestinationSearchTool(
            s3_vectors=repository,
            search_budget=SearchBudgetSettings(per_theme_attraction_top_k=7),
        )

        candidates = tool.search_candidates(
            [0.1, 0.2, 0.3],
            city_id="city-1",
            theme="sea_coast",
        )

        request = client.requests[0]
        self.assertEqual(request["queryVector"], {"float32": [0.1, 0.2, 0.3]})
        self.assertEqual(request["topK"], 7)
        self.assertTrue(request["returnMetadata"])
        self.assertTrue(request["returnDistance"])
        self.assertEqual(
            request["filter"],
            {
                "$and": [
                    {"entity_type": {"$eq": "attraction"}},
                    {"city_id": {"$eq": "city-1"}},
                    {"theme_tags": {"$eq": "sea_coast"}},
                ],
            },
        )
        self.assertEqual(candidates[0].place_id, "place-1")
        self.assertEqual(candidates[0].city_id, "city-1")

    def test_search_candidates_top_k_call_argument_overrides_runtime_budget(self) -> None:
        request = build_attraction_search_request(
            query_vector=[0.1],
            top_k=3,
            search_budget=SearchBudgetSettings(per_theme_attraction_top_k=9),
        )

        self.assertEqual(request["topK"], 3)

    def test_filter_combines_city_and_single_theme(self) -> None:
        metadata_filter = build_attraction_filter(city_id="city-7", theme="history")

        self.assertEqual(
            metadata_filter,
            {
                "$and": [
                    {"entity_type": {"$eq": "attraction"}},
                    {"city_id": {"$eq": "city-7"}},
                    {"theme_tags": {"$eq": "history"}},
                ],
            },
        )

    def test_filter_does_not_use_non_filterable_ddb_pk(self) -> None:
        metadata_filter = build_attraction_filter(ddb_pk="CITY#ANDONG", theme="history")

        self.assertEqual(
            metadata_filter,
            {
                "$and": [
                    {"entity_type": {"$eq": "attraction"}},
                    {"theme_tags": {"$eq": "history"}},
                ],
            },
        )

    def test_festival_allowed_pool_retrieves_each_city_directly(self) -> None:
        search = RecordingDestinationSearch()

        candidates = retrieve_allowed_city_pool_by_theme(
            search,
            query_vector=[0.1, 0.2],
            themes=("역사·전통",),
            allowed_city_ids=("KR-47-130", "KR-51-730", "KR-36-8"),
        )

        self.assertEqual(len(candidates), 3)
        self.assertEqual(
            [(call["city_id"], call["theme"]) for call in search.calls],
            [
                ("KR-47-130", "역사·전통"),
                ("KR-51-730", "역사·전통"),
                ("KR-36-8", "역사·전통"),
            ],
        )
        self.assertNotIn(None, [call["city_id"] for call in search.calls])

    def test_food_theme_is_not_sent_to_s3_vector_search(self) -> None:
        client = RecordingS3VectorClient()
        repository = S3VectorRepository(client=client, settings=S3VectorSettings())
        tool = DestinationSearchTool(
            s3_vectors=repository,
            search_budget=SearchBudgetSettings(),
        )

        candidates = tool.search_candidates([0.1, 0.2], theme="미식·노포")

        self.assertEqual(candidates, ())
        self.assertEqual(client.requests, [])

    def test_chunk_key_normalizes_to_stable_place_id(self) -> None:
        candidate = normalize_attraction_candidate(
            {
                "key": "attraction#place-99#12",
                "distance": 0.5,
                "metadata": {
                    "entity_type": "attraction",
                    "city_id": "city-1",
                    "title": "명소",
                    "theme_tags": "history",
                },
            },
        )

        self.assertEqual(candidate.place_id, "attraction#place-99")
        self.assertEqual(candidate.theme_tags, ("history",))

    def test_normalize_metadata_place_id_overrides_chunk_key(self) -> None:
        candidate = normalize_attraction_candidate(
            {
                "key": "chunk-only-1",
                "distance": 0.5,
                "metadata": {
                    "entity_type": "attraction",
                    "place_id": "place-from-metadata",
                    "city_id": "city-1",
                    "title": "명소",
                    "theme_tags": ["history"],
                },
            },
        )

        self.assertEqual(candidate.place_id, "place-from-metadata")

    def test_normalize_non_attraction_candidate_fails(self) -> None:
        with self.assertRaises(SchemaValidationError):
            normalize_attraction_candidate(
                {
                    "key": "festival-1::chunk-1",
                    "distance": 0.5,
                    "metadata": {
                        "entity_type": "festival",
                        "city_id": "city-1",
                        "title": "축제",
                        "theme_tags": ["festival"],
                    },
                },
            )

    def test_prune_cities_applies_allowed_pool_and_partial_theme_membership(self) -> None:
        candidates = (
            normalize_attraction_candidate(
                {
                    "key": "attraction#sea-1#1",
                    "distance": 0.1,
                    "metadata": {
                        "entity_type": "attraction",
                        "city_id": "city-1",
                        "title": "바다 산책로",
                        "theme_tags": ["바다·해안"],
                    },
                },
            ),
            normalize_attraction_candidate(
                {
                    "key": "attraction#history-1#1",
                    "distance": 0.2,
                    "metadata": {
                        "entity_type": "attraction",
                        "city_id": "city-1",
                        "title": "역사 거리",
                        "theme_tags": ["역사·문화"],
                    },
                },
            ),
            normalize_attraction_candidate(
                {
                    "key": "attraction#sea-2#1",
                    "distance": 0.3,
                    "metadata": {
                        "entity_type": "attraction",
                        "city_id": "city-2",
                        "title": "다른 바다",
                        "theme_tags": ["바다·해안"],
                    },
                },
            ),
        )

        result = prune_cities(
            candidates,
            ["바다·해안", "역사·문화"],
            allowed_city_ids=["city-1", "city-2"],
        )

        self.assertEqual(tuple(result.survived_groups), ("CITY-1", "CITY-2"))
        self.assertEqual(result.eliminated_cities, ())
        self.assertEqual(result.available_themes_by_city["CITY-1"], ("바다·해안", "역사·문화"))
        self.assertEqual(result.missing_themes_by_city["CITY-1"], ())
        self.assertEqual(result.available_themes_by_city["CITY-2"], ("바다·해안",))
        self.assertEqual(result.missing_themes_by_city["CITY-2"], ("역사·문화",))

    def test_prune_cities_normalizes_ddb_pk_case_and_goseong_alias(self) -> None:
        candidates = (
            normalize_attraction_candidate(
                {
                    "key": "attraction#andong-1#1",
                    "distance": 0.1,
                    "metadata": {
                        "entity_type": "attraction",
                        "city_id": "KR-47-ANDONG",
                        "title": "안동 장소 1",
                        "theme_tags": ["history"],
                        "ddb_pk": "CITY#Andong",
                    },
                },
            ),
            normalize_attraction_candidate(
                {
                    "key": "attraction#andong-2#1",
                    "distance": 0.2,
                    "metadata": {
                        "entity_type": "attraction",
                        "city_id": "KR-47-ANDONG",
                        "title": "안동 장소 2",
                        "theme_tags": ["nature"],
                        "ddb_pk": "CITY#ANDONG",
                    },
                },
            ),
            normalize_attraction_candidate(
                {
                    "key": "attraction#goseong-1#1",
                    "distance": 0.3,
                    "metadata": {
                        "entity_type": "attraction",
                        "city_id": "KR-42-GOSEONG",
                        "title": "고성 장소",
                        "theme_tags": ["nature"],
                        "ddb_pk": "CITY#GOSEONG",
                    },
                },
            ),
        )

        result = prune_cities(candidates, ["history", "nature"])

        self.assertEqual(
            tuple(result.survived_groups),
            ("CITY#ANDONG", "CITY#GOSEONG-GANGWON"),
        )
        self.assertEqual(len(result.survived_groups["CITY#ANDONG"]), 2)


class FestivalSeedTest(unittest.TestCase):
    """Validate festival city seed lookup rules for Task 4.3."""

    def test_festival_seed_ignores_theme_pool(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(
            query_response={
                "Items": [
                    {
                        "festival_id": "festival-1",
                        "name": "월 일치 축제",
                        "country": "KR",
                        "city_id": "city-1",
                        "month": 6,
                    },
                ],
            },
        )
        tool = make_dynamo_lookup_tool(dynamodb_client)

        result = tool.search_festival_city_seeds(
            country="KR",
            travel_month=6,
            travel_year=2026,
            theme_pool=["festival_event", "축제·이벤트"],
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.seed_city_ids, ("city-1",))
        self.assertEqual(result.candidates[0].festival_id, "festival-1")

    def test_festival_seed_applies_month_without_theme_filtering(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(
            query_response={
                "Items": [
                    {
                        "festival_id": "festival-1",
                        "name": "바다 축제",
                        "country": "KR",
                        "city_id": "city-1",
                        "city_name": "해변시",
                        "month": 6,
                        "assigned_theme": "sea_coast",
                        "theme_tags": ["festival"],
                    },
                    {
                        "festival_id": "festival-2",
                        "name": "역사 야행",
                        "country": "KR",
                        "city_id": "city-2",
                        "city_name": "고도시",
                        "month": 6,
                        "theme": "history",
                        "assigned_theme": "night_view",
                        "theme_tags": ["festival"],
                    },
                    {
                        "festival_id": "festival-3",
                        "name": "다음달 축제",
                        "country": "KR",
                        "city_id": "city-3",
                        "city_name": "달력시",
                        "month": 7,
                        "assigned_theme": "sea_coast",
                        "theme_tags": ["history"],
                    },
                    {
                        "festival_id": "festival-4",
                        "name": "다른 테마 축제",
                        "country": "KR",
                        "city_id": "city-4",
                        "city_name": "테마시",
                        "month": 6,
                        "assigned_theme": "shopping",
                        "theme_tags": ["shopping"],
                    },
                ],
            },
        )
        tool = make_dynamo_lookup_tool(dynamodb_client)

        result = tool.search_festival_city_seeds(
            country="KR",
            travel_month=6,
            travel_year=2026,
            theme_pool=["sea_coast", "history"],
            max_candidates=10,
        )

        self.assertEqual(result.status, "ok")
        self.assertFalse(result.needs_clarification)
        self.assertEqual(result.seed_city_ids, ("city-1", "city-2", "city-4"))
        self.assertEqual(result.to_dict()["seed_city_ids"], ["city-1", "city-2", "city-4"])
        self.assertEqual(
            [candidate.festival_id for candidate in result.candidates],
            ["festival-1", "festival-2", "festival-4"],
        )
        self.assertEqual(dynamodb_client.scan_requests, [])
        request = dynamodb_client.query_requests[0]
        self.assertEqual(request["TableName"], "lovv-table")
        self.assertEqual(request["IndexName"], "FestivalMonthIndex")
        self.assertEqual(request["ExpressionAttributeValues"][":month_prefix"], {"S": "FESTIVAL#06"})
        self.assertEqual(
            request["ExpressionAttributeValues"][":entity_type"],
            {"S": "festival"},
        )
        self.assertEqual(
            request["KeyConditionExpression"],
            "#entity_type = :entity_type AND begins_with(#gsi_sk, :month_prefix)",
        )

    def test_fixed_city_festival_seed_restricts_to_anchor_city(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(
            query_response={
                "Items": [
                    {
                        "festival_id": "festival-1",
                        "name": "첫 도시 축제",
                        "country": "KR",
                        "city_id": "city-1",
                        "month": 6,
                        "PK": "CITY#CITY-1",
                        "SK": "FESTIVAL#festival-1",
                        "assigned_theme": "history",
                        "theme_tags": ["history"],
                    },
                    {
                        "festival_id": "festival-2",
                        "name": "고정 도시 축제",
                        "country": "KR",
                        "city_id": "city-2",
                        "month": 6,
                        "PK": "CITY#CITY-2",
                        "SK": "FESTIVAL#festival-2",
                        "city_key": "CITY#CITY-2",
                        "ddb_pk": "CITY#CITY-2",
                        "assigned_theme": "history",
                        "theme_tags": ["history"],
                    },
                ],
            },
        )
        tool = make_dynamo_lookup_tool(dynamodb_client)

        result = tool.search_festival_city_seeds(
            country="KR",
            travel_month=6,
            travel_year=2026,
            theme_pool=["history"],
            city_id="city-2",
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.seed_city_ids, ("city-2",))
        self.assertEqual(result.candidates[0].festival_id, "festival-2")
        self.assertEqual(result.candidates[0].ddb_pk, "CITY#CITY-2")
        self.assertEqual(result.candidates[0].ddb_sk, "FESTIVAL#festival-2")
        self.assertEqual(result.candidates[0].city_key, "CITY#CITY-2")
        self.assertEqual(
            result.verified_festival_cities[0]["festivals"][0]["SK"],
            "FESTIVAL#festival-2",
        )
        request = dynamodb_client.query_requests[0]
        self.assertEqual(dynamodb_client.scan_requests, [])
        self.assertEqual(request["IndexName"], "FestivalMonthIndex")
        self.assertEqual(
            request["KeyConditionExpression"],
            "#entity_type = :entity_type AND begins_with(#gsi_sk, :month_prefix)",
        )
        self.assertNotIn(":pk", request["ExpressionAttributeValues"])

    def test_fixed_city_festival_seed_ignores_city_key_for_month_query(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(
            query_response={
                "Items": [
                    {
                        "festival_id": "festival-1",
                        "name": "김해 축제",
                        "country": "KR",
                        "city_id": "KR-36-4",
                        "month": 10,
                        "PK": "CITY#GIMHAE",
                        "SK": "FESTIVAL#festival-1",
                        "theme_tags": ["festival"],
                    },
                ],
            },
        )
        tool = make_dynamo_lookup_tool(dynamodb_client)

        result = tool.search_festival_city_seeds(
            country="KR",
            travel_month=10,
            travel_year=2026,
            theme_pool=["festival"],
            city_id="KR-36-4",
            city_key="CITY#GIMHAE",
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.seed_city_ids, ("KR-36-4",))
        request = dynamodb_client.query_requests[0]
        self.assertEqual(request["IndexName"], "FestivalMonthIndex")
        self.assertEqual(
            request["ExpressionAttributeValues"][":month_prefix"],
            {"S": "FESTIVAL#10"},
        )
        self.assertNotIn(":pk", request["ExpressionAttributeValues"])

    def test_festival_seed_empty_city_discovery_reports_failure(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(query_response={"Items": []})
        tool = make_dynamo_lookup_tool(dynamodb_client)

        result = tool.search_festival_city_seeds(
            country="KR",
            travel_month=6,
            travel_year=2026,
            theme_pool=["history"],
        )

        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.tier, "none")
        self.assertTrue(result.needs_clarification)
        self.assertEqual(result.failure_signals, ("no_confirmed_festival_city",))
        self.assertEqual(result.clarification["reason_code"], "festival_none")

    def test_fixed_city_empty_lookup_reports_anchor_failure(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(query_response={"Items": []})
        tool = make_dynamo_lookup_tool(dynamodb_client)

        result = tool.search_festival_city_seeds(
            country="KR",
            travel_month=6,
            travel_year=2026,
            theme_pool=["history"],
            city_id="city-1",
        )

        self.assertEqual(result.status, "needs_clarification")
        self.assertEqual(result.tier, "none")
        self.assertTrue(result.needs_clarification)
        self.assertEqual(result.failure_signals, ("anchor_city_has_no_confirmed_festival",))
        self.assertEqual(result.clarification["reason_code"], "anchor_festival_conflict")

    def test_festival_seed_normalizes_dynamodb_attribute_values(self) -> None:
        candidate = normalize_festival_candidate(
            {
                "festival_id": {"S": "festival-1"},
                "name": {"S": "바다 축제"},
                "country": {"S": "KR"},
                "PK": {"S": "CITY#SEA"},
                "SK": {"S": "FESTIVAL#festival-1"},
                "city_id": {"S": "city-1"},
                "city_key": {"S": "CITY#SEA"},
                "city_name": {"S": "해변시"},
                "month": {"N": "6"},
                "theme": {"S": "sea_coast"},
                "assigned_theme": {"S": "sea_coast"},
                "theme_tags": {"SS": ["sea_coast", "walk"]},
                "eventstartdate": {"S": "2026-06-01"},
            },
        )

        self.assertEqual(candidate.festival_id, "festival-1")
        self.assertEqual(candidate.month, 6)
        self.assertEqual(candidate.theme, "sea_coast")
        self.assertEqual(candidate.theme_tags, ("sea_coast", "walk"))
        self.assertEqual(candidate.event_start_date, "2026-06-01")
        self.assertEqual(candidate.ddb_pk, "CITY#SEA")
        self.assertEqual(candidate.ddb_sk, "FESTIVAL#festival-1")
        self.assertEqual(candidate.city_key, "CITY#SEA")


class FinalPlaceDetailEnrichmentTest(unittest.TestCase):
    """Validate final placed item detail enrichment warnings for Task 4.4."""

    def test_enrich_final_places_reads_placed_item_details(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(
            batch_get_response={
                "Responses": {
                    "lovv-table": [
                        {
                            "PK": {"S": "PLACE#1"},
                            "SK": {"S": "DETAIL#1"},
                            "overview": {"S": "조용한 바다 산책지"},
                            "visitor_count": {"N": "12"},
                        },
                    ],
                },
            },
        )
        tool = make_dynamo_lookup_tool(dynamodb_client)
        candidate = normalize_attraction_candidate(
            {
                "key": "attraction#place-1#1",
                "distance": 0.1,
                "metadata": {
                    "entity_type": "attraction",
                    "city_id": "city-1",
                    "title": "바다 산책로",
                    "theme_tags": ["바다·해안"],
                    "ddb_pk": "PLACE#1",
                    "ddb_sk": "DETAIL#1",
                },
            },
        )

        result = tool.enrich_final_places((candidate,))

        self.assertEqual(result.warnings, ())
        self.assertEqual(
            result.places[0].details,
            {
                "PK": "PLACE#1",
                "SK": "DETAIL#1",
                "overview": "조용한 바다 산책지",
                "visitor_count": 12,
            },
        )
        self.assertEqual(
            dynamodb_client.batch_get_item_requests[0]["RequestItems"]["lovv-table"]["Keys"][0],
            {
                "PK": {"S": "PLACE#1"},
                "SK": {"S": "DETAIL#1"},
            },
        )
        self.assertEqual(dynamodb_client.get_item_requests, [])

    def test_enrich_final_places_batches_placed_item_details(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(
            batch_get_response={
                "Responses": {
                    "lovv-table": [
                        {
                            "PK": {"S": "PLACE#1"},
                            "SK": {"S": "DETAIL#1"},
                            "description": {"S": "첫 번째 공개 개요"},
                        },
                        {
                            "PK": {"S": "PLACE#2"},
                            "SK": {"S": "DETAIL#2"},
                            "overview": {"S": "두 번째 공개 개요"},
                        },
                    ],
                },
            },
        )
        tool = make_dynamo_lookup_tool(dynamodb_client)
        candidates = tuple(
            normalize_attraction_candidate(
                {
                    "key": f"attraction#place-{index}#1",
                    "distance": 0.1,
                    "metadata": {
                        "entity_type": "attraction",
                        "city_id": "city-1",
                        "title": f"장소 {index}",
                        "theme_tags": ["바다·해안"],
                        "ddb_pk": f"PLACE#{index}",
                        "ddb_sk": f"DETAIL#{index}",
                    },
                },
            )
            for index in (1, 2)
        )

        result = tool.enrich_final_places(candidates)

        self.assertEqual(result.warnings, ())
        self.assertEqual(result.places[0].details["overview"], "첫 번째 공개 개요")
        self.assertEqual(result.places[1].details["overview"], "두 번째 공개 개요")
        self.assertEqual(len(dynamodb_client.batch_get_item_requests), 1)
        self.assertEqual(dynamodb_client.get_item_requests, [])

    def test_enrich_final_places_uses_exact_v2_city_pk(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(
            batch_get_response={
                "Responses": {
                    "lovv-table": [
                        {
                            "PK": {"S": "CITY#DONGHAE"},
                            "SK": {"S": "ATTRACTION#125713"},
                            "overview": {"S": "망상해변 공개 개요"},
                        },
                    ],
                },
            },
        )
        tool = make_dynamo_lookup_tool(dynamodb_client)
        candidate = normalize_attraction_candidate(
            {
                "key": "attraction#125713#1",
                "distance": 0.1,
                "metadata": {
                    "entity_type": "attraction",
                    "city_id": "KR-51-170",
                    "title": "망상해변",
                    "theme_tags": ["바다·해안"],
                    "ddb_pk": "CITY#DONGHAE",
                    "ddb_sk": "ATTRACTION#125713",
                },
            },
        )

        result = tool.enrich_final_places((candidate,))

        self.assertEqual(result.warnings, ())
        self.assertEqual(result.places[0].details["overview"], "망상해변 공개 개요")
        self.assertEqual(
            dynamodb_client.batch_get_item_requests[0]["RequestItems"]["lovv-table"]["Keys"][0],
            {
                "PK": {"S": "CITY#DONGHAE"},
                "SK": {"S": "ATTRACTION#125713"},
            },
        )

    def test_enrich_final_places_does_not_retry_legacy_city_pk(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(get_item_response={})
        tool = make_dynamo_lookup_tool(dynamodb_client)
        candidate = normalize_attraction_candidate(
            {
                "key": "attraction#125713#1",
                "distance": 0.1,
                "metadata": {
                    "entity_type": "attraction",
                    "city_id": "KR-51-170",
                    "title": "망상해변",
                    "theme_tags": ["바다·해안"],
                    "ddb_pk": "CITY#DONGHAE",
                    "ddb_sk": "ATTRACTION#125713",
                },
            },
        )

        result = tool.enrich_final_places((candidate,))

        self.assertIsNone(result.places[0].details)
        self.assertEqual(result.warnings[0].code, "missing_detail_item")
        self.assertEqual(len(dynamodb_client.batch_get_item_requests), 1)
        self.assertEqual(dynamodb_client.get_item_requests, [])
        self.assertEqual(
            dynamodb_client.batch_get_item_requests[0]["RequestItems"]["lovv-table"]["Keys"][0],
            {
                "PK": {"S": "CITY#DONGHAE"},
                "SK": {"S": "ATTRACTION#125713"},
            },
        )

    def test_enrich_final_places_only_calls_for_passed_final_items(self) -> None:
        dynamodb_client = RecordingDynamoDbClient()
        tool = make_dynamo_lookup_tool(dynamodb_client)
        placed = normalize_attraction_candidate(
            {
                "key": "attraction#placed#1",
                "distance": 0.1,
                "metadata": {
                    "entity_type": "attraction",
                    "city_id": "city-1",
                    "title": "Placed",
                    "theme_tags": ["history"],
                    "ddb_pk": "PLACE#PLACED",
                    "ddb_sk": "DETAIL#PLACED",
                },
            },
        )
        not_placed = normalize_attraction_candidate(
            {
                "key": "attraction#not-placed#1",
                "distance": 0.2,
                "metadata": {
                    "entity_type": "attraction",
                    "city_id": "city-1",
                    "title": "Not Placed",
                    "theme_tags": ["history"],
                    "ddb_pk": "PLACE#R",
                    "ddb_sk": "DETAIL#R",
                },
            },
        )

        result = tool.enrich_final_places((placed,))

        self.assertEqual(len(result.places), 1)
        self.assertEqual(result.places[0].place_id, placed.place_id)
        self.assertNotEqual(result.places[0].place_id, not_placed.place_id)
        self.assertEqual(len(dynamodb_client.batch_get_item_requests), 1)
        self.assertEqual(dynamodb_client.get_item_requests, [])

    def test_enrich_final_places_missing_keys_warns_and_keeps_null_details(self) -> None:
        dynamodb_client = RecordingDynamoDbClient()
        tool = make_dynamo_lookup_tool(dynamodb_client)
        candidate = normalize_attraction_candidate(
            {
                "key": "attraction#place-1#1",
                "distance": 0.1,
                "metadata": {
                    "entity_type": "attraction",
                    "city_id": "city-1",
                    "title": "키 없는 장소",
                    "theme_tags": ["history"],
                    "ddb_pk": "PLACE#1",
                },
            },
        )

        result = tool.enrich_final_places((candidate,))

        self.assertIsNone(result.places[0].details)
        self.assertEqual(result.warnings[0].code, "missing_detail_key")
        self.assertEqual(result.warnings[0].place_id, "attraction#place-1")
        self.assertEqual(dynamodb_client.get_item_requests, [])

    def test_enrich_final_places_dynamodb_failure_creates_warning(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(
            batch_get_exception=RuntimeError("network failed"),
        )
        tool = make_dynamo_lookup_tool(dynamodb_client)
        candidate = normalize_attraction_candidate(
            {
                "key": "attraction#place-1#1",
                "distance": 0.1,
                "metadata": {
                    "entity_type": "attraction",
                    "city_id": "city-1",
                    "title": "조회 실패 장소",
                    "theme_tags": ["history"],
                    "ddb_pk": "PLACE#1",
                    "ddb_sk": "DETAIL#1",
                },
            },
        )

        result = tool.enrich_final_places((candidate,))

        self.assertIsNone(result.places[0].details)
        self.assertEqual(result.warnings[0].code, "dynamodb_detail_failure")
        self.assertEqual(result.warnings[0].error_type, "RuntimeError")

    def test_enrich_final_places_missing_item_creates_warning(self) -> None:
        dynamodb_client = RecordingDynamoDbClient(get_item_response={})
        tool = make_dynamo_lookup_tool(dynamodb_client)
        candidate = normalize_attraction_candidate(
            {
                "key": "attraction#place-1#1",
                "distance": 0.1,
                "metadata": {
                    "entity_type": "attraction",
                    "city_id": "city-1",
                    "title": "빈 상세 장소",
                    "theme_tags": ["history"],
                    "ddb_pk": "PLACE#1",
                    "ddb_sk": "DETAIL#1",
                },
            },
        )

        result = tool.enrich_final_places((candidate,))

        self.assertIsNone(result.places[0].details)
        self.assertEqual(result.warnings[0].code, "missing_detail_item")


if __name__ == "__main__":
    unittest.main()
