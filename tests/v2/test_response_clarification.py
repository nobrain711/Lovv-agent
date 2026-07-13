from __future__ import annotations

import unittest

from lovv_agent_v2.agents.response_packager.packager import (
    package_recommendation_response,
)
from lovv_agent_v2.models.clarification import (
    Clarification,
    ClarificationApply,
    ClarificationOption,
)
from lovv_agent_v2.models.clarification_texts import clarification_helper_text
from lovv_agent_v2.models.clarification_texts import clarification_label_text


def request_payload() -> dict[str, object]:
    return {
        "request_id": "REQ-1",
        "country": "KR",
        "travel_month": 10,
        "trip_type": "daytrip",
        "destination_id": None,
        "themes": ("festival_event",),
    }


class ResponseClarificationPackagingTest(unittest.TestCase):
    def test_completed_response_preserves_existing_shape_without_clarification(self) -> None:
        # Given: no planner output and no clarification block.
        response = package_recommendation_response(
            planner_output=None,
            request=request_payload(),
            selected_city=None,
            recommendation_id="REC-1",
            expires_at="2026-06-30T00:00:00Z",
        )

        # Then: legacy clients still see the existing response shape.
        self.assertEqual(
            set(response),
            {
                "recommendationId",
                "expiresAt",
                "destination",
                "itinerary",
                "explainability",
                "festivalDateVerifications",
                "links",
            },
        )
        self.assertEqual(response["itinerary"]["days"], [])

    def test_wait_user_response_adds_camel_case_clarification(self) -> None:
        # Given: a structured internal clarification.
        clarification = Clarification(
            reason_code="festival_none",
            prompt="10월에 확정된 축제 도시가 없습니다. 축제 조건 없이 계속할까요?",
            options=(
                ClarificationOption(
                    option_id="continue_without_festival",
                    label="축제 없이 계속",
                    helper_text="축제 조건을 제외하고 여행지를 다시 찾습니다.",
                    apply=ClarificationApply(
                        include_festivals=False,
                        destination_id=None,
                    ),
                    then="rerun_discovery",
                ),
            ),
            context={"travel_month": 10},
            failure_signals=("no_confirmed_festival_city",),
        )

        # When: packaging an END_WAIT_USER response.
        response = package_recommendation_response(
            planner_output=None,
            request=request_payload(),
            selected_city=None,
            recommendation_id="REC-WAIT",
            expires_at="2026-06-30T00:00:00Z",
            response_status="END_WAIT_USER",
            clarification=clarification,
        )

        # Then: the old notice and new block carry the same user prompt.
        self.assertEqual(
            response["explainability"]["userNotice"],
            clarification.prompt,
        )
        self.assertEqual(response["clarification"]["reasonCode"], "festival_none")
        self.assertEqual(
            response["clarification"]["options"][0]["optionId"],
            "continue_without_festival",
        )
        self.assertFalse(
            response["clarification"]["options"][0]["apply"]["includeFestivals"],
        )
        self.assertEqual(
            response["clarification"]["options"][0]["then"],
            "rerun_discovery",
        )
        self.assertEqual(
            response["clarification"]["options"][0]["helperText"],
            "축제 조건을 제외하고 여행지를 다시 찾습니다.",
        )

    def test_apply_exposes_theme_agnostic_festival_retry(self) -> None:
        # Given: a festival retry option that clears theme narrowing.
        option = ClarificationOption(
            option_id="search_any_festival_theme",
            label="테마 무관 축제 찾기",
            helper_text="선호 테마와 무관하게 확정 축제가 있는 도시를 찾습니다.",
            apply=ClarificationApply(
                include_festivals=True,
                active_required_themes=(),
                festival_theme_agnostic=True,
            ),
            then="rerun_discovery",
        )

        # Then: the public payload carries the explicit retry semantics.
        payload = option.to_public_dict()
        self.assertEqual(payload["apply"]["activeRequiredThemes"], [])
        self.assertTrue(payload["apply"]["festivalThemeAgnostic"])

    def test_helper_texts_are_loaded_from_editable_resource(self) -> None:
        self.assertEqual(
            clarification_helper_text(
                "festival_tentative",
                "accept_tentative_festival:FEST-1",
                "fallback",
            ),
            "확정되지 않은 축제 일정일 수 있음을 감수하고 해당 도시로 진행합니다.",
        )

    def test_labels_are_loaded_from_editable_resource(self) -> None:
        self.assertEqual(
            clarification_label_text(
                "festival_none",
                "continue_without_festival",
                "fallback",
            ),
            "축제 없이 계속",
        )


if __name__ == "__main__":
    unittest.main()
