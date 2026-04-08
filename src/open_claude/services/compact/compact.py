"""Core compaction engine — compress conversation while preserving key context.

Ported from Claude-Code-rev/src/services/compact/compact.ts.

Summarizes the conversation history via an LLM call, then replaces the full
message list with a compact boundary marker + summary + system reminder.
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field

from open_claude.services.compact.prompts import (
    format_compact_summary,
    get_compact_prompt,
    get_compact_user_summary_message,
    get_partial_compact_prompt,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_COMPACT_SYSTEM_PROMPT = (
    "You are a helpful AI assistant tasked with summarizing conversations."
)
_MAX_PTL_RETRIES = 3  # prompt-too-long retry attempts
_MAX_STREAMING_RETRIES = 2


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class CompactionResult:
    """Result of a compaction operation."""

    compacted_messages: list[dict]
    display_text: str
    pre_compact_token_count: int = 0
    post_compact_token_count: int = 0
    success: bool = True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def rough_token_count(messages: list[dict]) -> int:
    """Rough token estimation: ~4 bytes per token.

    Mirrors TS ``roughTokenCountEstimation``.
    """
    total_chars = sum(len(str(m)) for m in messages)
    return total_chars // 4


def group_messages_by_api_round(messages: list[dict]) -> list[list[dict]]:
    """Group messages by API round boundaries.

    A boundary fires when a new assistant message has a different ``id``
    from the previously seen one.

    Mirrors TS ``groupMessagesByApiRound``.
    """
    groups: list[list[dict]] = []
    current_group: list[dict] = []
    last_assistant_id: str | None = None

    for msg in messages:
        is_assistant = msg.get("role") == "assistant"
        msg_id = msg.get("id") or msg.get("uuid")

        if (
            is_assistant
            and msg_id is not None
            and msg_id != last_assistant_id
            and current_group
        ):
            groups.append(current_group)
            current_group = []

        current_group.append(msg)

        if is_assistant and msg_id is not None:
            last_assistant_id = msg_id

    if current_group:
        groups.append(current_group)

    return groups


def strip_images_from_messages(messages: list[dict]) -> list[dict]:
    """Replace image/document blocks with text markers.

    Mirrors TS ``stripImagesFromMessages``.
    """
    result = copy.deepcopy(messages)

    for msg in result:
        if msg.get("role") not in ("user", "assistant"):
            continue
        content = msg.get("content")
        if isinstance(content, list):
            msg["content"] = _strip_images_in_blocks(content)

    return result


def _strip_images_in_blocks(blocks: list[dict]) -> list[dict]:
    out: list[dict] = []
    for block in blocks:
        btype = block.get("type", "")
        if btype == "image":
            out.append({"type": "text", "text": "[image]"})
        elif btype == "document":
            out.append({"type": "text", "text": "[document]"})
        else:
            # Recurse into tool_result content arrays
            if btype == "tool_result":
                inner = block.get("content")
                if isinstance(inner, list):
                    block = {**block, "content": _strip_images_in_blocks(inner)}
            out.append(block)
    return out


def _truncate_head_for_ptl_retry(
    messages: list[dict],
    estimated_overage: int,
) -> list[dict] | None:
    """Drop oldest API-round groups to fit within token limits.

    Mirrors TS ``truncateHeadForPTLRetry``.
    """
    groups = group_messages_by_api_round(messages)
    if len(groups) <= 1:
        return None

    avg_tokens_per_group = max(rough_token_count(messages) // len(groups), 1)
    groups_to_drop = max(1, estimated_overage // avg_tokens_per_group)
    groups_to_drop = min(groups_to_drop, len(groups) - 1)

    kept = []
    for g in groups[groups_to_drop:]:
        kept.extend(g)

    # API requires first message to be user role
    if kept and kept[0].get("role") == "assistant":
        kept.insert(0, {
            "role": "user",
            "content": "[conversation start]",
        })

    return kept


# ---------------------------------------------------------------------------
# Core compaction
# ---------------------------------------------------------------------------


async def compact_conversation(
    messages: list[dict],
    llm_call_fn,
    *,
    instructions: str = "",
    max_retries: int = _MAX_PTL_RETRIES,
) -> CompactionResult:
    """Summarize the full conversation and produce a compacted message list.

    Mirrors TS ``compactConversation``.

    Parameters
    ----------
    messages:
        The full conversation history.
    llm_call_fn:
        Async callable ``async (system, messages) -> str``.
    instructions:
        Optional custom summarization instructions from the user.
    max_retries:
        Maximum prompt-too-long retry attempts.

    Returns
    -------
    CompactionResult with the new compacted message list.
    """
    if not messages:
        return CompactionResult(
            compacted_messages=[],
            display_text="No messages to compact.",
            success=False,
        )

    pre_token_count = rough_token_count(messages)
    working_messages = strip_images_from_messages(messages)

    # Build the summarization request
    prompt = get_compact_prompt(instructions)
    summary_request: dict = {
        "role": "user",
        "content": prompt,
    }

    # --- Summary generation with PTL retry ---
    raw_summary: str | None = None

    for attempt in range(max_retries + 1):
        try:
            # Append the summary request to the conversation
            api_messages = working_messages + [summary_request]

            raw_summary = await llm_call_fn(
                system=_COMPACT_SYSTEM_PROMPT,
                messages=api_messages,
            )

            # Check for prompt-too-long errors
            if raw_summary and _is_prompt_too_long_error(raw_summary):
                logger.debug(
                    "[compact] prompt-too-long on attempt %d, truncating head",
                    attempt + 1,
                )
                estimated_overage = _parse_ptl_overage(raw_summary, pre_token_count)
                truncated = _truncate_head_for_ptl_retry(
                    working_messages, estimated_overage,
                )
                if truncated is None:
                    logger.warning("[compact] cannot truncate further — aborting")
                    return CompactionResult(
                        compacted_messages=list(messages),
                        display_text="Compaction failed: conversation too large to summarize.",
                        pre_compact_token_count=pre_token_count,
                        post_compact_token_count=pre_token_count,
                        success=False,
                    )
                working_messages = truncated
                continue

            break  # success

        except Exception as e:
            logger.error("[compact] LLM call failed (attempt %d): %s", attempt + 1, e)
            if attempt >= max_retries:
                return CompactionResult(
                    compacted_messages=list(messages),
                    display_text=f"Compaction failed: {e}",
                    pre_compact_token_count=pre_token_count,
                    post_compact_token_count=pre_token_count,
                    success=False,
                )

    if not raw_summary or not raw_summary.strip():
        return CompactionResult(
            compacted_messages=list(messages),
            display_text="Compaction failed: empty summary.",
            pre_compact_token_count=pre_token_count,
            post_compact_token_count=pre_token_count,
            success=False,
        )

    # --- Format and build result ---
    formatted = format_compact_summary(raw_summary)
    summary_text = get_compact_user_summary_message(
        formatted, suppress_follow_up_questions=True,
    )

    # Build compacted messages: boundary marker + summary + system reminder
    boundary_marker: dict = {
        "role": "user",
        "content": (
            "<system-reminder>\n"
            "The previous conversation has been compacted. "
            "The summary below captures the key context.\n"
            "</system-reminder>"
        ),
    }
    summary_message: dict = {
        "role": "user",
        "content": summary_text,
    }

    compacted = [boundary_marker, summary_message]
    post_token_count = rough_token_count(compacted)

    display = (
        f"Conversation compacted: {pre_token_count} -> {post_token_count} "
        f"tokens (~{post_token_count * 100 // max(pre_token_count, 1)}% of original)"
    )

    return CompactionResult(
        compacted_messages=compacted,
        display_text=display,
        pre_compact_token_count=pre_token_count,
        post_compact_token_count=post_token_count,
        success=True,
    )


# ---------------------------------------------------------------------------
# Error detection helpers
# ---------------------------------------------------------------------------

_PTL_PATTERNS = [
    r"prompt is too long",
    r"request too large",
    r"exceeds the maximum",
    r"too many tokens",
]


def _is_prompt_too_long_error(text: str) -> bool:
    lower = text.lower()
    return any(re.search(p, lower) for p in _PTL_PATTERNS)


def _parse_ptl_overage(error_text: str, current_estimate: int) -> int:
    """Try to parse token overage from the error message."""
    # Look for patterns like "X tokens over" or "maximum of Y tokens"
    match = re.search(r"(\d+)\s*tokens?\s*(?:over|exceeding)", error_text, re.I)
    if match:
        return int(match.group(1))
    # Fallback: assume ~20% overage
    return current_estimate // 5


# ---------------------------------------------------------------------------
# Module-level singleton (matches extract_memories pattern)
# ---------------------------------------------------------------------------

_service_llm_call_fn = None


def init_compact(llm_call_fn=None) -> None:
    """Initialize the compact service.

    Call once at startup. Stores the LLM callback for later use.
    """
    global _service_llm_call_fn
    _service_llm_call_fn = llm_call_fn


def reset_compact() -> None:
    """Reset the compact service state."""
    global _service_llm_call_fn
    _service_llm_call_fn = None


async def execute_compact(
    messages: list[dict],
    *,
    instructions: str = "",
) -> CompactionResult:
    """Run compaction using the initialized LLM callback.

    No-op until ``init_compact()`` has been called with an ``llm_call_fn``.
    """
    if _service_llm_call_fn is None:
        return CompactionResult(
            compacted_messages=list(messages),
            display_text="Compact service not initialized (no LLM callback).",
            success=False,
        )
    return await compact_conversation(
        messages, _service_llm_call_fn, instructions=instructions,
    )
