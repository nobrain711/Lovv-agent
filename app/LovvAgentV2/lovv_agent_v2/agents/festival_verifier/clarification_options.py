from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from lovv_agent_v2.models.clarification import (
    Clarification,
    ClarificationApply,
    ClarificationOption,
)


class FestivalOptionCandidate(Protocol):
    @property
    def city_id(self) -> str: ...

    @property
    def city_name(self) -> str: ...

    @property
    def festival_id(self) -> str: ...

    @property
    def festival_label(self) -> str: ...


def festival_none_clarification(audit: Mapping[str, Any]) -> Clarification:
    prompt = "요청한 월에 확정된 축제 도시를 찾지 못했습니다. 축제 조건 없이 계속할까요?"
    return Clarification(
        reason_code="festival_none",
        prompt=prompt,
        options=(
            ClarificationOption(
                option_id="continue_without_festival",
                label="축제 없이 계속",
                apply=ClarificationApply(include_festivals=False, destination_id=None),
                then="rerun_discovery",
            ),
            ClarificationOption(
                option_id="revise_conditions",
                label="조건 다시 입력",
                apply=ClarificationApply(),
                then="abort",
            ),
        ),
        context=dict(audit),
        failure_signals=("no_confirmed_festival_city",),
    )


def festival_tentative_clarification(
    candidates: Sequence[FestivalOptionCandidate],
    audit: Mapping[str, Any],
) -> Clarification:
    options = tuple(
        ClarificationOption(
            option_id=f"accept_tentative_festival:{candidate.festival_id}",
            label=f"{candidate.city_name} {candidate.festival_label} 일정 위험을 수락",
            apply=ClarificationApply(
                include_festivals=True,
                destination_id=candidate.city_id,
                destination_label=candidate.city_name,
                festival_id=candidate.festival_id,
                festival_label=candidate.festival_label,
                allow_tentative_festivals=True,
                accepted_festival_risk=True,
            ),
            then="anchor",
        )
        for candidate in candidates
    )
    return Clarification(
        reason_code="festival_tentative",
        prompt="확정 일정은 없고 잠정 축제 후보만 있습니다. 이 위험을 수락할까요?",
        options=(
            *options,
            ClarificationOption(
                option_id="continue_without_festival",
                label="축제 없이 계속",
                apply=ClarificationApply(include_festivals=False, destination_id=None),
                then="rerun_discovery",
            ),
        ),
        context=dict(audit),
        failure_signals=("tentative_festival_requires_user_acceptance",),
    )


def anchor_conflict_clarification(
    *,
    requested_city: str,
    confirmed: Sequence[FestivalOptionCandidate],
    audit: Mapping[str, Any],
) -> Clarification:
    switch_options = tuple(
        ClarificationOption(
            option_id=f"switch_to_festival_city:{candidate.city_id}",
            label=f"{candidate.city_name}로 변경",
            apply=ClarificationApply(
                include_festivals=True,
                destination_id=candidate.city_id,
                destination_label=candidate.city_name,
                festival_id=candidate.festival_id,
                festival_label=candidate.festival_label,
            ),
            then="anchor",
        )
        for candidate in confirmed
    )
    return Clarification(
        reason_code="anchor_festival_conflict",
        prompt="요청한 도시에 해당 월의 확정 축제가 없습니다. 축제 조건 없이 진행할까요?",
        options=(
            ClarificationOption(
                option_id="continue_without_festival_in_anchor",
                label="이 도시에서 축제 없이 계속",
                apply=ClarificationApply(
                    include_festivals=False,
                    destination_id=requested_city,
                ),
                then="anchor",
            ),
            *switch_options,
            ClarificationOption(
                option_id="revise_conditions",
                label="조건 다시 입력",
                apply=ClarificationApply(),
                then="abort",
            ),
        ),
        context=dict(audit),
        failure_signals=("anchor_city_has_no_confirmed_festival",),
    )


__all__ = [
    "anchor_conflict_clarification",
    "festival_none_clarification",
    "festival_tentative_clarification",
]
