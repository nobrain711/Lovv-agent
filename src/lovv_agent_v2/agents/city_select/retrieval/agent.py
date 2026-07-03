from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.agents.city_select.domain.contracts import CitySelectContext
from lovv_agent_v2.agents.city_select.retrieval.policy import (
    allowed_city_pk,
    prepare_city_select_context,
)
from lovv_agent_v2.agents.city_select.retrieval.flow import (
    allowed_city_ids,
    city_select_failure_state,
    embedding_query_text,
    merge_duplicate_candidates,
    package_failure,
    retrieval_audit,
    retrieve_allowed_city_pool_by_theme,
    retrieve_by_theme,
)
from lovv_agent_v2.agents.city_select.tools import CitySelectTools


@dataclass(frozen=True, slots=True)
class CitySelectRetrievalRequest:
    candidate_input: Mapping[str, Any]
    allowed_city_ids: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class CitySelectRetrievalOutput:
    city_select: dict[str, Any]


@dataclass(frozen=True, slots=True)
class CitySelectRetrievalAgent:
    tools: CitySelectTools | None = None
    tools_provider: Callable[[], CitySelectTools] | None = None

    def run(self, request: CitySelectRetrievalRequest) -> CitySelectRetrievalOutput:
        context = prepare_city_select_context(request.candidate_input)
        if context.include_festivals and request.allowed_city_ids is None:
            fail_pkg = package_failure(
                context,
                status="error",
                failure_signal="missing_festival_gate_allowed_city_ids",
                needs_clarification=False,
                retrieval_audit={
                    "festival_gate_required": True,
                    "reason": "city_select_requires_festival_gate_allowed_city_ids",
                },
            )
            return CitySelectRetrievalOutput(city_select_failure_state(fail_pkg))

        if not context.theme_split.searchable_place_themes:
            fail_pkg = package_failure(
                context,
                status="no_candidate",
                failure_signal="no_searchable_place_theme",
                needs_clarification=True,
                clarifying_question="현재 조건에서는 검색 가능한 관광 테마가 없습니다.",
            )
            return CitySelectRetrievalOutput(city_select_failure_state(fail_pkg))

        tools = self._tools()
        query_vector = tools.embedding.embed_query(embedding_query_text(context))
        anchor_ddb_pk = (
            allowed_city_pk(context.candidate_input.destination_id)
            if context.candidate_input.destination_id
            else None
        )
        preferred_city_ids, disliked_city_ids = _nationwide_region_filters(context)
        retrieved = _retrieve_for_context(
            tools.destination_search,
            query_vector=query_vector,
            themes=context.theme_split.searchable_place_themes,
            include_festivals=context.include_festivals,
            allowed_city_ids=request.allowed_city_ids,
            anchor_ddb_pk=anchor_ddb_pk,
            preferred_city_ids=preferred_city_ids,
            disliked_city_ids=disliked_city_ids,
        )
        merged_candidates = merge_duplicate_candidates(retrieved)
        allowed = allowed_city_ids(context=context, allowed_city_ids=request.allowed_city_ids)
        pruned_groups = tools.destination_search.prune_cities(
            merged_candidates,
            context.theme_split.searchable_place_themes,
            allowed_city_ids=allowed,
        )
        audit = retrieval_audit(
            context=context,
            retrieved_count=len(retrieved),
            merged_count=len(merged_candidates),
            survived_city_count=len(pruned_groups.survived_groups) if pruned_groups else 0,
            eliminated_cities=tuple(pruned_groups.eliminated_cities) if pruned_groups else (),
        )
        return CitySelectRetrievalOutput(
            {
                "retrieval_audit": audit,
                "scoring_audit": {},
                "scratch": {
                    "pruned_groups": pruned_groups,
                    "festival_seed_result": None,
                    "context": context,
                    "raw_query_vector": list(query_vector),
                    "retrieved_count": len(retrieved),
                    "merged_count": len(merged_candidates),
                },
            },
        )

    def _tools(self) -> CitySelectTools:
        if self.tools is not None:
            return self.tools
        if self.tools_provider is not None:
            return self.tools_provider()
        raise RuntimeError("CitySelectRetrievalAgent requires tools")


def _retrieve_for_context(
    destination_search: Any,
    *,
    query_vector: Sequence[float],
    themes: Sequence[str],
    include_festivals: bool,
    allowed_city_ids: Sequence[str] | None,
    anchor_ddb_pk: str | None,
    preferred_city_ids: Sequence[str],
    disliked_city_ids: Sequence[str],
) -> tuple[Any, ...]:
    if include_festivals and allowed_city_ids is not None:
        return retrieve_allowed_city_pool_by_theme(
            destination_search,
            query_vector=query_vector,
            themes=themes,
            allowed_city_ids=allowed_city_ids,
        )
    return retrieve_by_theme(
        destination_search,
        query_vector=query_vector,
        themes=themes,
        city_id=None,
        ddb_pk=anchor_ddb_pk,
        preferred_city_ids=preferred_city_ids,
        disliked_city_ids=disliked_city_ids,
    )


def _nationwide_region_filters(
    context: CitySelectContext,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if context.include_festivals or context.candidate_input.destination_id is not None:
        return (), ()
    return (
        tuple(context.candidate_input.preferred_region_ids),
        tuple(context.candidate_input.disliked_region_ids),
    )
