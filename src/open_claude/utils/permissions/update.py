"""Permission update operations — apply and persist changes.

Ported from Claude-Code-rev src/utils/permissions/PermissionUpdate.ts.
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

from open_claude.schemas.permissions import (
    AddDirectoriesUpdate,
    AddRulesUpdate,
    PermissionBehavior,
    PermissionRuleValue,
    PermissionUpdate,
    PermissionUpdateDestination,
    RemoveDirectoriesUpdate,
    RemoveRulesUpdate,
    ReplaceRulesUpdate,
    SetModeUpdate,
    ToolPermissionContext,
    ToolPermissionRulesBySource,
)
from open_claude.utils.permissions.rule_parser import (
    permission_rule_value_from_string,
    permission_rule_value_to_string,
)

logger = logging.getLogger(__name__)


def extract_rules(updates: list[PermissionUpdate] | None) -> list[PermissionRuleValue]:
    """Flatten addRules entries from a list of updates."""
    if not updates:
        return []
    result: list[PermissionRuleValue] = []
    for update in updates:
        if isinstance(update, AddRulesUpdate):
            result.extend(update.rules)
    return result


def has_rules(updates: list[PermissionUpdate] | None) -> bool:
    """Check if any updates contain rules."""
    return len(extract_rules(updates)) > 0


def _rule_kind_for_behavior(
    behavior: PermissionBehavior,
) -> str:
    """Map behavior to the context field name."""
    return {
        PermissionBehavior.ALLOW: "always_allow_rules",
        PermissionBehavior.DENY: "always_deny_rules",
        PermissionBehavior.ASK: "always_ask_rules",
    }[behavior]


def apply_permission_update(
    context: ToolPermissionContext,
    update: PermissionUpdate,
) -> ToolPermissionContext:
    """Apply a single permission update to the context, returning a new context."""
    ctx = copy.deepcopy(context)

    if isinstance(update, SetModeUpdate):
        logger.debug("Setting mode to '%s'", update.mode.value)
        ctx.mode = update.mode
        return ctx

    if isinstance(update, AddRulesUpdate):
        rule_strings = [permission_rule_value_to_string(r) for r in update.rules]
        logger.debug(
            "Adding %d %s rule(s) to '%s': %s",
            len(update.rules),
            update.behavior.value,
            update.destination.value,
            rule_strings,
        )
        rule_kind = _rule_kind_for_behavior(update.behavior)
        rules_map = getattr(ctx, rule_kind)
        existing = list(rules_map.get(update.destination, []))
        existing.extend(rule_strings)
        rules_map[update.destination] = existing
        return ctx

    if isinstance(update, ReplaceRulesUpdate):
        rule_strings = [permission_rule_value_to_string(r) for r in update.rules]
        logger.debug(
            "Replacing all %s rules for '%s' with %d rule(s)",
            update.behavior.value,
            update.destination.value,
            len(update.rules),
        )
        rule_kind = _rule_kind_for_behavior(update.behavior)
        getattr(ctx, rule_kind)[update.destination] = rule_strings
        return ctx

    if isinstance(update, RemoveRulesUpdate):
        rule_strings = [permission_rule_value_to_string(r) for r in update.rules]
        logger.debug(
            "Removing %d %s rule(s) from '%s'",
            len(update.rules),
            update.behavior.value,
            update.destination.value,
        )
        rule_kind = _rule_kind_for_behavior(update.behavior)
        existing = getattr(ctx, rule_kind).get(update.destination, [])
        to_remove = set(rule_strings)
        getattr(ctx, rule_kind)[update.destination] = [
            r for r in existing if r not in to_remove
        ]
        return ctx

    if isinstance(update, AddDirectoriesUpdate):
        logger.debug(
            "Adding %d directories to '%s'",
            len(update.directories),
            update.destination.value,
        )
        for directory in update.directories:
            from open_claude.schemas.permissions import AdditionalWorkingDirectory

            ctx.additional_working_directories[directory] = AdditionalWorkingDirectory(
                path=directory,
                source=update.destination,
            )
        return ctx

    if isinstance(update, RemoveDirectoriesUpdate):
        logger.debug(
            "Removing %d directories",
            len(update.directories),
        )
        for directory in update.directories:
            ctx.additional_working_directories.pop(directory, None)
        return ctx

    return ctx


def apply_permission_updates(
    context: ToolPermissionContext,
    updates: list[PermissionUpdate],
) -> ToolPermissionContext:
    """Apply multiple permission updates sequentially."""
    result = context
    for update in updates:
        result = apply_permission_update(result, update)
    return result


def supports_persistence(
    destination: PermissionUpdateDestination,
) -> bool:
    """Check if a destination supports persistence to disk."""
    return destination in (
        PermissionUpdateDestination.LOCAL_SETTINGS,
        PermissionUpdateDestination.USER_SETTINGS,
        PermissionUpdateDestination.PROJECT_SETTINGS,
    )


# ============================================================================
# Settings file I/O for persistence
# ============================================================================


def _get_settings_path(destination: PermissionUpdateDestination) -> Path | None:
    """Resolve the settings file path for a destination."""
    from pathlib import Path

    if destination == PermissionUpdateDestination.USER_SETTINGS:
        p = Path.home() / ".claude" / "settings.json"
        return p if p.is_file() else None
    if destination in (
        PermissionUpdateDestination.PROJECT_SETTINGS,
        PermissionUpdateDestination.LOCAL_SETTINGS,
    ):
        name = (
            "settings.json"
            if destination == PermissionUpdateDestination.PROJECT_SETTINGS
            else "settings.local.json"
        )
        p = Path.cwd() / ".claude" / name
        return p if p.is_file() else None
    return None


def _load_settings_json(path: Path) -> dict[str, Any]:
    """Load a settings JSON file, returning {} on error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_settings_json(path: Path, data: dict[str, Any]) -> bool:
    """Save a settings JSON file atomically."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return True
    except OSError as e:
        logger.error("Failed to save settings to %s: %s", path, e)
        return False


def persist_permission_update(update: PermissionUpdate) -> bool:
    """Persist a single permission update to the appropriate settings file.

    Returns True if any update was actually persisted to disk.
    """
    if not supports_persistence(update.destination):
        return False

    path = _get_settings_path(update.destination)
    if path is None:
        # Create the file if it doesn't exist for writes
        if isinstance(update, (SetModeUpdate,)):
            return False
        # For rule additions, create the file
        path = _ensure_settings_path(update.destination)
        if path is None:
            return False

    data = _load_settings_json(path)
    permissions = data.setdefault("permissions", {})

    if isinstance(update, AddRulesUpdate):
        rule_strings = [permission_rule_value_to_string(r) for r in update.rules]
        existing = permissions.get(update.behavior.value, [])
        existing_set = {
            permission_rule_value_to_string(permission_rule_value_from_string(r))
            for r in existing
        }
        new_rules = [r for r in rule_strings if r not in existing_set]
        if new_rules:
            permissions[update.behavior.value] = existing + new_rules
            return _save_settings_json(path, data)
        return True

    if isinstance(update, ReplaceRulesUpdate):
        rule_strings = [permission_rule_value_to_string(r) for r in update.rules]
        permissions[update.behavior.value] = rule_strings
        return _save_settings_json(path, data)

    if isinstance(update, RemoveRulesUpdate):
        existing = permissions.get(update.behavior.value, [])
        to_remove = {
            permission_rule_value_to_string(permission_rule_value_from_string(r))
            for r in update.rules
        }
        filtered = [
            r
            for r in existing
            if permission_rule_value_to_string(permission_rule_value_from_string(r))
            not in to_remove
        ]
        permissions[update.behavior.value] = filtered
        return _save_settings_json(path, data)

    if isinstance(update, SetModeUpdate):
        permissions["defaultMode"] = update.mode.value
        return _save_settings_json(path, data)

    if isinstance(update, AddDirectoriesUpdate):
        existing_dirs = permissions.get("additionalDirectories", [])
        dirs_to_add = [d for d in update.directories if d not in existing_dirs]
        if dirs_to_add:
            permissions["additionalDirectories"] = existing_dirs + dirs_to_add
            return _save_settings_json(path, data)
        return True

    if isinstance(update, RemoveDirectoriesUpdate):
        existing_dirs = permissions.get("additionalDirectories", [])
        to_remove = set(update.directories)
        filtered = [d for d in existing_dirs if d not in to_remove]
        permissions["additionalDirectories"] = filtered
        return _save_settings_json(path, data)

    return False


def persist_permission_updates(updates: list[PermissionUpdate]) -> bool:
    """Persist multiple permission updates. Returns True if any were persisted."""
    any_persisted = False
    for update in updates:
        if persist_permission_update(update):
            any_persisted = True
    return any_persisted


def _ensure_settings_path(destination: PermissionUpdateDestination) -> Path | None:
    """Get or create the path for a settings file."""
    if destination == PermissionUpdateDestination.USER_SETTINGS:
        return Path.home() / ".claude" / "settings.json"
    if destination in (
        PermissionUpdateDestination.PROJECT_SETTINGS,
        PermissionUpdateDestination.LOCAL_SETTINGS,
    ):
        name = (
            "settings.json"
            if destination == PermissionUpdateDestination.PROJECT_SETTINGS
            else "settings.local.json"
        )
        return Path.cwd() / ".claude" / name
    return None


def create_read_rule_suggestion(
    dir_path: str,
    destination: PermissionUpdateDestination = PermissionUpdateDestination.SESSION,
) -> PermissionUpdate | None:
    """Create a Read rule suggestion for a directory.

    Returns None for the root directory (too broad).
    """
    from pathlib import PurePosixPath

    posix_path = PurePosixPath(dir_path).as_posix()
    if posix_path == "/":
        return None

    is_abs = posix_path.startswith("/")
    rule_content = f"/{posix_path}/**" if is_abs else f"{posix_path}/**"

    return AddRulesUpdate(
        destination=destination,
        rules=[PermissionRuleValue(tool_name="Read", rule_content=rule_content)],
        behavior=PermissionBehavior.ALLOW,
    )
