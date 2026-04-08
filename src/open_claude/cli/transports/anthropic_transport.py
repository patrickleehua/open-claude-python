"""Anthropic API transport with streaming support."""

from __future__ import annotations

import os
from typing import AsyncIterator

from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam, ToolParam

from open_claude.constants import DEFAULT_MODEL, DEFAULT_MAX_TOKENS, SYSTEM_PROMPT_DEFAULT


class AnthropicTransport:
    """Manages communication with the Anthropic API."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        api_key: str | None = None,
        system_prompt: str = SYSTEM_PROMPT_DEFAULT,
    ) -> None:
        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt
        self._client = AsyncAnthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    async def stream_message(
        self,
        messages: list[MessageParam],
        tools: list[ToolParam] | None = None,
    ) -> AsyncIterator:
        """Stream a response from the API. Yields content blocks."""
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system_prompt,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        async with self._client.messages.stream(**kwargs) as stream:
            async for event in stream:
                yield event

    async def send_message(
        self,
        messages: list[MessageParam],
        tools: list[ToolParam] | None = None,
    ) -> Message:
        """Send a message and get the full response (non-streaming)."""
        kwargs = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self.system_prompt,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        return await self._client.messages.create(**kwargs)

    async def close(self) -> None:
        """Close the API client."""
        await self._client.close()
