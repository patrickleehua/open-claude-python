"""Memory age utilities.

Ported from Claude-Code-rev/src/memdir/memoryAge.ts.
"""

from __future__ import annotations

import time

_MS_PER_DAY = 86_400_000


def memory_age_days(mtime_ms: float) -> int:
    """Days elapsed since mtime. Floor-rounded.

    0 for today, 1 for yesterday, 2+ for older.
    Negative inputs (future mtime, clock skew) clamp to 0.
    """
    return max(0, int((time.time() * 1000 - mtime_ms) / _MS_PER_DAY))


def memory_age(mtime_ms: float) -> str:
    """Human-readable age string.

    Models are poor at date arithmetic — a raw ISO timestamp doesn't
    trigger staleness reasoning the way "47 days ago" does.
    """
    d = memory_age_days(mtime_ms)
    if d == 0:
        return "today"
    if d == 1:
        return "yesterday"
    return f"{d} days ago"


def memory_freshness_text(mtime_ms: float) -> str:
    """Plain-text staleness caveat for memories >1 day old.

    Returns '' for fresh (today/yesterday) memories — warning there is noise.
    """
    d = memory_age_days(mtime_ms)
    if d <= 1:
        return ""
    return (
        f"This memory is {d} days old. "
        "Memories are point-in-time observations, not live state — "
        "claims about code behavior or file:line citations may be outdated. "
        "Verify against current code before asserting as fact."
    )


def memory_freshness_note(mtime_ms: float) -> str:
    """Per-memory staleness note wrapped in <system-reminder> tags.

    Returns '' for memories ≤ 1 day old.
    """
    text = memory_freshness_text(mtime_ms)
    if not text:
        return ""
    return f"<system-reminder>{text}</system-reminder>\n"
