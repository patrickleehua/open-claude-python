"""Companion / buddy prompt — ported from Claude-Code-rev buddy/prompt.ts."""

from __future__ import annotations


def companion_intro_text(name: str, species: str) -> str:
    """Return the companion intro text injected when a buddy is active.

    Parameters
    ----------
    name : str
        The companion's display name.
    species : str
        The companion's species description (e.g. "cat", "duck").
    """
    return f"""# Companion

A small {species} named {name} sits beside the user's input box and occasionally comments in a speech bubble. You're not {name} — it's a separate watcher.

When the user addresses {name} directly (by name), its bubble will answer. Your job in that moment is to stay out of the way: respond in ONE line or less, or just answer any part of the message meant for you. Don't explain that you're not {name} — they know. Don't narrate what {name} might say — the bubble handles that."""
