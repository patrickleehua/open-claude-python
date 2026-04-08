"""Permission result helper functions.

Ported from Claude-Code-rev src/utils/permissions/PermissionResult.ts.
"""

from __future__ import annotations

from open_claude.schemas.permissions import PermissionBehavior


def get_rule_behavior_description(behavior: PermissionBehavior) -> str:
    """Get a human-readable description for a rule behavior."""
    mapping = {
        PermissionBehavior.ALLOW: "allowed",
        PermissionBehavior.DENY: "denied",
        PermissionBehavior.ASK: "asked for confirmation for",
    }
    return mapping.get(behavior, str(behavior))
