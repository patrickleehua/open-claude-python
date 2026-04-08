"""Background memory consolidation (AutoDream).

Ported from Claude-Code-rev/src/services/autoDream/autoDream.ts.

Runs periodically as a forked subagent when time-gate passes AND enough
sessions have accumulated. Gate order (cheapest first):
  1. Time: hours since lastConsolidatedAt >= minHours
  2. Lock: no other process mid-consolidation
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from open_claude.services.auto_dream.config import is_auto_dream_enabled
from open_claude.services.auto_dream.consolidation_lock import (
    read_last_consolidated_at,
    rollback_consolidation_lock,
    try_acquire_consolidation_lock,
)
from open_claude.services.auto_dream.consolidation_prompt import build_consolidation_prompt
from open_claude.utils.memory.paths import get_memory_dir, is_auto_memory_enabled

logger = logging.getLogger(__name__)

_SESSION_SCAN_INTERVAL_MS = 10 * 60 * 1000  # 10 minutes


@dataclass
class AutoDreamConfig:
    min_hours: int = 24
    min_sessions: int = 5


_DEFAULTS = AutoDreamConfig()


def _get_config() -> AutoDreamConfig:
    """Return scheduling knobs (simplified — no remote config)."""
    return _DEFAULTS


class AutoDreamRunner:
    """Stateful auto-dream runner (closure-scoped via init_auto_dream)."""

    def __init__(self) -> None:
        self._last_session_scan_at: float = 0.0
        self._llm_call_fn = None

    def set_llm_call_fn(self, fn) -> None:
        self._llm_call_fn = fn

    async def run(self, extra: str = "") -> None:
        """Execute one auto-dream check/run cycle."""
        if not is_auto_memory_enabled() or not is_auto_dream_enabled():
            return

        if self._llm_call_fn is None:
            return

        cfg = _get_config()

        # --- Time gate ---
        try:
            last_at = await read_last_consolidated_at()
        except Exception as e:
            logger.debug("[autoDream] readLastConsolidatedAt failed: %s", e)
            return

        hours_since = (time.time() * 1000 - last_at) / 3_600_000
        if hours_since < cfg.min_hours:
            return

        # --- Scan throttle ---
        since_scan_ms = time.time() * 1000 - self._last_session_scan_at
        if since_scan_ms < _SESSION_SCAN_INTERVAL_MS:
            logger.debug(
                "[autoDream] scan throttle — last scan was %.0fs ago",
                since_scan_ms / 1000,
            )
            return
        self._last_session_scan_at = time.time() * 1000

        # --- Lock ---
        try:
            prior_mtime = await try_acquire_consolidation_lock()
        except Exception as e:
            logger.debug("[autoDream] lock acquire failed: %s", e)
            return
        if prior_mtime is None:
            return

        logger.debug(
            "[autoDream] firing — %.1fh since last consolidation",
            hours_since,
        )

        try:
            memory_root = str(get_memory_dir())
            # Simplified: no transcript dir in Python port
            transcript_dir = ""

            prompt = build_consolidation_prompt(memory_root, transcript_dir, extra)

            await self._llm_call_fn(
                system="You are a memory consolidation agent.",
                messages=[{"role": "user", "content": prompt}],
            )

            logger.debug("[autoDream] completed successfully")

        except Exception as e:
            logger.debug("[autoDream] failed: %s", e)
            await rollback_consolidation_lock(prior_mtime)


# Module-level singleton
_runner: AutoDreamRunner | None = None


def init_auto_dream(llm_call_fn=None) -> None:
    """Initialize the auto-dream system.

    Call once at startup.
    """
    global _runner
    _runner = AutoDreamRunner()
    if llm_call_fn:
        _runner.set_llm_call_fn(llm_call_fn)


async def execute_auto_dream(extra: str = "") -> None:
    """Run one auto-dream check cycle.

    No-op until init_auto_dream() has been called.
    """
    if _runner:
        await _runner.run(extra)
