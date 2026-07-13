"""Tool dependency containers and protocols shared across V2 agents.

Consolidates the runtime container/protocol definitions that used to live in
per-agent ``tools.py`` modules (``city_select``, ``festival_verifier``,
``planner``, ``intent``, ``response_packager``) into one shared module. See
docs/specs/v2/LOVV_V2_TOOL_CODE_CONSOLIDATION_SPEC.md sections 3.1 and 6.

Naming changes applied during the move (spec section 6):

- planner protocol ``DestinationSearchTool`` -> ``DestinationSearchPort``
  (removes the name clash with the real
  ``tools.destination_search.DestinationSearchTool`` implementation).
- planner protocol ``EmbeddingTool`` -> ``EmbeddingPort``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

from lovv_agent_v2.infra.adapters.bedrock_converse import RuntimeInvoker
from lovv_agent_v2.infra.adapters.embeddings import BedrockEmbeddingAdapter
from lovv_agent_v2.infra.dynamo_lookup import DynamoLookupTool, FestivalSeedResult
from lovv_agent_v2.tools.destination_search import DestinationSearchTool

DEFAULT_SCHEMA_RETRY_LIMIT: Final = 2


@dataclass(frozen=True, slots=True)
class CitySelectTools:
    destination_search: DestinationSearchTool
    dynamo_lookup: DynamoLookupTool
    embedding: BedrockEmbeddingAdapter


@dataclass(frozen=True, slots=True)
class CitySelectScoringTools:
    dynamo_lookup: DynamoLookupTool


class FestivalCandidateLookupTool(Protocol):
    def search_festival_city_seeds(
        self,
        *,
        country: str,
        travel_month: int,
        travel_year: int | None = None,
        theme_pool: Sequence[str],
        city_id: str | None = None,
        city_key: str | None = None,
        max_candidates: int | None = None,
    ) -> FestivalSeedResult: ...


@dataclass(frozen=True, slots=True)
class FestivalVerifierTools:
    festival_lookup: FestivalCandidateLookupTool


class DestinationSearchPort(Protocol):
    def search_candidates(
        self,
        query_vector: Sequence[float],
        *,
        top_k: int,
        city_id: str | None = None,
        ddb_pk: str | None = None,
        theme: str | None = None,
    ) -> Sequence[object]: ...


class EmbeddingPort(Protocol):
    def embed_query(self, query: str) -> Sequence[float]: ...


@dataclass(frozen=True, slots=True)
class PlannerRuntimeTools:
    destination_search: DestinationSearchPort
    embedding: EmbeddingPort


@dataclass(frozen=True, slots=True)
class IntentPromptRuntime:
    runtime: RuntimeInvoker | None = None
    schema_retry_limit: int = DEFAULT_SCHEMA_RETRY_LIMIT


@dataclass(frozen=True, slots=True)
class ItineraryExplanationRuntime:
    explanation_runtime: RuntimeInvoker | None = None
    dynamo_lookup: Any | None = None
    schema_retry_limit: int = DEFAULT_SCHEMA_RETRY_LIMIT


__all__ = [
    "DEFAULT_SCHEMA_RETRY_LIMIT",
    "CitySelectScoringTools",
    "CitySelectTools",
    "DestinationSearchPort",
    "EmbeddingPort",
    "FestivalCandidateLookupTool",
    "FestivalVerifierTools",
    "IntentPromptRuntime",
    "ItineraryExplanationRuntime",
    "PlannerRuntimeTools",
]
