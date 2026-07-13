from __future__ import annotations

from typing import Any

from lovv_agent_v2.agents.intent.prompt import (
    INTENT_PROMPT_OUTPUT_SCHEMA,
    INTENT_PROMPT_TEXT,
)
from lovv_agent_v2.agents.intent.modify_parser import parse_modify_query
from lovv_agent_v2.agents.intent.node import intent_node
from lovv_agent_v2.agents.intent.parser import parse_initial_query
from lovv_agent_v2.agents.intent.validator import validate_preference_sets
from lovv_agent_v2.core.runtime_state import invocation_runtime
from lovv_agent_v2.core.state import UnifiedAgentState
from lovv_agent_v2.models.schemas import SchemaValidationError


def test_parse_initial_query_extracts_preferred_theme_ids() -> None:
    result = parse_initial_query("바다랑 로컬 맛집 위주로 2박 3일 여행지를 추천해줘")

    assert result.preferred_theme_ids == ("sea_coast", "food_local")
    assert result.disliked_theme_ids == ()
    assert result.active_theme_labels == ("바다·해안", "미식·노포")


def test_parse_initial_query_extracts_disliked_theme_ids() -> None:
    result = parse_initial_query("전시는 좋지만 등산이나 트레킹 코스는 빼줘")

    assert result.preferred_theme_ids == ("art_sense",)
    assert result.disliked_theme_ids == ("nature_trekking",)


def test_parse_initial_query_does_not_treat_coastal_walk_as_nature() -> None:
    result = parse_initial_query("부산 바다와 해안 산책 중심으로 추천해줘")

    assert result.preferred_theme_ids == ("sea_coast",)


def test_parse_initial_query_extracts_preferred_and_disliked_regions() -> None:
    result = parse_initial_query(
        "속초 말고 안동이나 경주처럼 역사 있는 곳으로 추천해줘"
    )

    assert result.preferred_region_ids == ("KR-47-170", "KR-47-130")
    assert result.preferred_region_names == ("안동시", "경주시")
    assert result.disliked_region_ids == ("KR-51-210",)
    assert result.disliked_region_names == ("속초시",)
    assert result.preferred_theme_ids == ("history_tradition",)


def test_parse_initial_query_resolves_city_county_and_district_names() -> None:
    result = parse_initial_query("평창군이나 경주시 말고 대구 동구 쪽으로 추천해줘")

    assert result.preferred_region_ids == ("KR-27-DONG-DAEGU",)
    assert result.preferred_region_names == ("동구 (대구광역시)",)
    assert result.disliked_region_ids == ("KR-51-760", "KR-47-130")
    assert result.disliked_region_names == ("평창군", "경주시")
    assert result.preferred_region_spans == ("대구 동구",)
    assert result.disliked_region_spans == ("평창군", "경주시")


def test_parse_initial_query_keeps_ambiguous_district_unresolved() -> None:
    result = parse_initial_query("동구 쪽의 조용한 바다 여행지를 추천해줘")

    assert result.preferred_region_ids == ()
    assert result.preferred_region_names == ()
    assert result.preferred_region_spans == ("동구",)
    assert result.unresolved_region_spans == ("동구",)


def test_parse_initial_query_resolves_parenthesized_district_qualifier() -> None:
    result = parse_initial_query("동구 (대구광역시) 쪽으로 가고 싶어")

    assert result.preferred_region_ids == ("KR-27-DONG-DAEGU",)
    assert result.preferred_region_names == ("동구 (대구광역시)",)


def test_parse_initial_query_keeps_positive_segment_after_avoid_marker() -> None:
    result = parse_initial_query(
        "강원도는 피하고 경북에서 바다랑 로컬 맛집 위주로 가고 싶어. "
        "등산이나 트레킹은 빼줘."
    )

    assert result.preferred_theme_ids == ("sea_coast", "food_local")
    assert result.disliked_theme_ids == ("nature_trekking",)
    assert result.preferred_region_ids == ()
    assert result.disliked_region_ids == ()
    assert result.unresolved_region_spans == ("경북", "강원도")
    assert "강원" not in result.cleaned_raw_query
    assert "등산" not in result.cleaned_raw_query
    assert "트레킹" not in result.cleaned_raw_query


def test_validator_flags_theme_and_region_contradictions() -> None:
    result = validate_preference_sets(
        preferred_theme_ids=("sea_coast",),
        disliked_theme_ids=("sea_coast",),
        preferred_region_ids=("KR-51-210",),
        disliked_region_ids=("KR-51-210",),
    )

    assert result.needs_clarification is True
    assert result.contradiction_reasons == (
        "theme:sea_coast",
        "region:KR-51-210",
    )


def test_parse_initial_query_surfaces_clarification_route() -> None:
    result = parse_initial_query("속초는 싫은데 속초 바다 여행지를 추천해줘")

    assert result.preferred_region_ids == ("KR-51-210",)
    assert result.disliked_region_ids == ("KR-51-210",)
    assert result.needs_clarification is True
    assert result.clarifying_question is not None


def test_parse_initial_query_flags_theme_clarification_route() -> None:
    result = parse_initial_query("바다는 좋은데 바다는 빼줘")

    assert result.preferred_theme_ids == ("sea_coast",)
    assert result.disliked_theme_ids == ("sea_coast",)
    assert result.needs_clarification is True


def test_intent_node_projects_request_preferences_to_intent_payload() -> None:
    output = intent_node(
        {
            "request": {
                "country": "KR",
                "travel_month": 8,
                "travel_year": 2026,
                "trip_type": "couple",
                "include_festivals": True,
                "raw_query": "강원도 말고 경북 바다랑 미식 여행지 추천해줘",
            },
        },
    )

    intent = output["intent"]
    assert intent["preferred_theme_ids"] == ("sea_coast", "food_local")
    assert intent["disliked_theme_ids"] == ()
    assert intent["preferred_region_ids"] == ()
    assert intent["preferred_region_names"] == ()
    assert intent["disliked_region_ids"] == ()
    assert intent["disliked_region_names"] == ()
    assert intent["unresolved_region_spans"] == ("경북", "강원도")
    assert intent["city_select_input"]["active_required_themes"] == [
        "바다·해안",
        "미식·노포",
    ]
    assert intent["city_select_input"]["preferred_theme_ids"] == (
        "sea_coast",
        "food_local",
    )
    assert intent["city_select_input"]["unresolved_region_spans"] == (
        "경북",
        "강원도",
    )


def test_intent_node_reads_front_textfield_natural_language_query() -> None:
    output = intent_node(
        {
            "request": {
                "country": "KR",
                "travel_month": 10,
                "travel_year": 2026,
                "trip_type": "2d1n",
                "include_festivals": False,
                "naturalLanguageQuery": "속초 말고 안동 역사 여행을 추천해줘.",
                "softPreferenceQuery": "차분한 분위기.",
            },
        },
    )

    intent = output["intent"]
    city_input = intent["city_select_input"]
    assert city_input["cleaned_raw_query"] == "안동 역사 여행을 추천해줘"
    assert city_input["soft_preference_query"] == ""
    assert intent["preferred_region_ids"] == ("KR-47-170",)
    assert intent["disliked_region_ids"] == ("KR-51-210",)
    assert city_input["preferred_region_ids"] == ("KR-47-170",)
    assert city_input["disliked_region_ids"] == ("KR-51-210",)
    assert city_input["preferred_region_names"] == ("안동시",)
    assert city_input["disliked_region_names"] == ("속초시",)


def test_intent_node_uses_prompt_runtime_before_code_parser() -> None:
    runtime = RecordingIntentRuntime(
        {
            "cleaned_raw_query": "차 없이 걸어서 둘러보기 좋은 역사 유적 중심 여행을 하고 싶어.",
            "soft_preference_query": "조용하고 오래된 골목 분위기.",
            "unsupported_conditions": [],
            "congestion_pref": "quiet",
            "transport_pref": "walk",
            "preferred_theme_ids": ["history_tradition", "nature_trekking"],
            "disliked_theme_ids": [],
            "preferred_region_spans": [],
            "disliked_region_spans": [],
            "needs_clarification": False,
            "clarifying_question": "",
            "contradiction_reasons": [],
        },
    )

    state: UnifiedAgentState = {
        "request": {
            "country": "KR",
            "travel_month": 10,
            "travel_year": 2026,
            "trip_type": "2d1n",
            "themes": ["역사·전통", "자연·트레킹"],
            "include_festivals": False,
            "raw_query": "바다 여행지를 추천해줘",
            "user_location": {"latitude": 37.5665, "longitude": 126.978},
            "congestion_pref": "neutral",
            "transport_pref": "unknown",
        },
    }
    with invocation_runtime(
        {
            "intent_prompt_runtime": {
                "runtime": runtime,
                "schema_retry_limit": 0,
            },
        },
    ):
        output = intent_node(state)

    intent = output["intent"]
    assert intent["city_select_input"]["active_required_themes"] == [
        "역사·전통",
        "자연·트레킹",
    ]
    assert intent["city_select_input"]["congestion_pref"] == "neutral"
    assert intent["city_select_input"]["transport_pref"] == "walk"
    assert intent["city_select_input"]["destination_id"] is None
    assert intent["city_select_input"]["preferred_theme_ids"] == (
        "history_tradition",
        "nature_trekking",
    )
    assert intent["city_select_input"]["disliked_theme_ids"] == ()
    assert intent["preferred_theme_ids"] == ("history_tradition", "nature_trekking")
    assert intent["clarifying_question"] is None
    assert intent["intent_extraction_mode"] == "prompt_structured_output"
    assert runtime.requests[0]["outputConfig"]["textFormat"]["type"] == "json_schema"
    assert "Lovv V2 Intent Agent" in runtime.requests[0]["system"][0]["text"]


def test_prompt_intent_projects_parsed_themes_when_request_themes_are_empty() -> None:
    runtime = RecordingIntentRuntime(
        {
            "cleaned_raw_query": "온천에서 푹 쉬는 힐링 휴양 여행을 원해",
            "soft_preference_query": "편안하게 쉬기 좋은 온천 휴양지.",
            "unsupported_conditions": [],
            "congestion_pref": "neutral",
            "transport_pref": "unknown",
            "preferred_theme_ids": ["healing_rest"],
            "disliked_theme_ids": [],
            "preferred_region_spans": [],
            "disliked_region_spans": [],
            "needs_clarification": False,
            "clarifying_question": "",
            "contradiction_reasons": [],
        },
    )

    state: UnifiedAgentState = {
        "request": {
            "country": "KR",
            "travel_month": 12,
            "travel_year": 2026,
            "trip_type": "2d1n",
            "themes": [],
            "include_festivals": False,
            "naturalLanguageQuery": "온천에서 푹 쉬는 힐링 휴양 여행을 원해",
        },
    }
    with invocation_runtime(
        {
            "intent_prompt_runtime": {
                "runtime": runtime,
                "schema_retry_limit": 0,
            },
        },
    ):
        output = intent_node(state)

    assert output["intent"]["city_select_input"]["active_required_themes"] == [
        "온천·휴양",
    ]


def test_intent_node_keeps_request_owned_fields_out_of_prompt_output() -> None:
    runtime = RecordingIntentRuntime(
        {
            "country": "JP",
            "travel_month": 1,
            "travel_year": 2030,
            "trip_type": "llm-trip",
            "active_required_themes": ["자연·트레킹"],
            "include_festivals": False,
            "cleaned_raw_query": "차 없이 걷기 좋은 일정",
            "soft_preference_query": "조용한 골목 분위기",
            "unsupported_conditions": ["실시간 혼잡도 보장"],
            "destination_id": "LLM-CITY",
            "city_key": "CITY#LLM",
            "ddb_pk": "CITY#LLM",
            "user_location": {"latitude": 0, "longitude": 0},
            "execution_mode": "city_discovery",
            "congestion_pref": "quiet",
            "transport_pref": "walk",
            "preferred_theme_ids": ["history_tradition"],
            "disliked_theme_ids": [],
            "preferred_region_spans": ["안동"],
            "disliked_region_spans": [],
            "needs_clarification": False,
            "clarifying_question": "",
            "contradiction_reasons": [],
        },
    )

    state: UnifiedAgentState = {
        "request": {
            "country": "KR",
            "travel_month": 10,
            "travel_year": 2026,
            "trip_type": "2d1n",
            "themes": ["역사·전통"],
            "include_festivals": True,
            "destination_id": "KR-Andong",
            "city_key": "CITY#ANDONG",
            "ddb_pk": "CITY#ANDONG",
            "user_location": {"latitude": 37.5665, "longitude": 126.978},
            "execution_mode": "anchored_place_search",
            "raw_query": "안동 역사 여행을 차 없이 추천해줘",
        },
    }
    with invocation_runtime(
        {
            "intent_prompt_runtime": {
                "runtime": runtime,
                "schema_retry_limit": 0,
            },
        },
    ):
        output = intent_node(state)

    city_input = output["intent"]["city_select_input"]
    assert city_input["country"] == "KR"
    assert city_input["travel_month"] == 10
    assert city_input["travel_year"] == 2026
    assert city_input["trip_type"] == "2d1n"
    assert city_input["active_required_themes"] == ["역사·전통"]
    assert city_input["include_festivals"] is True
    assert city_input["destination_id"] == "KR-Andong"
    assert city_input["city_key"] == "CITY#ANDONG"
    assert city_input["ddb_pk"] == "CITY#ANDONG"
    assert city_input["user_location"] == {"latitude": 37.5665, "longitude": 126.978}
    assert city_input["execution_mode"] == "anchored_place_search"
    assert city_input["cleaned_raw_query"] == "차 없이 걷기 좋은 일정"
    assert city_input["soft_preference_query"] == "조용한 골목 분위기"
    assert city_input["unsupported_conditions"] == ("실시간 혼잡도 보장",)
    assert city_input["congestion_pref"] == "neutral"
    assert city_input["transport_pref"] == "walk"
    assert output["intent"]["preferred_region_ids"] == ("KR-47-170",)


def test_prompt_intent_removes_disliked_region_from_cleaned_query() -> None:
    runtime = RecordingIntentRuntime(
        {
            "cleaned_raw_query": "속초 말고 안동이나 경주처럼 역사 있는 곳으로 추천해줘.",
            "soft_preference_query": "",
            "unsupported_conditions": [],
            "congestion_pref": "neutral",
            "transport_pref": "unknown",
            "preferred_theme_ids": ["history_tradition"],
            "disliked_theme_ids": [],
            "preferred_region_spans": ["안동", "경주"],
            "disliked_region_spans": ["속초"],
            "needs_clarification": False,
            "clarifying_question": "",
            "contradiction_reasons": [],
        },
    )

    with invocation_runtime(
        {
            "intent_prompt_runtime": {
                "runtime": runtime,
                "schema_retry_limit": 0,
            },
        },
    ):
        output = intent_node(
            {
                "request": {
                    "country": "KR",
                    "travel_month": 9,
                    "travel_year": 2026,
                    "trip_type": "daytrip",
                    "themes": ["역사·전통"],
                    "include_festivals": False,
                    "naturalLanguageQuery": "속초 말고 안동이나 경주처럼 역사 있는 곳으로 추천해줘.",
                },
            },
        )

    cleaned = output["intent"]["city_select_input"]["cleaned_raw_query"]
    assert "속초" not in cleaned
    assert "안동" in cleaned
    assert "경주" in cleaned


def test_prompt_intent_reconciles_preference_contradictions() -> None:
    runtime = RecordingIntentRuntime(
        {
            "cleaned_raw_query": "속초는 싫은데 속초 바다 여행지를 추천해줘.",
            "soft_preference_query": "",
            "unsupported_conditions": [],
            "congestion_pref": "neutral",
            "transport_pref": "unknown",
            "preferred_theme_ids": ["sea_coast"],
            "disliked_theme_ids": [],
            "preferred_region_spans": ["속초"],
            "disliked_region_spans": ["속초"],
            "needs_clarification": False,
            "clarifying_question": "",
            "contradiction_reasons": [],
        },
    )

    with invocation_runtime(
        {
            "intent_prompt_runtime": {
                "runtime": runtime,
                "schema_retry_limit": 0,
            },
        },
    ):
        output = intent_node(
            {
                "request": {
                    "country": "KR",
                    "travel_month": 8,
                    "travel_year": 2026,
                    "trip_type": "daytrip",
                    "themes": ["바다·해안"],
                    "include_festivals": False,
                    "naturalLanguageQuery": "속초는 싫은데 속초 바다 여행지를 추천해줘.",
                },
            },
        )

    intent = output["intent"]
    assert intent["needs_clarification"] is True
    assert intent["contradiction_reasons"] == ("region:KR-51-210",)
    assert intent["clarifying_question"] is not None
    assert intent["clarification"]["reason_code"] == "contradiction"
    assert intent["clarification"]["options"][0]["then"] == "abort"


def test_intent_node_clarifies_unsupported_country_request() -> None:
    output = intent_node(
        {
            "request": {
                "entryType": "create",
                "country": "JP",
                "travelMonth": 8,
                "travelYear": 2026,
                "tripType": "daytrip",
                "themes": ["바다·해안"],
                "includeFestivals": False,
                "naturalLanguageQuery": "도쿄 바다 여행지를 추천해줘.",
            },
        },
    )

    intent = output["intent"]
    assert intent["needs_clarification"] is True
    assert intent["clarification"]["reason_code"] == "unsupported_region"
    assert intent["clarification"]["options"][0]["option_id"] == "revise_conditions"
    assert intent["clarification"]["options"][0]["then"] == "abort"
    assert output["response"] == {}


def test_intent_prompt_defines_transport_and_congestion_enum_rules() -> None:
    assert "transport_pref=walk" in INTENT_PROMPT_TEXT
    assert "transport_pref=car" in INTENT_PROMPT_TEXT
    assert "transport_pref=unknown" in INTENT_PROMPT_TEXT
    assert "congestion_pref=quiet" in INTENT_PROMPT_TEXT
    assert "congestion_pref=vibrant" in INTENT_PROMPT_TEXT


def test_intent_prompt_defines_soft_preference_hyde_examples() -> None:
    assert "HyDE-style place-description sentence" in INTENT_PROMPT_TEXT
    assert "사람이 드물고 조용하며 한적한" in INTENT_PROMPT_TEXT
    assert "still appear naturally in" in INTENT_PROMPT_TEXT
    assert "옛 정취가 흐르는" in INTENT_PROMPT_TEXT
    assert "no explicit mood/style phrase" in INTENT_PROMPT_TEXT


def test_intent_prompt_defines_preference_id_rules_and_enums() -> None:
    assert "preferred_theme_ids" in INTENT_PROMPT_TEXT
    assert "disliked_theme_ids" in INTENT_PROMPT_TEXT
    assert "preferred_region_spans" in INTENT_PROMPT_TEXT
    assert "disliked_region_spans" in INTENT_PROMPT_TEXT
    assert "Never invent KR-* ids" in INTENT_PROMPT_TEXT
    assert "동구 (대구광역시)" in INTENT_PROMPT_TEXT
    assert "평창군" in INTENT_PROMPT_TEXT
    assert "A 말고 B" in INTENT_PROMPT_TEXT
    assert "A는 피하고 B에서 C 위주" in INTENT_PROMPT_TEXT
    properties = INTENT_PROMPT_OUTPUT_SCHEMA["properties"]
    assert "sea_coast" in properties["preferred_theme_ids"]["items"]["enum"]
    assert "art_sense" in properties["disliked_theme_ids"]["items"]["enum"]
    assert "enum" not in properties["preferred_region_spans"]["items"]
    assert "enum" not in properties["disliked_region_spans"]["items"]
    for field_name in (
        "country",
        "travel_month",
        "travel_year",
        "trip_type",
        "include_festivals",
        "destination_id",
        "user_location",
        "city_key",
        "ddb_pk",
        "execution_mode",
        "active_required_themes",
    ):
        assert field_name not in properties
        assert field_name not in INTENT_PROMPT_OUTPUT_SCHEMA["required"]


def test_intent_node_reparses_fresh_create_request_over_stale_city_input() -> None:
    output = intent_node(
        {
            "intent": {
                "clarification": {
                    "reason_code": "contradiction",
                    "prompt": "old prompt",
                    "options": [],
                },
                "city_select_input": {
                    "country": "KR",
                    "travel_month": 9,
                    "travel_year": 2026,
                    "trip_type": "solo",
                    "active_required_themes": ["역사·전통"],
                    "include_festivals": False,
                    "cleaned_raw_query": "안동 역사 여행",
                    "soft_preference_query": "",
                    "unsupported_conditions": [],
                },
            },
            "request": {
                "entryType": "create",
                "country": "KR",
                "travel_month": 9,
                "travel_year": 2026,
                "trip_type": "solo",
                "include_festivals": False,
                "raw_query": "강릉 바다 여행지를 추천해줘",
            },
        },
    )

    intent = output["intent"]
    assert intent["city_select_input"]["active_required_themes"] == ["바다·해안"]
    assert intent["city_select_input"]["cleaned_raw_query"] == "강릉 바다 여행지를 추천해줘"
    assert "clarification" not in intent
    assert output["response"] == {}
    assert output["planner"] == {}
    assert output["city_select"] == {}


def test_intent_node_rejects_intent_output_alias_without_front_request() -> None:
    try:
        intent_node(
            {
                "intent": {
                    "intent_output": {
                        "country": "KR",
                        "travel_month": 9,
                        "travel_year": 2026,
                        "trip_type": "solo",
                        "active_required_themes": ["역사·전통"],
                        "include_festivals": False,
                        "cleaned_raw_query": "안동 역사 여행",
                        "soft_preference_query": "",
                        "unsupported_conditions": [],
                    },
                    "preferred_theme_ids": ("history_tradition",),
                },
            },
        )
    except SchemaValidationError as exc:
        assert "intent.city_select_input or state.request is required" in str(exc)
    else:
        raise AssertionError("intent_output alias must be rejected")


def test_parse_modify_query_extracts_turn_updates() -> None:
    result = parse_modify_query("2일차 오후는 바다 말고 숲길이랑 온천 중심으로 바꿔줘")

    assert result.preferred_theme_ids == ("nature_trekking", "healing_rest")
    assert result.disliked_theme_ids == ("sea_coast",)


def test_parse_modify_query_extracts_region_updates() -> None:
    result = parse_modify_query("속초는 빼고 안동 쪽으로 바꿔줘")

    assert result.preferred_region_ids == ("KR-47-170",)
    assert result.preferred_region_names == ("안동시",)
    assert result.disliked_region_ids == ("KR-51-210",)
    assert result.disliked_region_names == ("속초시",)


class RecordingIntentRuntime:
    def __init__(self, structured_output: dict[str, Any]) -> None:
        self.structured_output = structured_output
        self.requests: list[dict[str, Any]] = []

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.requests.append(request)
        return {"structured_output": self.structured_output}
