from __future__ import annotations

import json
from typing import Any

from .models import HarnessResponse


def _arguments(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError(f"tool-call arguments are not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise ValueError("tool-call arguments must be a JSON object")
    return value


def _call(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("each tool call must be a JSON object")
    function = value.get("function")
    if isinstance(function, dict):
        name = function.get("name")
        arguments = function.get("arguments")
    else:
        name = value.get("name") or value.get("tool_name")
        arguments = value.get("arguments", value.get("input", value.get("parameters")))
    if not isinstance(name, str) or not name:
        raise ValueError("each tool call needs a non-empty name")
    return {"name": name, "arguments": _arguments(arguments)}


def normalize_response(payload: Any) -> HarnessResponse:
    """Normalize common harness/provider response shapes."""
    if not isinstance(payload, dict):
        raise ValueError("adapter response must be a JSON object")

    message = payload
    if "choices" in payload:
        choices = payload["choices"]
        if not isinstance(choices, list) or not choices:
            raise ValueError("OpenAI response choices must be a non-empty list")
        choice = choices[0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise ValueError("OpenAI response is missing choices[0].message")
        message = choice["message"]

    content = message.get("content", "")
    tool_calls: list[dict[str, Any]] = []

    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
            elif block.get("type") in {"tool_use", "tool_call"}:
                tool_calls.append(_call(block))
        content = "\n".join(text_parts)
    elif content is None:
        content = ""
    elif not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)

    raw_calls = message.get("tool_calls", message.get("calls", []))
    if raw_calls:
        if not isinstance(raw_calls, list):
            raise ValueError("tool_calls must be a list")
        tool_calls.extend(_call(item) for item in raw_calls)

    single_call = message.get("function_call")
    if single_call:
        tool_calls.append(_call({"function": single_call}))

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {"value": metadata}
    return HarnessResponse(
        content=content,
        tool_calls=tool_calls,
        raw=payload,
        metadata=metadata,
    )
