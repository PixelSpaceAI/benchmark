from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Case:
    id: str
    category: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    ground_truth: list[dict[str, Any]] | None
    raw: dict[str, Any]

    def adapter_payload(self) -> dict[str, Any]:
        """Return the non-leaky request sent to a command adapter."""
        return {
            "id": self.id,
            "category": self.category,
            "messages": self.messages,
            "tools": self.tools,
            "raw": self.raw,
        }


@dataclass(slots=True)
class HarnessResponse:
    content: str
    tool_calls: list[dict[str, Any]]
    raw: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ScoreResult:
    status: str
    passed: bool | None
    reason: str
