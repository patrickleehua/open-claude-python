"""Denial tracking infrastructure for permission classifiers.

Ported from Claude-Code-rev src/utils/permissions/denialTracking.ts.
Tracks consecutive denials and total denials to determine
when to fall back to prompting.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DenialTrackingState:
    """Immutable state tracking denial counts."""

    consecutive_denials: int = 0
    total_denials: int = 0


DENIAL_LIMITS = {
    "max_consecutive": 3,
    "max_total": 20,
}


def create_denial_tracking_state() -> DenialTrackingState:
    """Create a fresh denial tracking state."""
    return DenialTrackingState()


def record_denial(state: DenialTrackingState) -> DenialTrackingState:
    """Record a denial, returning a new immutable state."""
    return DenialTrackingState(
        consecutive_denials=state.consecutive_denials + 1,
        total_denials=state.total_denials + 1,
    )


def record_success(state: DenialTrackingState) -> DenialTrackingState:
    """Record a success, resetting the consecutive denial counter."""
    if state.consecutive_denials == 0:
        return state
    return DenialTrackingState(
        consecutive_denials=0,
        total_denials=state.total_denials,
    )


def should_fallback_to_prompting(state: DenialTrackingState) -> bool:
    """Check if we should fall back to user prompting due to too many denials."""
    return (
        state.consecutive_denials >= DENIAL_LIMITS["max_consecutive"]
        or state.total_denials >= DENIAL_LIMITS["max_total"]
    )
