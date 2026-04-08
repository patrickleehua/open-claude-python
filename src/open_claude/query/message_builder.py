"""Message construction helpers for the Anthropic Messages API."""

from __future__ import annotations

from typing import Any

from open_claude.schemas import ToolResult


def build_user_message(text: str) -> dict[str, Any]:
    """Build a simple user message dict for the API."""
    return {"role": "user", "content": text}


def build_assistant_message(content: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an assistant message with content blocks."""
    return {"role": "assistant", "content": content}


def build_tool_result_message(tool_results: list[ToolResult]) -> dict[str, Any]:
    """Build a user message containing one or more tool_result blocks.

    The API requires all tool_result blocks to be in a single user message
    following the assistant message that requested them.
    """
    blocks: list[dict[str, Any]] = []
    for tr in tool_results:
        block: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": tr.tool_call_id,
            "content": tr.output,
        }
        if tr.is_error:
            block["is_error"] = True
        blocks.append(block)
    return {"role": "user", "content": blocks}


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ensure messages are in the correct format for the API.

    Validates roles alternate user/assistant, converts string content to
    the proper structure, and strips empty messages.
    """
    normalized: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue

        content = msg.get("content")
        if content is None:
            continue

        # Normalize string content for user messages
        if isinstance(content, str):
            if not content.strip():
                continue
            normalized.append({"role": role, "content": content})
        elif isinstance(content, list):
            normalized.append({"role": role, "content": content})
        else:
            normalized.append({"role": role, "content": str(content)})

    return normalized


def add_cache_breakpoints(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add cache_control breakpoints to the last user message.

    This enables prompt caching on the Anthropic API by marking the last
    user message with ephemeral cache control.
    """
    if not messages:
        return messages

    result = [msg.copy() for msg in messages]

    # Find the last user message and add cache_control
    for i in range(len(result) - 1, -1, -1):
        if result[i].get("role") == "user":
            content = result[i].get("content")
            if isinstance(content, list) and content:
                # Add cache_control to the last content block
                last_block = content[-1]
                if isinstance(last_block, dict):
                    content[-1] = {**last_block, "cache_control": {"type": "ephemeral"}}
            result[i] = {**result[i], "content": content}
            break

    return result
