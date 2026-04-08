"""Streaming response parser for Anthropic API events."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

from open_claude.query.types import ContentBlock, StreamEvent
from open_claude.services.api.usage import TokenUsage


def _update_usage(current: TokenUsage, incoming: Any | None) -> TokenUsage:
    """Merge incoming usage into current, only updating fields with non-zero values.

    The API may send explicit 0 values in message_delta events that should not
    overwrite values already set in message_start.
    Accepts both dicts and SDK Usage objects.
    """
    if incoming is None:
        return current

    input_tokens = _get_attr(incoming, "input_tokens", 0) or 0
    output_tokens = _get_attr(incoming, "output_tokens", 0) or 0
    cache_creation = _get_attr(incoming, "cache_creation_input_tokens", 0) or 0
    cache_read = _get_attr(incoming, "cache_read_input_tokens", 0) or 0

    if input_tokens > 0:
        current.input_tokens = input_tokens
    if output_tokens > 0:
        current.output_tokens = output_tokens
    if cache_creation > 0:
        current.cache_creation_input_tokens = cache_creation
    if cache_read > 0:
        current.cache_read_input_tokens = cache_read

    return current


def _parse_tool_input(raw: str) -> dict[str, Any]:
    """Parse accumulated JSON string from input_json_delta into a dict."""
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _block_to_event(block: ContentBlock) -> StreamEvent:
    """Convert a completed ContentBlock into the appropriate StreamEvent."""
    if block.type == "text":
        return StreamEvent(type="text", content=block.text or "")
    if block.type == "tool_use":
        return StreamEvent(type="tool_use", content=block)
    if block.type == "thinking":
        return StreamEvent(type="thinking", content=block.thinking or "")
    return StreamEvent(type="text", content=str(block))


async def parse_stream(
    stream: AsyncGenerator[Any, None],
) -> AsyncGenerator[StreamEvent, None]:
    """Parse raw Anthropic streaming events into StreamEvent instances.

    Handles the SSE event lifecycle:
      message_start      -> capture initial message metadata and usage
      content_block_start -> initialize a content block by index
      content_block_delta -> accumulate deltas (text, input_json, thinking)
      content_block_stop  -> finalize block, yield as StreamEvent
      message_delta       -> capture stop_reason and final usage
      message_stop        -> emit stop event

    Yields one StreamEvent per completed content block, plus a final
    'stop' event with the stop_reason and a 'usage' event with token stats.
    """
    content_blocks: dict[int, ContentBlock] = {}
    usage = TokenUsage()
    stop_reason: str | None = None

    async for event in stream:
        event_type = getattr(event, "type", None) or (
            event.get("type") if isinstance(event, dict) else None
        )

        if event_type == "message_start":
            msg = _get_attr(event, "message", {})
            raw_usage = _get_attr(msg, "usage", None)
            usage = _update_usage(usage, raw_usage)

        elif event_type == "content_block_start":
            idx = _get_attr(event, "index", 0)
            block = _get_attr(event, "content_block", {})
            block_type = _get_attr(block, "type", "text")

            if block_type == "tool_use":
                content_blocks[idx] = ContentBlock(
                    type="tool_use",
                    id=_get_attr(block, "id", None),
                    name=_get_attr(block, "name", None),
                    input=None,  # accumulated via deltas
                )
            elif block_type == "thinking":
                content_blocks[idx] = ContentBlock(
                    type="thinking",
                    thinking="",
                    signature="",
                )
            else:
                # text blocks: text may appear in start but we accumulate
                # via deltas instead (SDK sometimes duplicates it)
                content_blocks[idx] = ContentBlock(
                    type="text",
                    text="",
                )

        elif event_type == "content_block_delta":
            idx = _get_attr(event, "index", 0)
            delta = _get_attr(event, "delta", {})
            delta_type = _get_attr(delta, "type", "")
            block = content_blocks.get(idx)

            if block is None:
                continue

            if delta_type == "text_delta" and block.type == "text":
                block.text = (block.text or "") + _get_attr(delta, "text", "")

            elif delta_type == "input_json_delta" and block.type == "tool_use":
                # Accumulate partial JSON string; parse on content_block_stop
                partial = _get_attr(delta, "partial_json", "")
                block.input = (block.input if isinstance(block.input, str) else "") + partial

            elif delta_type == "thinking_delta" and block.type == "thinking":
                block.thinking = (block.thinking or "") + _get_attr(delta, "thinking", "")

            elif delta_type == "signature_delta" and block.type == "thinking":
                block.signature = _get_attr(delta, "signature", "")

        elif event_type == "content_block_stop":
            idx = _get_attr(event, "index", 0)
            block = content_blocks.get(idx)
            if block is None:
                continue

            # Finalize tool_use input: parse accumulated JSON
            if block.type == "tool_use" and isinstance(block.input, str):
                block.input = _parse_tool_input(block.input)

            yield _block_to_event(block)

        elif event_type == "message_delta":
            delta = _get_attr(event, "delta", {})
            raw_usage = _get_attr(event, "usage", None)
            usage = _update_usage(usage, raw_usage)

            sr = _get_attr(delta, "stop_reason", None)
            if sr is not None:
                stop_reason = sr

        elif event_type == "message_stop":
            # Emit usage and stop events
            yield StreamEvent(type="usage", content=usage)
            yield StreamEvent(type="stop", content=stop_reason or "end_turn")


def _get_attr(obj: Any, key: str, default: Any = None) -> Any:
    """Retrieve an attribute from an object, falling back to dict-style access."""
    if hasattr(obj, key):
        return getattr(obj, key)
    if isinstance(obj, dict):
        return obj.get(key, default)
    return default
