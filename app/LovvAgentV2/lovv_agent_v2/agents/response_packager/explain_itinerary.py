from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from lovv_agent_v2.agents.response_packager.itinerary_explanation_mapping import (
    CandidatePackageInput,
    build_safe_summary,
    enrich_itinerary,
    fallback_audit,
)
from lovv_agent_v2.agents.response_packager.planner_copy_composer import (
    compose_planner_copy_explanation,
)
from lovv_agent_v2.tools.runtime_containers import ItineraryExplanationRuntime
from lovv_agent_v2.tools.runtime_extractors import itinerary_explanation_runtime_from_state
from lovv_agent_v2.models.schemas import PlannerExplanationAudit, PlannerOutput


@dataclass(frozen=True, slots=True)
class ItineraryExplanationInput:
    planner_output: PlannerOutput
    selected_city: Mapping[str, object]
    query: Mapping[str, object]
    runtime: ItineraryExplanationRuntime


def explain_itinerary_node(state: Mapping[str, object]) -> dict[str, object]:
    planner_output = _planner_output(state)
    if planner_output is None:
        return {}
    explained = explain_planner_output(
        ItineraryExplanationInput(
            planner_output=planner_output,
            selected_city=_selected_city(state),
            query=_query(state),
            runtime=_runtime(state),
        ),
    )
    return {
        "planner": {
            **_planner_state(state),
            "planner_output": explained.to_dict(),
            "validation_result": explained.validation_result,
        },
    }


def explain_planner_output(explanation_input: ItineraryExplanationInput) -> PlannerOutput:
    planner_output = explanation_input.planner_output
    runtime = explanation_input.runtime
    itinerary, detail_warnings = enrich_itinerary(planner_output.itinerary, runtime.dynamo_lookup)
    safe_summary = build_safe_summary(
        CandidatePackageInput(
            selected_city=explanation_input.selected_city,
            query=explanation_input.query,
            itinerary=itinerary,
            validation_result=planner_output.validation_result,
        ),
    )
    target_refs = _target_item_refs(itinerary, planner_output.validation_result)
    has_target_scope = bool(
        _text_tuple(planner_output.validation_result.get("explanation_item_place_ids")),
    )
    if has_target_scope:
        safe_summary = {
            **safe_summary,
            "copy_target_item_refs": list(target_refs),
            "copy_scope": "changed_items_only",
        }
    audit = fallback_audit(itinerary)
    validation_result = _validation_result(
        planner_output,
        itinerary=itinerary,
        detail_warnings=detail_warnings,
    )
    if has_target_scope:
        validation_result["modification_explanation_attempted"] = True
        validation_result["modification_explanation_completed"] = False
    if has_target_scope and not target_refs:
        skipped_audit = _audit_with_note(audit, "planner_copy_generation:skipped:target_not_found")
        return _replace_planner_output(planner_output, itinerary, validation_result, skipped_audit)
    if runtime.explanation_runtime is None:
        skipped_audit = _audit_with_note(audit, "planner_copy_generation:skipped:no_runtime")
        return _replace_planner_output(planner_output, itinerary, validation_result, skipped_audit)

    composed = compose_planner_copy_explanation(
        safe_summary=safe_summary,
        itinerary=itinerary,
        runtime=runtime.explanation_runtime,
        retry_limit=runtime.schema_retry_limit,
        fallback_recommendation_reasons=planner_output.recommendation_reasons,
        fallback_itinerary_flow_reason=planner_output.itinerary_flow_reason,
        fallback_explanation_audit=audit,
        target_item_refs=target_refs,
    )
    validation_result["planner_copy_generation_used_llm"] = composed.used_llm
    if has_target_scope:
        expected_refs = set(target_refs)
        copied_refs = {
            f"item:{index}"
            for index, item in enumerate(composed.itinerary)
            if f"item:{index}" in expected_refs
            and item.get("copy_source") == "llm_planner_copy"
        }
        validation_result["modification_explanation_completed"] = (
            expected_refs == set(composed.applied_item_refs) == copied_refs
        )
    return PlannerOutput(
        itinerary=composed.itinerary,
        recommendation_reasons=composed.recommendation_reasons,
        itinerary_flow_reason=composed.itinerary_flow_reason,
        external_links=planner_output.external_links,
        confidence=planner_output.confidence,
        user_notice=planner_output.user_notice,
        validation_result=validation_result,
        alternative_itinerary=planner_output.alternative_itinerary,
        explanation_audit=asdict(composed.explanation_audit),
    )


def _validation_result(
    planner_output: PlannerOutput,
    *,
    itinerary: Sequence[Mapping[str, Any]],
    detail_warnings: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    validation = {
        **planner_output.validation_result,
        "detail_enrichment_warning_count": len(detail_warnings),
        "planner_copy_generation_used_llm": False,
    }
    if detail_warnings:
        validation["detail_enrichment_warnings"] = tuple(dict(warning) for warning in detail_warnings)
    if itinerary:
        target_refs = _target_item_refs(itinerary, validation)
        validation["itinerary_explanation_item_count"] = len(target_refs) if target_refs else len(itinerary)
    return validation


def _target_item_refs(
    itinerary: Sequence[Mapping[str, Any]],
    validation_result: Mapping[str, Any],
) -> tuple[str, ...]:
    place_ids = _text_tuple(validation_result.get("explanation_item_place_ids"))
    if not place_ids:
        return ()
    target_ids = set(place_ids)
    return tuple(
        f"item:{index}"
        for index, item in enumerate(itinerary)
        if _place_id(item) in target_ids
    )


def _text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _place_id(item: Mapping[str, Any]) -> str | None:
    value = item.get("placeId", item.get("place_id"))
    return value.strip() if isinstance(value, str) and value.strip() else None


def _audit_with_note(audit: PlannerExplanationAudit, note: str) -> PlannerExplanationAudit:
    return PlannerExplanationAudit(
        reason_refs=audit.reason_refs,
        itinerary_flow_refs=audit.itinerary_flow_refs,
        hidden_internal_notes=(*audit.hidden_internal_notes, note),
    )


def _replace_planner_output(
    planner_output: PlannerOutput,
    itinerary: tuple[dict[str, Any], ...],
    validation_result: dict[str, Any],
    audit: PlannerExplanationAudit,
) -> PlannerOutput:
    return PlannerOutput(
        itinerary=itinerary,
        recommendation_reasons=planner_output.recommendation_reasons,
        itinerary_flow_reason=planner_output.itinerary_flow_reason,
        external_links=planner_output.external_links,
        confidence=planner_output.confidence,
        user_notice=planner_output.user_notice,
        validation_result=validation_result,
        alternative_itinerary=planner_output.alternative_itinerary,
        explanation_audit=asdict(audit),
    )


def _runtime(state: Mapping[str, object]) -> ItineraryExplanationRuntime:
    return itinerary_explanation_runtime_from_state(state)


def _planner_output(state: Mapping[str, object]) -> PlannerOutput | None:
    planner = _planner_state(state)
    value = planner.get("planner_output")
    if value is None:
        return None
    if isinstance(value, PlannerOutput):
        return value
    if isinstance(value, Mapping):
        return PlannerOutput.from_mapping(value)
    return None


def _planner_state(state: Mapping[str, object]) -> dict[str, object]:
    planner = state.get("planner")
    return dict(planner) if isinstance(planner, Mapping) else {}


def _selected_city(state: Mapping[str, object]) -> Mapping[str, object]:
    city_select = state.get("city_select")
    if isinstance(city_select, Mapping):
        result = city_select.get("city_selection_result")
        if isinstance(result, Mapping):
            city = result.get("selected_city")
            if isinstance(city, Mapping):
                return city
    return {}

def _query(state: Mapping[str, object]) -> Mapping[str, object]:
    intent = state.get("intent")
    if isinstance(intent, Mapping):
        city_input = intent.get("city_select_input")
        if isinstance(city_input, Mapping):
            return {
                "cleaned_raw_query": city_input.get("cleaned_raw_query"),
                "soft_preference_query": city_input.get("soft_preference_query"),
            }
    return {}
