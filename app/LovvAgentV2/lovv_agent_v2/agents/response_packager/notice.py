from __future__ import annotations

from collections.abc import Sequence


def unsupported_notice(unsupported_conditions: Sequence[str]) -> str:
    if not unsupported_conditions:
        return ""
    return "현재 지원하지 않는 조건은 안내만 반영했습니다: " + ", ".join(
        str(item) for item in unsupported_conditions
    )


def joined_notice(
    planner_notices: Sequence[str],
    unsupported_conditions: Sequence[str],
) -> str:
    notices = [str(notice) for notice in planner_notices if str(notice).strip()]
    unsupported = unsupported_notice(unsupported_conditions)
    if unsupported:
        notices.append(unsupported)
    return " ".join(notices)


__all__ = ["joined_notice", "unsupported_notice"]
