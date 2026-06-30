"""DynamoDB repository for LovvUserProfile table (read-only during recommendation).

Profile Agent reads stored user preferences from a separate DynamoDB table.
This repository is intentionally read-only during recommendation execution.
Profile writes happen asynchronously after trip confirmation (separate handler).

Table schema:
  PK: ACTOR#{actorId}
  SK: PROFILE#v1
  Attributes: saved_trip_count (Number), saved_theme_counts (Map), ...
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lovv_agent_v2.models.profile import LovvUserProfile
from lovv_agent_v2.models.schemas import SchemaValidationError


@dataclass(frozen=True, slots=True)
class ProfileRepository:
    """Read-only adapter for LovvUserProfile DynamoDB table."""

    client: Any  # boto3 DynamoDB client
    table_name: str

    def get_profile(self, actor_id: str) -> LovvUserProfile | None:
        """Fetch a user profile by pseudonymized actor ID.

        Returns None if the profile does not exist (cold start user).
        Errors are swallowed — Profile is optional, graceful degradation.
        """

        if not actor_id or not isinstance(actor_id, str):
            return None

        pk = f"ACTOR#{actor_id}"
        sk = "PROFILE#v1"

        try:
            response = self.client.get_item(
                TableName=self.table_name,
                Key={
                    "PK": {"S": pk},
                    "SK": {"S": sk},
                },
                ConsistentRead=False,
            )
        except Exception:
            # DynamoDB errors should not crash the recommendation flow.
            return None

        item = response.get("Item")
        if item is None:
            return None

        return _parse_profile_item(item)


def _parse_profile_item(item: dict[str, Any]) -> LovvUserProfile | None:
    """Parse a DynamoDB item into a LovvUserProfile.

    Returns None if required fields are missing or malformed.
    """

    try:
        saved_trip_count = int(item.get("saved_trip_count", {}).get("N", "0"))

        raw_counts = item.get("saved_theme_counts", {}).get("M", {})
        saved_theme_counts: dict[str, int] = {}
        for theme_id, value_map in raw_counts.items():
            count_str = value_map.get("N", "0")
            saved_theme_counts[theme_id] = int(count_str)

        return LovvUserProfile(
            saved_trip_count=saved_trip_count,
            saved_theme_counts=saved_theme_counts,
        )
    except (ValueError, TypeError, AttributeError, SchemaValidationError):
        return None


__all__ = [
    "ProfileRepository",
]
