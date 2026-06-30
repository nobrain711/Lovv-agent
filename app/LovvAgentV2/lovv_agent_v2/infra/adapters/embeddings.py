"""Embedding adapter boundary for Bedrock-backed query vectors.

The adapter accepts an injected Bedrock Runtime client and never constructs AWS
clients by itself. This keeps unit tests local while allowing the Task 10
harness to generate live query embeddings when runtime config is present.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

ADAPTER_NAME = "EmbeddingAdapter"

RESPONSIBILITY = "Generate query vectors through an injected embedding runtime."

DEFAULT_EMBEDDING_DIMENSIONS = 1024
DEFAULT_NORMALIZE_EMBEDDING = True


# 호출자가 provider 응답 형태 문제와 graph schema 오류를 구분할 수 있도록
# embedding 실패는 adapter 전용 예외로 유지한다.
class EmbeddingAdapterError(RuntimeError):
    """Raised when an embedding response cannot be parsed safely."""


class BedrockEmbeddingClient(Protocol):
    """Runtime client shape required for Bedrock embedding generation."""

    def invoke_model(self, **request: Any) -> Any:
        """Invoke a Bedrock model and return the provider response."""


@dataclass(frozen=True, slots=True)
class BedrockEmbeddingAdapter:
    """Generate normalized query embeddings through Bedrock Runtime."""

    client: BedrockEmbeddingClient
    model_id: str
    dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS
    normalize: bool = DEFAULT_NORMALIZE_EMBEDDING

    def embed_query(self, query_text: str) -> tuple[float, ...]:
        """Return one query embedding vector for DestinationSearchTool."""

        text = _required_text(query_text, "query_text")
        model_id = _required_text(self.model_id, "model_id")
        dimensions = _positive_int(self.dimensions, "dimensions")
        # Titan 계열 Bedrock embedding 요청은 query text와 vector 형태를
        # JSON body로 전달한다.
        payload = {
            "inputText": text,
            "dimensions": dimensions,
            "normalize": bool(self.normalize),
        }
        response = self.client.invoke_model(
            modelId=model_id,
            body=json.dumps(payload).encode("utf-8"),
        )
        embedding = _extract_embedding(response)
        if len(embedding) != dimensions:
            raise EmbeddingAdapterError(
                f"embedding dimension mismatch: expected {dimensions}, got {len(embedding)}",
            )
        return embedding


def _extract_embedding(response: Any) -> tuple[float, ...]:
    """Extract a numeric embedding vector from a Bedrock Runtime response."""

    if not isinstance(response, dict):
        raise EmbeddingAdapterError("embedding response must be a mapping")
    body = response.get("body")
    if hasattr(body, "read"):
        body = body.read()
    if isinstance(body, bytes):
        body = body.decode("utf-8")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise EmbeddingAdapterError("embedding response body is not valid JSON") from exc
    if not isinstance(body, dict):
        raise EmbeddingAdapterError("embedding response body must be a mapping")
    embedding = body.get("embedding")
    if not isinstance(embedding, Sequence) or isinstance(embedding, (str, bytes)):
        raise EmbeddingAdapterError("embedding response must contain an embedding list")
    values: list[float] = []
    for value in embedding:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise EmbeddingAdapterError("embedding values must be numeric")
        values.append(float(value))
    return tuple(values)


def _required_text(value: str, field_name: str) -> str:
    """Validate a non-empty text argument."""

    if not isinstance(value, str):
        raise EmbeddingAdapterError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise EmbeddingAdapterError(f"{field_name} must be a non-empty string")
    return normalized


def _positive_int(value: int, field_name: str) -> int:
    """Validate a positive integer setting."""

    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EmbeddingAdapterError(f"{field_name} must be a positive integer")
    return value


__all__ = [
    "ADAPTER_NAME",
    "DEFAULT_EMBEDDING_DIMENSIONS",
    "DEFAULT_NORMALIZE_EMBEDDING",
    "RESPONSIBILITY",
    "BedrockEmbeddingAdapter",
    "BedrockEmbeddingClient",
    "EmbeddingAdapterError",
]
