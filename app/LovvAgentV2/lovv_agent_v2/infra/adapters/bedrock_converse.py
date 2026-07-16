"""Bedrock Converse structured-output adapter boundary.

The adapter is intentionally provider-SDK free. Runtime callers inject a
Converse-compatible callable so unit tests, local harnesses, and future
AgentCore entrypoints can share the same schema/retry behavior without
initializing AWS clients at import time.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from lovv_agent_v2.common.telemetry import context_window_for_model, record_llm_usage, sanitize_text
from lovv_agent_v2.common.telemetry_metrics import record_tool_call

ADAPTER_NAME = "BedrockConverseAdapter"

RESPONSIBILITY = "Provide schema-oriented LLM calls through an injected runtime."

STRUCTURED_OUTPUT_TEXT_FORMAT = "json_schema"
_TRACER = trace.get_tracer("lovv_agent_v2.infra.adapters.bedrock_converse")

# RuntimeInvoker는 단순 callable로 두어 테스트가 AWS SDK 응답 클래스 없이
# 간단한 fake를 주입할 수 있게 한다.
RuntimeInvoker = Callable[[Mapping[str, Any]], Mapping[str, Any] | str]
OutputValidator = Callable[[Mapping[str, Any]], Any]


class StructuredOutputError(RuntimeError):
    """Raised when a structured LLM response cannot be extracted or validated."""


@dataclass(frozen=True, slots=True)
class StructuredOutputResult:
    """Result from a bounded structured-output invocation."""

    ok: bool
    value: Any | None = None
    attempts: int = 0
    validation_errors: tuple[str, ...] = ()
    raw_response: Mapping[str, Any] | str | None = None


class BedrockConverseClient(Protocol):
    """Runtime client shape for Bedrock Converse-compatible calls."""

    def converse(self, **request: Any) -> Mapping[str, Any]:
        """Invoke Bedrock Converse and return a provider response."""


@dataclass(frozen=True, slots=True)
class BedrockConverseRuntime:
    """Callable wrapper that injects the configured Bedrock model id."""

    client: BedrockConverseClient
    model_id: str

    def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Invoke the configured Bedrock Converse model."""

        if not isinstance(request, Mapping):
            raise StructuredOutputError("converse request must be a mapping")
        model_id = _required_text(self.model_id, "model_id")
        payload = dict(request)
        # 테스트에서 명시한 modelId는 존중하고, live 호출은 설정값을 기본으로 쓴다.
        payload.setdefault("modelId", model_id)
        started_at = time.perf_counter()
        with _TRACER.start_as_current_span("BedrockConverse") as span:
            span.set_attribute("llm.model_id", model_id)
            span.set_attribute("llm.context_window", context_window_for_model(model_id))
            try:
                response = self.client.converse(**payload)
                if not isinstance(response, Mapping):
                    raise StructuredOutputError("converse response must be a mapping")
                usage = response.get("usage")
                if isinstance(usage, Mapping):
                    record_llm_usage(model_id, usage)
                    span.set_attribute("llm.usage.input_tokens", _usage_int(usage, "inputTokens"))
                    span.set_attribute("llm.usage.output_tokens", _usage_int(usage, "outputTokens"))
                    span.set_attribute("llm.usage.total_tokens", _usage_int(usage, "totalTokens"))
                return dict(response)
            except Exception as exc:  # noqa: BLE001 - provider span records and re-raises.
                span.record_exception(exc)
                span.set_status(
                    Status(StatusCode.ERROR, sanitize_text(str(exc) or type(exc).__name__)),
                )
                raise
            finally:
                record_tool_call("bedrock", "Converse", _duration_ms(started_at))


def create_bedrock_converse_runtime(
    *,
    client: BedrockConverseClient,
    model_id: str,
) -> RuntimeInvoker:
    """Build a structured-output runtime over Bedrock Converse."""

    return BedrockConverseRuntime(client=client, model_id=model_id)


def build_json_schema_text_format(
    *,
    name: str,
    schema: Mapping[str, Any],
    description: str,
) -> dict[str, Any]:
    """Build a Bedrock Converse ``outputConfig.textFormat`` schema block."""

    return {
        "type": STRUCTURED_OUTPUT_TEXT_FORMAT,
        "structure": {
            "jsonSchema": {
                "name": _required_text(name, "name"),
                "description": _required_text(description, "description"),
                "schema": json.dumps(dict(schema), ensure_ascii=False),
            },
        },
    }


def build_structured_converse_request(
    *,
    messages: Sequence[Mapping[str, Any]],
    schema_name: str,
    schema: Mapping[str, Any],
    schema_description: str,
    system: Sequence[Mapping[str, Any]] | None = None,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Build a provider-neutral Converse request with JSON Schema output.

    ``reasoning_effort`` (gpt-oss: ``low`` | ``medium`` | ``high``) is forwarded
    via Converse ``additionalModelRequestFields`` to cap the model's reasoning
    trace. gpt-oss cannot disable reasoning entirely; ``low`` is the floor.
    """

    if isinstance(messages, (str, bytes)) or not isinstance(messages, Sequence):
        raise StructuredOutputError("messages must be a sequence of message mappings")
    request: dict[str, Any] = {
        "messages": [dict(message) for message in messages],
        "outputConfig": {
            "textFormat": build_json_schema_text_format(
                name=schema_name,
                schema=schema,
                description=schema_description,
            ),
        },
    }
    if system is not None:
        request["system"] = [dict(item) for item in system]
    if reasoning_effort is not None:
        request["additionalModelRequestFields"] = {"reasoning_effort": reasoning_effort}
    return request


def invoke_structured_output(
    *,
    runtime: RuntimeInvoker,
    request: Mapping[str, Any],
    validator: OutputValidator,
    retry_limit: int,
) -> StructuredOutputResult:
    """Invoke an injected runtime and validate structured output with retries."""

    if retry_limit < 0:
        raise StructuredOutputError("retry_limit must be zero or positive")

    errors: list[str] = []
    raw_response: Mapping[str, Any] | str | None = None
    for attempt in range(1, retry_limit + 2):
        try:
            raw_response = runtime(request)
            structured_payload = extract_structured_output(raw_response)
            value = validator(structured_payload)
            return StructuredOutputResult(
                ok=True,
                value=value,
                attempts=attempt,
                validation_errors=tuple(errors),
                raw_response=raw_response,
            )
        except Exception as exc:  # noqa: BLE001 - boundary records all provider/schema failures.
            errors.append(str(exc))

    return StructuredOutputResult(
        ok=False,
        attempts=retry_limit + 1,
        validation_errors=tuple(errors),
        raw_response=raw_response,
    )


def extract_structured_output(response: Mapping[str, Any] | str) -> Mapping[str, Any]:
    """Extract a structured object from JSON Schema or tool-output style responses."""

    if isinstance(response, str):
        return _json_object(response)
    if not isinstance(response, Mapping):
        raise StructuredOutputError("structured response must be a mapping or JSON string")

    direct = _first_mapping_value(
        response,
        ("structured_output", "structuredOutput", "json", "outputJson"),
    )
    if direct is not None:
        return direct

    output = response.get("output")
    if isinstance(output, Mapping):
        direct_output = _first_mapping_value(
            output,
            ("structured_output", "structuredOutput", "json", "outputJson"),
        )
        if direct_output is not None:
            return direct_output
        message = output.get("message")
        if isinstance(message, Mapping):
            content = message.get("content")
            extracted = _extract_from_content_blocks(content)
            if extracted is not None:
                return extracted

    content = response.get("content")
    extracted = _extract_from_content_blocks(content)
    if extracted is not None:
        return extracted

    text = response.get("text")
    if isinstance(text, str):
        return _json_object(text)

    raise StructuredOutputError("no structured output object found")


def _extract_from_content_blocks(content: Any) -> Mapping[str, Any] | None:
    """Extract structured JSON from Converse content blocks."""

    if isinstance(content, Mapping):
        content = (content,)
    if not isinstance(content, Sequence) or isinstance(content, (str, bytes)):
        return None

    for block in content:
        if not isinstance(block, Mapping):
            continue
        direct = _first_mapping_value(block, ("json", "structured_output", "structuredOutput"))
        if direct is not None:
            return direct
        tool_use = block.get("toolUse") or block.get("tool_use")
        if isinstance(tool_use, Mapping):
            tool_input = tool_use.get("input")
            if isinstance(tool_input, Mapping):
                return tool_input
            if isinstance(tool_input, str):
                return _json_object(tool_input)
        text = block.get("text")
        if isinstance(text, str):
            return _json_object(text)
    return None


def _first_mapping_value(
    payload: Mapping[str, Any],
    keys: tuple[str, ...],
) -> Mapping[str, Any] | None:
    """Return the first mapping value under any key."""

    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str):
            return _json_object(value)
    return None


def _json_object(text: str) -> Mapping[str, Any]:
    """Parse a JSON object, including one recoverable provider text wrapper.

    Some Converse models return a valid JSON object after a malformed textual
    prefix even when JSON Schema output is requested. This boundary extracts a
    syntactically valid inner object only; the caller's schema/business
    validator must still approve every field before it enters graph state.
    """

    try:
        value = json.loads(text)
    except json.JSONDecodeError as direct_error:
        decoder = json.JSONDecoder()
        value = None
        for index, character in enumerate(text):
            if character != "{":
                continue
            try:
                candidate, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            # 모델이 실제 객체 앞에 빈 객체(``{}``)를 뱉으면 그것이 먼저 raw_decode되어
            # 잘못 채택된다(검증 실패→재시도 유발). 빈/키 없는 객체는 건너뛴다.
            if isinstance(candidate, Mapping) and candidate:
                value = candidate
                break
        if value is None:
            raise StructuredOutputError(
                "structured output text is not valid JSON",
            ) from direct_error
    if not isinstance(value, Mapping):
        raise StructuredOutputError("structured output JSON must be an object")
    return value


def _required_text(value: Any, field_name: str) -> str:
    """Validate non-empty request metadata."""

    if not isinstance(value, str):
        raise StructuredOutputError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise StructuredOutputError(f"{field_name} must be a non-empty string")
    return normalized


def _usage_int(usage: Mapping[str, Any], field_name: str) -> int:
    value = usage.get(field_name)
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _duration_ms(started_at: float) -> int:
    return max(0, int((time.perf_counter() - started_at) * 1000))


__all__ = [
    "ADAPTER_NAME",
    "RESPONSIBILITY",
    "STRUCTURED_OUTPUT_TEXT_FORMAT",
    "OutputValidator",
    "RuntimeInvoker",
    "BedrockConverseClient",
    "BedrockConverseRuntime",
    "StructuredOutputError",
    "StructuredOutputResult",
    "build_json_schema_text_format",
    "build_structured_converse_request",
    "create_bedrock_converse_runtime",
    "extract_structured_output",
    "invoke_structured_output",
]
