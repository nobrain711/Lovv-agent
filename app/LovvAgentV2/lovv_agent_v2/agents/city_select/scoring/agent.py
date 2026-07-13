from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.agents.city_select.scoring.service import (
    CANDIDATE_SUFFICIENCY_THRESHOLD,
    ScoringTool,
)
from lovv_agent_v2.agents.city_select.scoring.audit import (
    scoring_audit,
    theme_evidence_summary,
)
from lovv_agent_v2.agents.city_select.scoring.city_payload import _selected_city
from lovv_agent_v2.agents.city_select.scoring.payloads import (
    _alternative_city_payload,
    _annotate_city_rankings,
    _headline_seed,
    _passthrough_payload,
    _representative_seed_payload,
    _seed_payloads,
    _selection_reason_codes,
    _theme_evidence_payload,
)
from lovv_agent_v2.agents.city_select.scoring.ranking import (
    _rank_cities,
    _score_groups,
)
from lovv_agent_v2.agents.city_select.scoring.failures import (
    ScoringFailureContext,
    no_city_after_theme_gate,
    no_scored_city,
)
from lovv_agent_v2.tools.runtime_containers import CitySelectScoringTools
from lovv_agent_v2.agents.city_select.retrieval.flow import retrieval_audit
from lovv_agent_v2.models.schemas import CitySelectionResult


@dataclass(frozen=True, slots=True)
class CitySelectScoringRequest:
    city_select_state: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class CitySelectScoringAgent:
    tools: CitySelectScoringTools | None = None
    tools_provider: Callable[[], CitySelectScoringTools] | None = None
    scoring: ScoringTool = ScoringTool()

    def run(self, request: CitySelectScoringRequest) -> dict[str, dict[str, Any]]:
        scratch = request.city_select_state.get("scratch")
        if not isinstance(scratch, Mapping) or "pruned_groups" not in scratch:
            return {}

        pruned_groups = scratch.get("pruned_groups")
        festival_seed_result = scratch.get("festival_seed_result")
        context = scratch.get("context")
        retrieved_count = int(scratch.get("retrieved_count", 0))
        merged_count = int(scratch.get("merged_count", 0))
        failure_context = ScoringFailureContext(
            context=context,
            pruned_groups=pruned_groups,
            retrieved_count=retrieved_count,
            merged_count=merged_count,
        )

        if not pruned_groups or not pruned_groups.survived_groups:
            return no_city_after_theme_gate(failure_context)

        primary_budget = CANDIDATE_SUFFICIENCY_THRESHOLD
        scored_groups = _score_groups(
            pruned_groups.survived_groups,
            context=context,
            scoring=self.scoring,
        )
        city_rankings = _rank_cities(
            scored_groups,
            context=context,
            scoring=self.scoring,
            primary_budget=primary_budget,
            dynamo_lookup=self._tools().dynamo_lookup,
        )

        if not city_rankings:
            return no_scored_city(failure_context)

        selected_rank_index = 0
        selected_city_id = city_rankings[selected_rank_index]["city_id"]
        selected_group = scored_groups[selected_city_id]
        raw_query_vector = scratch.get("raw_query_vector")
        status = "ok"
        selected_city = _selected_city(
            selected_city_id,
            selected_group,
            context=context,
            status=status,
            selected_rank_index=selected_rank_index,
        )
        annotated_rankings = _annotate_city_rankings(
            city_rankings,
            selected_city_id=selected_city_id,
        )
        representative_seed_result = max(
            selected_group,
            key=lambda place: place.score_components.get("raw_similarity", 0.0),
        )
        representative_seed = _representative_seed_payload(
            representative_seed_result,
        )
        evidence_summary = theme_evidence_summary(
            selected_group,
            context.theme_split.searchable_place_themes,
        )
        missing_themes = (
            pruned_groups.missing_themes_by_city.get(selected_city_id, ())
            if pruned_groups and pruned_groups.missing_themes_by_city
            else ()
        )
        selected_ranking = next(
            ranking for ranking in city_rankings if ranking["city_id"] == selected_city_id
        )
        score_breakdown = selected_ranking.get("score_breakdown", {})
        alternative_city = _alternative_city_payload(
            city_rankings,
            scored_groups,
            selected_city_id=selected_city_id,
            themes=context.theme_split.searchable_place_themes,
        )
        seeds = _seed_payloads(
            selected_group,
            context.theme_split.searchable_place_themes,
        )
        audit = retrieval_audit(
            context=context,
            retrieved_count=retrieved_count,
            merged_count=merged_count,
            survived_city_count=len(pruned_groups.survived_groups),
            eliminated_cities=tuple(pruned_groups.eliminated_cities),
        )
        planner_hints = {}
        if isinstance(raw_query_vector, list):
            planner_hints["raw_query_vector"] = raw_query_vector
        city_selection_result = CitySelectionResult(
            selected_city=selected_city,
            alternative_city=alternative_city,
            selection_reason_code=_selection_reason_codes(
                context=context,
                score_breakdown=score_breakdown,
                alternative_city=alternative_city,
            ),
            representative_seed=representative_seed,
            seeds=seeds,
            headline_seed=_headline_seed(seeds),
            theme_evidence=_theme_evidence_payload(
                selected_group,
                context.theme_split.searchable_place_themes,
            ),
            theme_evidence_summary=evidence_summary,
            missing_themes=tuple(missing_themes),
            passthrough=_passthrough_payload(context),
            score_breakdown=score_breakdown,
            retrieval_audit=audit,
            planner_hints=planner_hints,
        )
        return {
            "city_select": {
                "city_selection_result": city_selection_result.to_dict(),
                "status": status,
                "clarification": None,
                "retrieval_audit": audit,
                "scoring_audit": scoring_audit(
                    context=context,
                    annotated_rankings=annotated_rankings,
                    festival_seed_result=festival_seed_result,
                    selected_city_id=selected_city_id,
                    coverage_audit={},
                    candidate_counts={
                        "retrieved": retrieved_count,
                        "merged": merged_count,
                        "scored": sum(len(group) for group in scored_groups.values()),
                        "city_count": len(city_rankings),
                    },
                    status=status,
                    retrieval_audit=audit,
                ),
            },
        }

    def _tools(self) -> CitySelectScoringTools:
        if self.tools is not None:
            return self.tools
        if self.tools_provider is not None:
            return self.tools_provider()
        raise RuntimeError("CitySelectScoringAgent requires tools")
