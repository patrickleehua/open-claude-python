"""Auto-compact trigger logic — proactively compress when approaching limits.

Ported from Claude-Code-rev/src/services/compact/autoCompact.ts.

Monitors token usage after each query loop turn and triggers compaction
when usage approaches the model's context window limit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from open_claude.services.compact.compact import (
    CompactionResult,
    compact_conversation,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants (mirrors TS autoCompact.ts)
# ---------------------------------------------------------------------------

RESERVED_OUTPUT_TOKENS = 20_000
AUTOCOMPACT_BUFFER_TOKENS = 13_000
DEFAULT_CONTEXT_WINDOW = 200_000
MAX_CONSECUTIVE_FAILURES = 3


# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------

@dataclass
class _AutoCompactState:
    """Mutable state for the auto-compact circuit breaker."""

    consecutive_failures: int = 0


_state: _AutoCompactState | None = None


def reset_auto_compact_state() -> None:
    """Reset auto-compact state (e.g. on session reset)."""
    global _state
    _state = _AutoCompactState()


def _get_state() -> _AutoCompactState:
    global _state
    if _state is None:
        _state = _AutoCompactState()
    return _state


# ---------------------------------------------------------------------------
# Threshold calculation
# ---------------------------------------------------------------------------


@dataclass
class CompactThresholdState:
    """Result of checking auto-compact thresholds."""

    should_compact: bool
    token_usage: int
    context_window: int
    threshold: int


def calculate_compact_state(
    token_usage: int,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
) -> CompactThresholdState:
    """Determine whether auto-compact should trigger.

    Mirrors TS ``calculateTokenWarningState`` / ``shouldAutoCompact``.

    Parameters
    ----------
    token_usage:
        Current token usage estimate.
    context_window:
        Model's context window size (default 200k).

    Returns
    -------
    CompactThresholdState indicating whether to compact.
    """
    effective_window = context_window - RESERVED_OUTPUT_TOKENS
    threshold = effective_window - AUTOCOMPACT_BUFFER_TOKENS

    should_compact = token_usage >= threshold

    return CompactThresholdState(
        should_compact=should_compact,
        token_usage=token_usage,
        context_window=context_window,
        threshold=threshold,
    )


# ---------------------------------------------------------------------------
# Auto-compact entry point
# ---------------------------------------------------------------------------


async def auto_compact_if_needed(
    messages: list[dict],
    token_usage: int,
    llm_call_fn,
    *,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    instructions: str = "",
) -> CompactionResult | None:
    """Trigger auto-compact if token usage exceeds the threshold.

    Mirrors TS ``autoCompactIfNeeded``.

    Includes a circuit breaker: after ``MAX_CONSECUTIVE_FAILURES`` consecutive
    failures, further attempts are suppressed for the session.

    Parameters
    ----------
    messages:
        Current conversation history.
    token_usage:
        Estimated token count of the messages.
    llm_call_fn:
        Async callable ``async (system, messages) -> str``.
    context_window:
        Model context window size.
    instructions:
        Optional custom summarization instructions.

    Returns
    -------
    CompactionResult if compaction was triggered, or None if not needed.
    """
    state = _get_state()

    # Circuit breaker
    if state.consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
        logger.debug(
            "[auto-compact] suppressed — %d consecutive failures",
            state.consecutive_failures,
        )
        return None

    # Check threshold
    compact_state = calculate_compact_state(token_usage, context_window)
    if not compact_state.should_compact:
        return None

    logger.info(
        "[auto-compact] triggering — %d tokens used (threshold: %d)",
        token_usage,
        compact_state.threshold,
    )

    try:
        result = await compact_conversation(
            messages, llm_call_fn, instructions=instructions,
        )

        if result.success:
            state.consecutive_failures = 0
            logger.info(
                "[auto-compact] success — %d -> %d tokens",
                result.pre_compact_token_count,
                result.post_compact_token_count,
            )
        else:
            state.consecutive_failures += 1
            logger.warning(
                "[auto-compact] failed (%d consecutive) — %s",
                state.consecutive_failures,
                result.display_text,
            )

        return result

    except Exception as e:
        state.consecutive_failures += 1
        logger.error(
            "[auto-compact] exception (%d consecutive): %s",
            state.consecutive_failures,
            e,
        )
        return None
