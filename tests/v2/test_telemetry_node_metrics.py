from __future__ import annotations

from lovv_agent_v2.common.telemetry_node_metrics import node_log_entry


def test_input_summary_separates_request_themes_from_active_themes() -> None:
    entry = node_log_entry(
        state={
            "request": {
                "request_id": "REQ-1",
                "themes": ("바다·해안",),
                "trip_type": "2d1n",
                "include_festivals": False,
            },
            "intent": {
                "city_select_input": {
                    "active_required_themes": (
                        "자연·트레킹",
                        "역사·전통",
                        "온천·휴양",
                    ),
                },
            },
        },
        node_name="city_select",
        request_id="REQ-1",
        duration_ms=1,
        status="ok",
        result=None,
        error_message=None,
        llm_metrics=(),
    )

    summary = entry["inputSummary"]
    assert summary["themes"] == ["바다·해안"]
    assert summary["requestThemes"] == ["바다·해안"]
    assert summary["activeRequiredThemes"] == ["자연·트레킹", "역사·전통", "온천·휴양"]
    assert summary["themeCount"] == 1
    assert summary["activeThemeCount"] == 3
