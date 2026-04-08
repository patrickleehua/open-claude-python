"""Auto-dream configuration.

Ported from Claude-Code-rev/src/services/autoDream/config.ts.
"""

from __future__ import annotations

from open_claude.services.settings.loader import load_settings


def is_auto_dream_enabled() -> bool:
    """Check if background memory consolidation is enabled.

    Checks settings.json for `autoDreamEnabled`. Defaults to False.
    """
    settings = load_settings()
    val = settings.raw.get("autoDreamEnabled")
    if val is not None:
        return bool(val)
    return False  # Default: disabled (opt-in)
