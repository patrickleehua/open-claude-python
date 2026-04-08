"""Compact service — context compression for long conversations.

Public API:
    - ``init_compact(llm_call_fn)`` — initialize with an LLM callback
    - ``execute_compact(messages, instructions)`` — run compaction
    - ``reset_compact()`` — tear down state
    - ``compact_conversation(messages, llm_call_fn, ...)`` — low-level entry
    - ``auto_compact_if_needed(messages, token_usage, llm_call_fn, ...)`` — auto-trigger
    - ``calculate_compact_state(token_usage, context_window)`` — threshold check
"""

from __future__ import annotations

from open_claude.services.compact.auto_compact import (
    auto_compact_if_needed,
    calculate_compact_state,
    reset_auto_compact_state,
)
from open_claude.services.compact.compact import (
    CompactionResult,
    compact_conversation,
    execute_compact,
    group_messages_by_api_round,
    init_compact,
    reset_compact,
    rough_token_count,
    strip_images_from_messages,
)

__all__ = [
    "CompactionResult",
    "auto_compact_if_needed",
    "calculate_compact_state",
    "compact_conversation",
    "execute_compact",
    "group_messages_by_api_round",
    "init_compact",
    "reset_auto_compact_state",
    "reset_compact",
    "rough_token_count",
    "strip_images_from_messages",
]
