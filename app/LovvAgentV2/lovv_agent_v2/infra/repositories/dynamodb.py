"""DynamoDB repository boundary.

This layer stays mockable by accepting an injected client. It owns only request
shape construction for DynamoDB reads; business fallback decisions remain in
the caller-facing tools.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from lovv_agent_v2.infra.config import DynamoDbSettings
from lovv_agent_v2.models.schemas import SchemaValidationError
from lovv_agent_v2.common.telemetry import sanitize_text

REPOSITORY_NAME = "DynamoDbRepository"

RESPONSIBILITY = "Read normalized detail records through an injected client."
_TRACER = trace.get_tracer("lovv_agent_v2.infra.repositories.dynamodb")
FESTIVAL_MONTH_INDEX_NAME = "FestivalMonthIndex"

# Scan은 페이지당 최대 1MB만 스캔한 뒤 FilterExpression을 적용하므로, 매칭 항목이
# 첫 페이지 밖에 있으면 단건 Scan은 빈 결과를 준다. 전체 테이블을 잇는 페이지네이션
# 상한(무한 루프/과도한 스캔 방지)이다.
MAX_FESTIVAL_SCAN_PAGES = 50


class DynamoDbClient(Protocol):
    """Runtime client shape required by :class:`DynamoDbRepository`."""

    def get_item(self, **request: Any) -> Mapping[str, Any]:
        """Return one DynamoDB item for the provided key request."""

    def query(self, **request: Any) -> Mapping[str, Any]:
        """Return DynamoDB query results for the provided query request."""

    def scan(self, **request: Any) -> Mapping[str, Any]:
        """Return DynamoDB scan results for the provided scan request."""

    def batch_get_item(self, **request: Any) -> Mapping[str, Any]:
        """Return DynamoDB items for the provided batch key request."""


@dataclass(frozen=True, slots=True)
class DynamoDbRepository:
    """Pass-through repository for injected DynamoDB clients."""

    client: DynamoDbClient
    settings: DynamoDbSettings

    def get_item(
        self,
        key: Mapping[str, Any],
        *,
        consistent_read: bool = False,
    ) -> dict[str, Any]:
        """Read one item from the configured table by primary key."""

        if not isinstance(key, Mapping):
            raise SchemaValidationError("dynamodb key must be a mapping")
        request_key = dict(key)
        with _TRACER.start_as_current_span("dynamodb.GetItem") as span:
            span.set_attribute("aws.service", "dynamodb")
            span.set_attribute("dynamodb.table", self.settings.table_name)
            span.set_attribute("dynamodb.operation", "GetItem")
            _set_key_attributes(span, request_key)
            try:
                response = self.client.get_item(
                    TableName=self.settings.table_name,
                    Key=request_key,
                    ConsistentRead=consistent_read,
                )
                if not isinstance(response, Mapping):
                    raise SchemaValidationError("dynamodb get_item response must be a mapping")
                _set_get_item_summary_attributes(span, response)
                return dict(response)
            except Exception as exc:  # noqa: BLE001 - provider span records and re-raises.
                span.record_exception(exc)
                span.set_status(
                    Status(StatusCode.ERROR, sanitize_text(str(exc) or type(exc).__name__)),
                )
                raise

    def get_detail_item(
        self,
        *,
        pk: str,
        sk: str,
        consistent_read: bool = False,
    ) -> dict[str, Any]:
        """Read one detail item by the canonical `PK`/`SK` key pair."""

        return self.get_item(
            {
                "PK": {"S": _required_text(pk, "pk")},
                "SK": {"S": _required_text(sk, "sk")},
            },
            consistent_read=consistent_read,
        )

    def batch_get_detail_items(
        self,
        keys: Iterable[tuple[str, str]],
        *,
        consistent_read: bool = False,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Read detail items by canonical `PK`/`SK` pairs in one batch."""

        unique_keys = list(
            dict.fromkeys(
                (
                    _required_text(pk, "pk"),
                    _required_text(sk, "sk"),
                )
                for pk, sk in keys
            ),
        )
        result: dict[tuple[str, str], dict[str, Any]] = {}
        if not unique_keys:
            return result
        table = self.settings.table_name
        pending: dict[str, Any] = {
            table: {
                "Keys": [
                    {"PK": {"S": pk}, "SK": {"S": sk}}
                    for pk, sk in unique_keys
                ],
                "ConsistentRead": consistent_read,
            },
        }
        with _TRACER.start_as_current_span("dynamodb.BatchGetItem") as span:
            span.set_attribute("aws.service", "dynamodb")
            span.set_attribute("dynamodb.table", table)
            span.set_attribute("dynamodb.operation", "BatchGetItem")
            span.set_attribute("dynamodb.request_key_count", len(unique_keys))
            try:
                for _ in range(2):
                    response = self.client.batch_get_item(RequestItems=pending)
                    if not isinstance(response, Mapping):
                        raise SchemaValidationError(
                            "dynamodb batch_get_item response must be a mapping",
                        )
                    rows = response.get("Responses", {})
                    for item in rows.get(table, ()) if isinstance(rows, Mapping) else ():
                        if not isinstance(item, Mapping):
                            continue
                        pk = _attribute_text(item.get("PK"))
                        sk = _attribute_text(item.get("SK"))
                        if pk is not None and sk is not None:
                            result[(pk, sk)] = dict(item)
                    unprocessed = response.get("UnprocessedKeys") or {}
                    if not unprocessed:
                        break
                    pending = dict(unprocessed)
                span.set_attribute("dynamodb.resolved_count", len(result))
                return result
            except Exception as exc:  # noqa: BLE001 - provider span records and re-raises.
                span.record_exception(exc)
                span.set_status(
                    Status(StatusCode.ERROR, sanitize_text(str(exc) or type(exc).__name__)),
                )
                raise

    def batch_get_city_visitor_stats(
        self,
        *,
        city_ids: Iterable[str],
        travel_month: int,
        partition_key_by_city: Mapping[str, str] | None = None,
    ) -> dict[str, float | None]:
        """Fetch per-city monthly visitor totals in one BatchGetItem.

        Key: ``PK=CITY#{city}``, ``SK=STAT#2025{MM}``, attribute ``total_visitors``.
        통계가 없는 도시는 ``None``(중립 처리용). 방문객 데이터는 2025만 존재하므로
        travelYear와 무관하게 2025 계절 패턴을 혼잡도 proxy로 사용한다.
        BatchGetItem은 항목당 RCU로 과금되어 비용은 GetItem N회와 동일하고, 왕복만 1회다.
        """

        unique_ids = list(dict.fromkeys(city_ids))
        result: dict[str, float | None] = {cid: None for cid in unique_ids}
        if not unique_ids:
            return result
        sk = f"STAT#2025{_month(travel_month, 'travel_month'):02d}"
        pk_to_city: dict[str, str] = {}
        keys: list[dict[str, Any]] = []
        for cid in unique_ids:
            raw_pk = (
                partition_key_by_city.get(cid)
                if partition_key_by_city is not None
                else None
            )
            pk = raw_pk if raw_pk else _city_partition_key(cid)
            pk_to_city[pk] = cid
            keys.append({"PK": {"S": pk}, "SK": {"S": sk}})
        table = self.settings.table_name
        pending: dict[str, Any] = {table: {"Keys": keys}}
        with _TRACER.start_as_current_span("dynamodb.BatchGetItem") as span:
            span.set_attribute("aws.service", "dynamodb")
            span.set_attribute("dynamodb.table", table)
            span.set_attribute("dynamodb.operation", "BatchGetItem")
            span.set_attribute("dynamodb.request_key_count", len(keys))
            try:
                for _ in range(2):  # 초기 1회 + UnprocessedKeys 1회 재시도
                    response = self.client.batch_get_item(RequestItems=pending)
                    if not isinstance(response, Mapping):
                        raise SchemaValidationError(
                            "dynamodb batch_get_item response must be a mapping",
                        )
                    rows = response.get("Responses", {})
                    for item in rows.get(table, ()) if isinstance(rows, Mapping) else ():
                        pk_value = item.get("PK", {}).get("S")
                        # total_visitors는 statistics 맵 안에 중첩돼 있다(현 스키마):
                        # statistics.M.total_visitors.N. 구 스키마(최상위)도 폴백 지원.
                        stats_map = item.get("statistics", {}).get("M", {})
                        total = stats_map.get("total_visitors", {}).get("N") or item.get(
                            "total_visitors", {}
                        ).get("N")
                        cid = pk_to_city.get(pk_value)
                        if cid is not None and total is not None:
                            result[cid] = float(total)
                    unprocessed = response.get("UnprocessedKeys") or {}
                    if not unprocessed:
                        break
                    pending = dict(unprocessed)
                span.set_attribute(
                    "dynamodb.resolved_count",
                    sum(1 for value in result.values() if value is not None),
                )
                return result
            except Exception as exc:  # noqa: BLE001 - provider span records and re-raises.
                span.record_exception(exc)
                span.set_status(
                    Status(StatusCode.ERROR, sanitize_text(str(exc) or type(exc).__name__)),
                )
                raise

    def query_items(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Run a query against the configured table."""

        if not isinstance(request, Mapping):
            raise SchemaValidationError("dynamodb query request must be a mapping")
        payload = dict(request)
        payload.setdefault("TableName", self.settings.table_name)
        with _TRACER.start_as_current_span("dynamodb.Query") as span:
            span.set_attribute("aws.service", "dynamodb")
            span.set_attribute("dynamodb.table", self.settings.table_name)
            span.set_attribute("dynamodb.operation", "Query")
            try:
                response = self.client.query(**payload)
                if not isinstance(response, Mapping):
                    raise SchemaValidationError("dynamodb query response must be a mapping")
                items = response.get("Items")
                span.set_attribute(
                    "dynamodb.result_count",
                    len(items) if isinstance(items, list) else 0,
                )
                return dict(response)
            except Exception as exc:  # noqa: BLE001 - provider span records and re-raises.
                span.record_exception(exc)
                span.set_status(
                    Status(StatusCode.ERROR, sanitize_text(str(exc) or type(exc).__name__)),
                )
                raise

    def query_all_items(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Query across all result pages, merging returned items."""

        if not isinstance(request, Mapping):
            raise SchemaValidationError("dynamodb query request must be a mapping")
        items: list[Any] = []
        start_key: Any = None
        while True:
            page_request = dict(request)
            if start_key is not None:
                page_request["ExclusiveStartKey"] = start_key
            response = self.query_items(page_request)
            page_items = response.get("Items", ())
            if isinstance(page_items, (list, tuple)):
                items.extend(page_items)
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                break
        return {"Items": items}

    def scan_items(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Run a scan against the configured table."""

        if not isinstance(request, Mapping):
            raise SchemaValidationError("dynamodb scan request must be a mapping")
        payload = dict(request)
        payload.setdefault("TableName", self.settings.table_name)
        response = self.client.scan(**payload)
        if not isinstance(response, Mapping):
            raise SchemaValidationError("dynamodb scan response must be a mapping")
        return dict(response)

    def scan_all_items(
        self,
        request: Mapping[str, Any],
        *,
        max_pages: int = MAX_FESTIVAL_SCAN_PAGES,
    ) -> dict[str, Any]:
        """Scan across pages until the table is exhausted, merging matched items.

        DynamoDB Scan은 페이지당 최대 1MB를 스캔한 뒤 FilterExpression을 적용한다.
        매칭 항목이 첫 페이지 밖에 있으면 단건 Scan은 빈 결과를 줄 수 있으므로,
        ``LastEvaluatedKey``가 없을 때까지(또는 안전 상한까지) 페이지를 이어 스캔한다.
        """

        if not isinstance(request, Mapping):
            raise SchemaValidationError("dynamodb scan request must be a mapping")
        items: list[Any] = []
        start_key: Any = None
        pages = 0
        while True:
            page_request = dict(request)
            if start_key is not None:
                page_request["ExclusiveStartKey"] = start_key
            response = self.scan_items(page_request)
            page_items = response.get("Items", ())
            if isinstance(page_items, (list, tuple)):
                items.extend(page_items)
            start_key = response.get("LastEvaluatedKey")
            pages += 1
            if not start_key or pages >= max_pages:
                break
        return {"Items": items}

    def query_festival_candidates(
        self,
        *,
        country: str,
        travel_month: int,
        city_id: str | None = None,
        city_key: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        _required_text(country, "country")
        normalized_month = _month(travel_month, "travel_month")
        _optional_text(city_id, "city_id")
        _optional_city_key(city_key)
        if limit is not None:
            _positive_int(limit, "limit")

        request = {
            "IndexName": FESTIVAL_MONTH_INDEX_NAME,
            "KeyConditionExpression": (
                "#entity_type = :entity_type AND begins_with(#gsi_sk, :month_prefix)"
            ),
            "ExpressionAttributeNames": {
                "#entity_type": "entity_type",
                "#gsi_sk": "gsi_sk",
            },
            "ExpressionAttributeValues": {
                ":entity_type": {"S": "festival"},
                ":month_prefix": {"S": f"FESTIVAL#{normalized_month:02d}"},
            },
        }
        return self.query_all_items(request)

def _required_text(value: Any, field_name: str) -> str:
    """Validate a non-empty text value for repository requests."""

    if not isinstance(value, str):
        raise SchemaValidationError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise SchemaValidationError(f"{field_name} must be a non-empty string")
    return normalized


def _optional_text(value: Any, field_name: str) -> str | None:
    """Validate optional text and normalize blanks to ``None``."""

    if value is None:
        return None
    return _required_text(value, field_name)


def _optional_city_key(value: Any) -> str | None:
    if value is None:
        return None
    normalized = _required_text(value, "city_key")
    if normalized.startswith("CITY#"):
        return normalized
    return f"CITY#{normalized.upper()}"


def _city_partition_key(city_id: str) -> str:
    """Convert a canonical country-prefixed city id to its DynamoDB PK."""

    normalized = _required_text(city_id, "city_id")
    prefix, separator, suffix = normalized.partition("-")
    city_name = suffix if separator and len(prefix) == 2 and prefix.isupper() else normalized
    return f"CITY#{city_name}"


def _month(value: Any, field_name: str) -> int:
    """Validate a 1-12 month number."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be an integer")
    if value < 1 or value > 12:
        raise SchemaValidationError(f"{field_name} must be between 1 and 12")
    return value


def _positive_int(value: Any, field_name: str) -> int:
    """Validate a positive integer request option."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    if value <= 0:
        raise SchemaValidationError(f"{field_name} must be a positive integer")
    return value


def _set_key_attributes(span, key: Mapping[str, Any]) -> None:
    pk = _attribute_text(key.get("PK"))
    sk = _attribute_text(key.get("SK"))
    if pk is not None:
        span.set_attribute("dynamodb.pk", pk)
    if sk is not None:
        span.set_attribute("dynamodb.sk", sk)


def _set_get_item_summary_attributes(span, response: Mapping[str, Any]) -> None:
    item = response.get("Item")
    found = isinstance(item, Mapping)
    span.set_attribute("dynamodb.found", found)
    if not found:
        return
    overview = _attribute_text(item.get("overview"))
    span.set_attribute("dynamodb.content_length", len(overview or ""))


def _attribute_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return None
    for key in ("S", "N"):
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return None


__all__ = [
    "DynamoDbClient",
    "DynamoDbRepository",
    "REPOSITORY_NAME",
    "RESPONSIBILITY",
]
