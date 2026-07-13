from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from lovv_agent_v2.agents.city_select.scoring.service import PlaceScoreResult
from lovv_agent_v2.agents.city_select.scoring.payloads import _ddb_pk_from_group
from lovv_agent_v2.agents.city_select.scoring.ranking import (
    _candidate_attr,
    _city_name_from_group,
)
from lovv_agent_v2.tools.city_select_contracts import CitySelectContext
from lovv_agent_v2.models.schemas import SelectedCity


def _selected_city(
    city_id: str,
    scored_places: Sequence[PlaceScoreResult],
    *,
    context: CitySelectContext,
    status: str,
    selected_rank_index: int,
) -> SelectedCity:
    """Build the selected city summary for Planner input."""

    reason_codes = (
        ["anchored_city"]
        if context.candidate_input.destination_id
        else [f"city_score_rank_{selected_rank_index + 1}"]
    )
    del status
    province = _candidate_attr(scored_places[0].place, "province") or _candidate_attr(
        scored_places[0].place,
        "location",
    )
    return SelectedCity(
        city_id=_candidate_attr(scored_places[0].place, "city_id") or city_id,
        city_name_ko=_city_name_from_group(scored_places) or city_id,
        country=context.candidate_input.country,
        selection_reason_code=tuple(reason_codes),
        ddb_pk=_ddb_pk_from_group(city_id, scored_places),
        province=province,
    )
