from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from lovv_agent_v2.models.clarification import (
    Clarification,
    ClarificationApply,
    ClarificationOption,
)
from lovv_agent_v2.models.clarification_texts import (
    clarification_helper_text,
    clarification_label_text,
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
                label=_label_text("festival_none", "continue_without_festival", "축제 없이 계속"),
                apply=ClarificationApply(include_festivals=False, destination_id=None),
                then="rerun_discovery",
                helper_text=_helper_text("festival_none", "continue_without_festival", "축제 조건을 제외하고 여행지를 다시 찾습니다."),
            ),
            ClarificationOption(
                option_id="search_any_festival_theme",
                label=_label_text("festival_none", "search_any_festival_theme", "테마와 무관하게 축제 찾기"),
                apply=ClarificationApply(
                    include_festivals=True,
                    destination_id=None,
                    active_required_themes=(),
                    festival_theme_agnostic=True,
                ),
                then="rerun_discovery",
                helper_text=_helper_text("festival_none", "search_any_festival_theme", "선호 테마보다 축제 여부를 우선해서 확정 축제 도시를 다시 찾습니다."),
            ),
            ClarificationOption(
                option_id="revise_conditions",
                label=_label_text("festival_none", "revise_conditions", "조건 다시 입력"),
                apply=ClarificationApply(),
                then="abort",
                helper_text=_helper_text("festival_none", "revise_conditions", "이번 실행을 멈추고 여행 조건을 다시 입력합니다."),
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
            label=_label_text(
                "festival_tentative",
                f"accept_tentative_festival:{candidate.festival_id}",
                f"{candidate.city_name} {candidate.festival_label} 일정 위험을 수락",
            ),
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
            helper_text=_helper_text("festival_tentative", f"accept_tentative_festival:{candidate.festival_id}", "확정되지 않은 축제 일정일 수 있음을 감수하고 해당 도시로 진행합니다."),
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
                label=_label_text("festival_tentative", "continue_without_festival", "축제 없이 계속"),
                apply=ClarificationApply(include_festivals=False, destination_id=None),
                then="rerun_discovery",
                helper_text=_helper_text("festival_tentative", "continue_without_festival", "잠정 축제 후보를 제외하고 여행지를 다시 찾습니다."),
            ),
            ClarificationOption(
                option_id="revise_conditions",
                label=_label_text("festival_tentative", "revise_conditions", "조건 다시 입력"),
                apply=ClarificationApply(),
                then="abort",
                helper_text=_helper_text("festival_tentative", "revise_conditions", "이번 실행을 멈추고 여행 조건을 다시 입력합니다."),
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
            label=_label_text(
                "anchor_festival_conflict",
                f"switch_to_festival_city:{candidate.city_id}",
                f"{candidate.city_name}로 변경",
            ),
            apply=ClarificationApply(
                include_festivals=True,
                destination_id=candidate.city_id,
                destination_label=candidate.city_name,
                festival_id=candidate.festival_id,
                festival_label=candidate.festival_label,
            ),
            then="anchor",
            helper_text=_helper_text("anchor_festival_conflict", f"switch_to_festival_city:{candidate.city_id}", "축제 조건을 유지하기 위해 해당 축제가 있는 도시로 바꿉니다."),
        )
        for candidate in confirmed
    )
    return Clarification(
        reason_code="anchor_festival_conflict",
        prompt="요청한 도시에 해당 월의 확정 축제가 없습니다. 축제 조건 없이 진행할까요?",
        options=(
            ClarificationOption(
                option_id="continue_without_festival_in_anchor",
                label=_label_text("anchor_festival_conflict", "continue_without_festival_in_anchor", "이 도시에서 축제 없이 계속"),
                apply=ClarificationApply(
                    include_festivals=False,
                    destination_id=requested_city,
                ),
                then="anchor",
                helper_text=_helper_text("anchor_festival_conflict", "continue_without_festival_in_anchor", "요청한 도시는 유지하고 축제 조건만 제외해 일정을 만듭니다."),
            ),
            *switch_options,
            ClarificationOption(
                option_id="revise_conditions",
                label=_label_text("anchor_festival_conflict", "revise_conditions", "조건 다시 입력"),
                apply=ClarificationApply(),
                then="abort",
                helper_text=_helper_text("anchor_festival_conflict", "revise_conditions", "이번 실행을 멈추고 여행 조건을 다시 입력합니다."),
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


def _helper_text(reason_code: str, option_id: str, default: str) -> str:
    return clarification_helper_text(reason_code, option_id, default)


def _label_text(reason_code: str, option_id: str, default: str) -> str:
    return clarification_label_text(reason_code, option_id, default)
