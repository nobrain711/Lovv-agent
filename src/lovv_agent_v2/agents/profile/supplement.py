from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Final, Protocol

from botocore.config import Config

from lovv_agent_v2.models.schemas import SchemaValidationError

PROFILE_SUPPLEMENT_SYSTEM_PROMPT: Final = (
    "You are Lovv Profile Agent. Read the normalized city_select_input JSON and "
    "produce a concise personalization supplement for downstream travel city "
    "selection. Return JSON only with keys: profile_summary, "
    "soft_preference_keywords, caution_flags."
)


class BedrockRuntimeClient(Protocol):
    def converse(
        self,
        *,
        modelId: str,
        system: Sequence[Mapping[str, str]],
        messages: Sequence[Mapping[str, Any]],
        inferenceConfig: Mapping[str, int | float],
    ) -> Mapping[str, Any]: ...


class ProfileSupplementGenerator(Protocol):
    def generate(self, city_select_input: Mapping[str, Any]) -> "ProfileSupplement": ...


@dataclass(frozen=True, slots=True)
class ProfileSupplement:
    profile_summary: str
    soft_preference_keywords: tuple[str, ...]
    caution_flags: tuple[str, ...]
    model_id: str

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        model_id: str,
    ) -> "ProfileSupplement":
        return cls(
            profile_summary=_required_text(payload, "profile_summary"),
            soft_preference_keywords=_string_tuple(
                payload.get("soft_preference_keywords", ()),
                "soft_preference_keywords",
            ),
            caution_flags=_string_tuple(payload.get("caution_flags", ()), "caution_flags"),
            model_id=model_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_summary": self.profile_summary,
            "soft_preference_keywords": self.soft_preference_keywords,
            "caution_flags": self.caution_flags,
            "model_id": self.model_id,
        }


@dataclass(frozen=True, slots=True)
class BedrockProfileSupplementGenerator:
    client: BedrockRuntimeClient
    model_id: str
    max_tokens: int = 512
    temperature: float = 0.0

    def generate(self, city_select_input: Mapping[str, Any]) -> ProfileSupplement:
        response = self.client.converse(
            modelId=self.model_id,
            system=[{"text": PROFILE_SUPPLEMENT_SYSTEM_PROMPT}],
            messages=[
                {
                    "role": "user",
                    "content": [{"text": json.dumps(city_select_input, ensure_ascii=False)}],
                },
            ],
            inferenceConfig={
                "maxTokens": self.max_tokens,
                "temperature": self.temperature,
            },
        )
        return ProfileSupplement.from_mapping(
            _json_payload(_bedrock_text(response)),
            model_id=self.model_id,
        )


def create_bedrock_profile_supplement_generator(
    *,
    model_id: str,
    region_name: str | None,
) -> BedrockProfileSupplementGenerator:
    import boto3

    client = boto3.client(
        "bedrock-runtime",
        region_name=region_name,
        config=Config(retries={"max_attempts": 5, "mode": "adaptive"}),
    )
    return BedrockProfileSupplementGenerator(client=client, model_id=model_id)


def _bedrock_text(response: Mapping[str, Any]) -> str:
    output = response.get("output")
    if not isinstance(output, Mapping):
        raise SchemaValidationError("bedrock response.output must be an object")
    message = output.get("message")
    if not isinstance(message, Mapping):
        raise SchemaValidationError("bedrock response.output.message must be an object")
    content = message.get("content")
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        raise SchemaValidationError("bedrock response content must be a sequence")
    for block in content:
        if isinstance(block, Mapping):
            text = block.get("text")
            if isinstance(text, str) and text.strip():
                return text
    raise SchemaValidationError("bedrock response content has no text")


def _json_payload(text: str) -> Mapping[str, Any]:
    try:
        value = json.loads(text)
    except JSONDecodeError as error:
        raise SchemaValidationError("bedrock profile supplement must be JSON") from error
    if not isinstance(value, Mapping):
        raise SchemaValidationError("bedrock profile supplement must be an object")
    return value


def _required_text(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{key} must be a non-empty string")
    return value.strip()


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise SchemaValidationError(f"{field_name} must be a string sequence")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise SchemaValidationError(f"{field_name} must contain strings")
        result.append(item.strip())
    return tuple(result)
