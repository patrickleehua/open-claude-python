"""Session Memory — automatic conversation summarization.

Ported from Claude-Code-rev/src/services/SessionMemory/sessionMemory.ts.

Session Memory automatically maintains a markdown file with notes about the
current conversation. It runs periodically in the background to extract key
information without interrupting the main conversation flow.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from open_claude.services.session_memory.prompts import (
    DEFAULT_SESSION_MEMORY_TEMPLATE,
    build_session_memory_update_prompt,
    load_session_memory_template,
)
from open_claude.services.session_memory.utils import (
    SessionMemoryConfig,
    get_session_memory_config,
    get_session_memory_content,
    get_session_memory_dir,
    get_session_memory_path,
    has_met_initialization_threshold,
    has_met_update_threshold,
    is_session_memory_initialized,
    mark_extraction_completed,
    mark_extraction_started,
    mark_session_memory_initialized,
    record_extraction_token_count,
    set_last_summarized_message_id,
)

logger = logging.getLogger(__name__)


@dataclass
class ManualExtractionResult:
    success: bool
    memory_path: str | None = None
    error: str | None = None


def should_extract_memory(messages: list[dict], token_count_fn=None) -> bool:
    """Determine if session memory extraction should run.

    Args:
        messages: Conversation messages.
        token_count_fn: Callable that returns estimated token count for messages.
    """
    if token_count_fn is None:
        # Rough estimation
        total = sum(len(str(m)) for m in messages) // 4
    else:
        total = token_count_fn(messages)

    if not is_session_memory_initialized():
        if not has_met_initialization_threshold(total):
            return False
        mark_session_memory_initialized()

    has_met_token_threshold = has_met_update_threshold(total)

    # Count tool calls since last extraction
    tool_calls = sum(
        1
        for m in messages
        if m.get("role") == "assistant"
        and isinstance(m.get("content"), list)
        and any(b.get("type") == "tool_use" for b in m["content"])
    )
    has_met_tool_call_threshold = tool_calls >= get_session_memory_config().tool_calls_between_updates

    # Check if last assistant turn has no tool calls (safe to extract)
    last_assistant = None
    for m in reversed(messages):
        if m.get("role") == "assistant":
            last_assistant = m
            break

    has_tool_calls_in_last_turn = False
    if last_assistant and isinstance(last_assistant.get("content"), list):
        has_tool_calls_in_last_turn = any(
            b.get("type") == "tool_use" for b in last_assistant["content"]
        )

    should_extract = (
        (has_met_token_threshold and has_met_tool_call_threshold)
        or (has_met_token_threshold and not has_tool_calls_in_last_turn)
    )

    return should_extract


async def setup_session_memory_file() -> tuple[str, str]:
    """Set up the session memory file and return (memory_path, current_content)."""
    session_memory_dir = get_session_memory_dir()
    session_memory_dir.mkdir(parents=True, exist_ok=True)

    memory_path = get_session_memory_path()

    # Create the memory file if it doesn't exist
    if not memory_path.exists():
        template = await load_session_memory_template()
        memory_path.write_text(template, encoding="utf-8")

    # Read current content
    current_memory = memory_path.read_text(encoding="utf-8")
    return str(memory_path), current_memory


async def extract_session_memory(
    messages: list[dict],
    *,
    llm_call_fn=None,
    token_count_fn=None,
) -> None:
    """Run session memory extraction.

    Args:
        messages: Conversation messages.
        llm_call_fn: Async callable for making LLM API calls.
            Signature: (system: str, messages: list) -> str
        token_count_fn: Callable for estimating token counts.
    """
    if not should_extract_memory(messages, token_count_fn):
        return

    mark_extraction_started()

    try:
        memory_path, current_memory = await setup_session_memory_file()

        if llm_call_fn is None:
            logger.debug("[session_memory] no LLM call function provided, skipping extraction")
            return

        user_prompt = await build_session_memory_update_prompt(current_memory, memory_path)

        # Call LLM to generate edits
        result = await llm_call_fn(
            system="You are updating session notes for a coding session.",
            messages=[{"role": "user", "content": user_prompt}],
        )

        if result:
            logger.debug("[session_memory] extraction completed, path=%s", memory_path)

        # Record token count
        if token_count_fn:
            record_extraction_token_count(token_count_fn(messages))

    except Exception as e:
        logger.debug("[session_memory] extraction failed: %s", e)
    finally:
        mark_extraction_completed()


async def manually_extract_session_memory(
    messages: list[dict],
    *,
    llm_call_fn=None,
) -> ManualExtractionResult:
    """Manually trigger session memory extraction, bypassing threshold checks."""
    if not messages:
        return ManualExtractionResult(success=False, error="No messages to summarize")

    mark_extraction_started()

    try:
        memory_path, current_memory = await setup_session_memory_file()

        if llm_call_fn is None:
            return ManualExtractionResult(success=False, error="No LLM call function provided")

        user_prompt = await build_session_memory_update_prompt(current_memory, memory_path)

        await llm_call_fn(
            system="You are updating session notes for a coding session.",
            messages=[{"role": "user", "content": user_prompt}],
        )

        return ManualExtractionResult(success=True, memory_path=memory_path)

    except Exception as e:
        return ManualExtractionResult(success=False, error=str(e))
    finally:
        mark_extraction_completed()
