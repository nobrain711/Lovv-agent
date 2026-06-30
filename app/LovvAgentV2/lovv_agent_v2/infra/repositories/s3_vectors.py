"""S3 Vector repository boundary.

The repository is intentionally thin in Task 4.1: it accepts an injected client
and forwards already-built query payloads. Filter construction and candidate
normalization belong to later DestinationSearchTool subtasks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from lovv_agent_v2.infra.config import S3VectorSettings
from lovv_agent_v2.models.schemas import SchemaValidationError
from lovv_agent_v2.common.telemetry import sanitize_text

REPOSITORY_NAME = "S3VectorRepository"

RESPONSIBILITY = "Search vector candidates through an injected S3 Vector client."
_TRACER = trace.get_tracer("lovv_agent_v2.infra.repositories.s3_vectors")


class S3VectorClient(Protocol):
    """Runtime client shape required by :class:`S3VectorRepository`."""

    def query_vectors(self, **request: Any) -> Mapping[str, Any]:
        """Run an S3 Vector query and return the raw provider response."""


@dataclass(frozen=True, slots=True)
class S3VectorRepository:
    """Pass-through repository for injected S3 Vector clients."""

    client: S3VectorClient
    settings: S3VectorSettings

    def query_vectors(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """Execute a vector query with configured bucket and index names."""

        if not isinstance(request, Mapping):
            raise SchemaValidationError("s3 vector request must be a mapping")
        payload = dict(request)
        # 테스트가 request에서 resource 이름을 override할 수 있게 하되,
        # 일반 harness 실행에는 설정된 런타임 resource를 기본으로 넣는다.
        payload.setdefault("vectorBucketName", self.settings.bucket_name)
        payload.setdefault("indexName", self.settings.index_name)
        with _TRACER.start_as_current_span("s3vectors.QueryVectors") as span:
            span.set_attribute("aws.service", "s3vectors")
            span.set_attribute("s3vectors.bucket", self.settings.bucket_name)
            span.set_attribute("s3vectors.index", self.settings.index_name)
            try:
                response = self.client.query_vectors(**payload)
                if not isinstance(response, Mapping):
                    raise SchemaValidationError("s3 vector response must be a mapping")
                _set_vector_summary_attributes(span, response)
                return dict(response)
            except Exception as exc:  # noqa: BLE001 - provider span records and re-raises.
                span.record_exception(exc)
                span.set_status(
                    Status(StatusCode.ERROR, sanitize_text(str(exc) or type(exc).__name__)),
                )
                raise


def extract_vector_records(response: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    """Extract raw vector records from common S3 Vector response shapes."""

    if not isinstance(response, Mapping):
        raise SchemaValidationError("s3 vector response must be a mapping")
    for field_name in ("vectors", "matches", "results"):
        # AWS와 test double은 서로 다른 collection key를 노출할 수 있다.
        records = response.get(field_name)
        if records is None:
            continue
        if not isinstance(records, (list, tuple)):
            raise SchemaValidationError(f"s3 vector response.{field_name} must be a list")
        return tuple(_copy_record(record, field_name) for record in records)
    return ()


def _copy_record(record: Any, field_name: str) -> dict[str, Any]:
    """Validate and copy one raw vector record."""

    if not isinstance(record, Mapping):
        raise SchemaValidationError(
            f"s3 vector response.{field_name} item must be a mapping",
        )
    return dict(record)


def _set_vector_summary_attributes(span, response: Mapping[str, Any]) -> None:
    records = extract_vector_records(response)
    span.set_attribute("s3vectors.result_count", len(records))
    distances = tuple(
        float(record["distance"])
        for record in records
        if isinstance(record.get("distance"), (int, float))
        and not isinstance(record.get("distance"), bool)
    )
    if distances:
        span.set_attribute("s3vectors.top_distance", min(distances))
        span.set_attribute("s3vectors.bottom_distance", max(distances))
    city_ids = sorted(
        {
            city_id
            for record in records
            for city_id in (_metadata_text(record, "city_id"),)
            if city_id is not None
        },
    )
    if city_ids:
        span.set_attribute("s3vectors.city_ids", city_ids)
    theme_tags = _theme_tags_sample(records)
    if theme_tags:
        span.set_attribute("s3vectors.theme_tags_sample", list(theme_tags))


def _metadata_text(record: Mapping[str, Any], field_name: str) -> str | None:
    metadata = record.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get(field_name)
    return value if isinstance(value, str) and value.strip() else None


def _theme_tags_sample(records: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    tags: list[str] = []
    for record in records:
        metadata = record.get("metadata")
        if not isinstance(metadata, Mapping):
            continue
        raw_tags = metadata.get("theme_tags")
        if not isinstance(raw_tags, (list, tuple)):
            continue
        for tag in raw_tags:
            if isinstance(tag, str) and tag not in tags:
                tags.append(tag)
            if len(tags) >= 5:
                return tuple(tags)
    return tuple(tags)


__all__ = [
    "REPOSITORY_NAME",
    "RESPONSIBILITY",
    "S3VectorClient",
    "S3VectorRepository",
    "extract_vector_records",
]
