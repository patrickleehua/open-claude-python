"""Event and result types for the query engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Re-export TokenUsage from the canonical location
from open_claude.services.api.usage import TokenUsage  # noqa: F401


@dataclass
class ContentBlock:
    """A single content block within an assistant message."""

    type: str  # 'text', 'tool_use', 'thinking'
    text: str | None = None
    id: str | None = None  # tool_use block id
    name: str | None = None  # tool_use tool name
    input: dict | None = None  # tool_use parsed JSON input
    thinking: str | None = None  # thinking block content
    signature: str | None = None  # thinking block signature


@dataclass
class StreamEvent:
    """Events yielded by the query engine during streaming."""

    type: str  # 'text', 'tool_use', 'tool_result', 'thinking', 'usage', 'error', 'stop'
    content: Any = None


@dataclass
class QueryResult:
    """Final result from a query."""

    stop_reason: str  # 'end_turn', 'max_tokens', 'tool_use', 'error'
    usage: TokenUsage = field(default_factory=TokenUsage)
    duration_ms: float = 0.0
    total_turns: int = 0
