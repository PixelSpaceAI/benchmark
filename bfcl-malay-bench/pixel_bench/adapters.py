from __future__ import annotations

import json
import os
import shlex
import subprocess
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any, Protocol

from .models import Case, HarnessResponse
from .normalize import normalize_response


class Adapter(Protocol):
    def invoke(self, case: Case) -> HarnessResponse: ...


class CommandAdapter:
    """Invoke one harness process per case using JSON over stdin/stdout."""

    def __init__(self, command: str | Sequence[str], *, timeout: float = 120) -> None:
        self.command = shlex.split(command) if isinstance(command, str) else list(command)
        if not self.command:
            raise ValueError("adapter command cannot be empty")
        self.timeout = timeout

    def invoke(self, case: Case) -> HarnessResponse:
        environment = os.environ.copy()
        environment["PIXEL_BENCH_CASE_ID"] = case.id
        environment["PIXEL_BENCH_CATEGORY"] = case.category
        try:
            completed = subprocess.run(
                self.command,
                input=json.dumps(case.adapter_payload(), ensure_ascii=False),
                text=True,
                capture_output=True,
                timeout=self.timeout,
                check=False,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(
                f"adapter timed out after {self.timeout:g}s for {case.id}"
            ) from error
        except OSError as error:
            raise RuntimeError(f"could not start adapter command: {error}") from error
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or "no output"
            raise RuntimeError(
                f"adapter exited with status {completed.returncode} for {case.id}: {detail}"
            )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise RuntimeError(
                f"adapter returned invalid JSON for {case.id}: {error}"
            ) from error
        response = normalize_response(payload)
        if completed.stderr.strip():
            response.metadata["stderr"] = completed.stderr.strip()
        return response


_TYPE_MAP = {
    "dict": "object",
    "Dictionary": "object",
    "HashMap": "object",
    "float": "number",
    "double": "number",
    "String": "string",
    "char": "string",
    "": "string",
    "Integer": "integer",
    "long": "integer",
    "Boolean": "boolean",
    "Array": "array",
    "ArrayList": "array",
    "List": "array",
    "tuple": "array",
    "any": None,
}


def normalize_json_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [normalize_json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: normalize_json_schema(item) for key, item in value.items()}
    schema_type = result.get("type")
    if isinstance(schema_type, str):
        normalized_type = _TYPE_MAP.get(schema_type, schema_type.lower())
        if normalized_type is None:
            result.pop("type")
        else:
            result["type"] = normalized_type
    if result.get("type") == "object" and "properties" not in result:
        result["properties"] = {}
    return result


def _openai_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = dict(tool)
    parameters = function.get("parameters")
    if isinstance(parameters, dict):
        function["parameters"] = normalize_json_schema(parameters)
    return {"type": "function", "function": function}


class OpenAIAdapter:
    """Call an OpenAI-compatible chat-completions endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: float = 120,
        temperature: float = 0,
    ) -> None:
        base_url = base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            self.endpoint = base_url
        elif base_url.endswith("/v1"):
            self.endpoint = f"{base_url}/chat/completions"
        else:
            self.endpoint = f"{base_url}/v1/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.temperature = temperature

    def invoke(self, case: Case) -> HarnessResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": case.messages,
            "temperature": self.temperature,
        }
        if case.tools:
            body["tools"] = [_openai_tool(tool) for tool in case.tools]
            body["tool_choice"] = "auto"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "pixel-bench/0.1",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.load(response)
        except TimeoutError as error:
            raise RuntimeError(
                f"endpoint request to {self.endpoint} timed out after "
                f"{self.timeout:g}s for {case.id}"
            ) from error
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"endpoint returned HTTP {error.code} for {case.id}: {detail}"
            ) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"endpoint request failed for {case.id}: {error}") from error
        normalized = normalize_response(payload)
        if isinstance(payload.get("usage"), dict):
            normalized.metadata["usage"] = payload["usage"]
        normalized.metadata["model"] = payload.get("model", self.model)
        return normalized
