"""File-based consolidation lock using mtime.

Ported from Claude-Code-rev/src/services/autoDream/consolidationLock.ts.

Lock file lives inside the memory dir. Its mtime IS lastConsolidatedAt.
Body is the holder's PID.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from open_claude.utils.memory.paths import get_memory_dir

logger = logging.getLogger(__name__)

_LOCK_FILE = ".consolidate-lock"
_HOLDER_STALE_MS = 60 * 60 * 1000  # 1 hour


def _lock_path() -> Path:
    return get_memory_dir() / _LOCK_FILE


def _is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


async def read_last_consolidated_at() -> float:
    """Read mtime of lock file (= lastConsolidatedAt). 0 if absent."""
    path = _lock_path()
    try:
        return path.stat().st_mtime * 1000
    except (FileNotFoundError, OSError):
        return 0.0


async def try_acquire_consolidation_lock() -> float | None:
    """Acquire: write PID → mtime = now.

    Returns pre-acquire mtime (for rollback), or None if blocked / lost race.
    """
    path = _lock_path()

    mtime_ms: float | None = None
    holder_pid: int | None = None

    try:
        stat_result = path.stat()
        mtime_ms = stat_result.st_mtime * 1000
        raw = path.read_text(encoding="utf-8").strip()
        parsed = int(raw) if raw else None
        holder_pid = parsed if parsed and parsed > 0 else None
    except (FileNotFoundError, OSError, ValueError):
        pass

    if mtime_ms is not None and time.time() * 1000 - mtime_ms < _HOLDER_STALE_MS:
        if holder_pid is not None and _is_process_running(holder_pid):
            logger.debug(
                "[autoDream] lock held by live PID %d (mtime %.0fs ago)",
                holder_pid,
                (time.time() * 1000 - mtime_ms) / 1000,
            )
            return None

    # Memory dir may not exist yet
    get_memory_dir().mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()), encoding="utf-8")

    # Race: two reclaimers both write → last wins. Loser bails on re-read.
    try:
        verify = path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None

    if int(verify) != os.getpid():
        return None

    return mtime_ms or 0.0


async def rollback_consolidation_lock(prior_mtime: float) -> None:
    """Rewind mtime to pre-acquire after a failed consolidation.

    prior_mtime 0 → delete file (restore no-file state).
    """
    path = _lock_path()
    try:
        if prior_mtime == 0:
            path.unlink(missing_ok=True)
            return

        path.write_text("", encoding="utf-8")
        t = prior_mtime / 1000
        os.utime(path, (t, t))
    except OSError as e:
        logger.debug("[autoDream] rollback failed: %s — next trigger delayed", e)


async def record_consolidation() -> None:
    """Stamp after manual /dream. Best-effort."""
    try:
        get_memory_dir().mkdir(parents=True, exist_ok=True)
        _lock_path().write_text(str(os.getpid()), encoding="utf-8")
    except OSError as e:
        logger.debug("[autoDream] recordConsolidation write failed: %s", e)
