from __future__ import annotations

from lovv_agent_v2.agents.city_select.scoring.service import CANDIDATE_SUFFICIENCY_THRESHOLD
from lovv_agent_v2.models.city_identity import load_default_city_identity_map


def test_anchor_destination_uses_city_id_map_before_legacy_pk_fallback() -> None:
    identity = load_default_city_identity_map().get("KR-47-130")

    assert identity is not None
    assert identity.ddb_pk == "CITY#GYEONGJU"


def test_trip_candidate_budget_matches_current_scoring_selection_shape() -> None:
    assert CANDIDATE_SUFFICIENCY_THRESHOLD == 5
