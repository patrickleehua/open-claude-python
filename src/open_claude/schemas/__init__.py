"""Pydantic v2 models for the application."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from open_claude.constants import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    SYSTEM_PROMPT_DEFAULT,
)


class MessageRole(str, Enum):
    """Allowed roles in a conversation message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ChatMessage(BaseModel):
    """A single message in the conversation history."""

    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)


class ToolCall(BaseModel):
    """Represents a tool invocation requested by the assistant."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Result returned after executing a tool call."""

    tool_call_id: str
    output: str
    is_error: bool = False
    display_data: dict[str, Any] | None = None
    new_messages: list[dict[str, Any]] | None = None


class ToolExecutionResult(BaseModel):
    """Structured result returned by a tool executor."""

    output: str
    display_data: dict[str, Any] | None = None
    new_messages: list[dict[str, Any]] | None = None


class ConversationConfig(BaseModel):
    """Configuration for a conversation session."""

    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    system_prompt: str | None = SYSTEM_PROMPT_DEFAULT
