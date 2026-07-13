from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lovv_agent_v2.infra.adapters.bedrock_converse import (
    RuntimeInvoker,
    build_structured_converse_request,
    invoke_structured_output,
)
from lovv_agent_v2.models.schemas import (
    ExplanationReasonRef,
    PlannerExplanationAudit,
    SchemaValidationError,
)

PLANNER_COPY_EXPLANATION_SCHEMA_NAME = "planner_copy_explanation_output"
PLANNER_COPY_EXPLANATION_PROMPT_PATH = Path(__file__).with_name("prompts") / "planner_copy_explanation.v1.json"

PLANNER_COPY_EXPLANATION_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["item_copies", "recommendation_reasons", "itinerary_flow_reason"],
    "properties": {
        "item_copies": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["item_ref", "title", "body", "reason"],
                "properties": {
                    "item_ref": {"type": "string"},
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
        "recommendation_reasons": {
            "type": "array",
            "minItems": 1,
            "maxItems": 3,
            "items": {"type": "string"},
        },
        "itinerary_flow_reason": {"type": "string"},
    },
}

INTERNAL_EXPLANATION_TERMS = (
    "top k",
    "top_k",
    "topk",
    "점수",
    "스코어",
    "랭킹 공식",
    "ranking formula",
    "raw retrieval",
    "seed",
    "cluster",
    "relevance",
    "클러스터",
    "관련도",
    "score audit",
    "dynamodb",
    "s3 vector",
)


@dataclass(frozen=True, slots=True)
class PlannerCopyExplanation:
    itinerary: tuple[dict[str, Any], ...]
    recommendation_reasons: tuple[str, ...]
    itinerary_flow_reason: str
    explanation_audit: PlannerExplanationAudit
    used_llm: bool


def compose_planner_copy_explanation(
    *,
    safe_summary: Mapping[str, Any],
    itinerary: Sequence[Mapping[str, Any]],
    runtime: RuntimeInvoker,
    retry_limit: int,
    fallback_recommendation_reasons: Sequence[str],
    fallback_itinerary_flow_reason: str,
    fallback_explanation_audit: PlannerExplanationAudit,
) -> PlannerCopyExplanation:
    item_refs = tuple(_item_ref(index) for index, _ in enumerate(itinerary))
    request = build_structured_converse_request(
        messages=[{"role": "user", "content": [{"text": json.dumps(safe_summary, ensure_ascii=False)}]}],
        system=[{"text": _prompt_text()}],
        schema_name=PLANNER_COPY_EXPLANATION_SCHEMA_NAME,
        schema=PLANNER_COPY_EXPLANATION_OUTPUT_SCHEMA,
        schema_description="Lovv V2 Planner Korean copy and explanation output",
        reasoning_effort="low",
    )
    result = invoke_structured_output(
        runtime=runtime,
        request=request,
        retry_limit=retry_limit,
        validator=lambda payload: validate_planner_copy_explanation_output(
            payload,
            allowed_item_refs=item_refs,
        ),
    )
    if not result.ok:
        return PlannerCopyExplanation(
            itinerary=tuple(dict(item) for item in itinerary),
            recommendation_reasons=tuple(fallback_recommendation_reasons),
            itinerary_flow_reason=fallback_itinerary_flow_reason,
            explanation_audit=_append_hidden_note(
                fallback_explanation_audit,
                f"planner_copy_generation:schema_failure:{result.attempts}",
            ),
            used_llm=False,
        )
    generated = result.value
    updated_itinerary = _apply_item_copies(itinerary, generated["item_copies"])
    return PlannerCopyExplanation(
        itinerary=updated_itinerary,
        recommendation_reasons=tuple(generated["recommendation_reasons"]),
        itinerary_flow_reason=generated["itinerary_flow_reason"],
        explanation_audit=_generated_explanation_audit(
            itinerary=updated_itinerary,
            recommendation_reasons=generated["recommendation_reasons"],
            base_audit=fallback_explanation_audit,
            status=_summary_status(safe_summary),
        ),
        used_llm=True,
    )


def validate_planner_copy_explanation_output(
    payload: Mapping[str, Any],
    *,
    allowed_item_refs: Sequence[str],
) -> dict[str, Any]:
    if set(payload) != {"item_copies", "recommendation_reasons", "itinerary_flow_reason"}:
        raise SchemaValidationError("planner copy output contains unsupported fields")
    allowed_refs = set(allowed_item_refs)
    raw_item_copies = payload["item_copies"]
    if not isinstance(raw_item_copies, (list, tuple)):
        raise SchemaValidationError("item_copies must be a list")
    item_copies = tuple(_validate_item_copy(item, allowed_refs) for item in raw_item_copies)
    raw_reasons = payload["recommendation_reasons"]
    if not isinstance(raw_reasons, (list, tuple)) or not raw_reasons:
        raise SchemaValidationError("recommendation_reasons must be a non-empty list")
    if len(raw_reasons) > 3:
        raise SchemaValidationError("recommendation_reasons must contain at most 3 items")
    return {
        "item_copies": item_copies,
        "recommendation_reasons": tuple(_safe_public_text(item, "recommendation_reasons") for item in raw_reasons),
        "itinerary_flow_reason": _safe_public_text(payload["itinerary_flow_reason"], "itinerary_flow_reason"),
    }


def _validate_item_copy(item: Any, allowed_refs: set[str]) -> dict[str, str]:
    if not isinstance(item, Mapping):
        raise SchemaValidationError("item_copies item must be an object")
    if set(item) != {"item_ref", "title", "body", "reason"}:
        raise SchemaValidationError("item_copies item contains unsupported fields")
    item_ref = _safe_public_text(item["item_ref"], "item_ref")
    if item_ref not in allowed_refs:
        raise SchemaValidationError(f"unknown item_ref: {item_ref}")
    return {
        "item_ref": item_ref,
        "title": _safe_public_text(item["title"], "title"),
        "body": _safe_public_text(item["body"], "body"),
        "reason": _safe_public_text(item["reason"], "reason"),
    }


def _apply_item_copies(
    itinerary: Sequence[Mapping[str, Any]],
    item_copies: Sequence[Mapping[str, str]],
) -> tuple[dict[str, Any], ...]:
    copies_by_ref = {copy["item_ref"]: copy for copy in item_copies}
    updated: list[dict[str, Any]] = []
    for index, item in enumerate(itinerary):
        copied = dict(item)
        if (copy := copies_by_ref.get(_item_ref(index))) is not None:
            copied.update(
                {
                    "title": copy["title"],
                    "body": copy["body"],
                    "reason": copy["reason"],
                    "copy_source": "llm_planner_copy",
                },
            )
        updated.append(copied)
    return tuple(updated)


def _generated_explanation_audit(
    *,
    itinerary: Sequence[Mapping[str, Any]],
    recommendation_reasons: Sequence[str],
    base_audit: PlannerExplanationAudit,
    status: str,
) -> PlannerExplanationAudit:
    evidence_refs = tuple(_itinerary_evidence_refs(itinerary)) or ("selected_city",)
    return PlannerExplanationAudit(
        reason_refs=tuple(
            ExplanationReasonRef(
                reason_id=f"recommendationReasons[{index}]",
                evidence_refs=evidence_refs,
                reason_codes=("llm_grounded_copy",),
                reason_text=reason,
            )
            for index, reason in enumerate(recommendation_reasons)
        ),
        itinerary_flow_refs=tuple(_itinerary_evidence_refs(itinerary)),
        hidden_internal_notes=(*base_audit.hidden_internal_notes, f"planner_copy_generation:llm_used:{status}"),
    )


def _append_hidden_note(audit: PlannerExplanationAudit, note: str) -> PlannerExplanationAudit:
    return PlannerExplanationAudit(
        reason_refs=audit.reason_refs,
        itinerary_flow_refs=audit.itinerary_flow_refs,
        hidden_internal_notes=(*audit.hidden_internal_notes, note),
    )


def _itinerary_evidence_refs(itinerary: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    refs: list[str] = []
    for item in itinerary:
        if item.get("item_type") == "attraction" and isinstance(item.get("placeId"), str):
            refs.append(f"place:{item['placeId']}")
        if item.get("item_type") == "festival" and isinstance(item.get("festivalId"), str):
            refs.append(f"festival:{item['festivalId']}")
    return tuple(refs)


def _item_ref(index: int) -> str:
    return f"item:{index}"


def _safe_public_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    if any(term in normalized.lower() for term in INTERNAL_EXPLANATION_TERMS):
        raise SchemaValidationError(f"{field_name} contains an internal term")
    return normalized


def _summary_status(safe_summary: Mapping[str, Any]) -> str:
    validation = safe_summary.get("validation_result")
    if isinstance(validation, Mapping):
        status = validation.get("planner_status_gate") or validation.get("status")
        if isinstance(status, str) and status.strip():
            return status.strip()
    return "ok"


def _prompt_text() -> str:
    prompt = json.loads(PLANNER_COPY_EXPLANATION_PROMPT_PATH.read_text(encoding="utf-8"))
    if not isinstance(prompt, Mapping):
        raise SchemaValidationError("planner copy prompt must be a JSON object")
    return json.dumps(prompt, ensure_ascii=False, indent=2, sort_keys=True)
