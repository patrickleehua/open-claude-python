"""Load permission rules from settings files.

Ported from Claude-Code-rev src/utils/permissions/permissionsLoader.ts.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from open_claude.schemas.permissions import (
    PermissionBehavior,
    PermissionRule,
    PermissionRuleSource,
    PermissionRuleValue,
)
from open_claude.utils.permissions.rule_parser import (
    permission_rule_value_from_string,
    permission_rule_value_to_string,
)
from open_claude.utils.permissions.update import (
    _ensure_settings_path,
    _load_settings_json,
    _save_settings_json,
)

logger = logging.getLogger(__name__)

SUPPORTED_RULE_BEHAVIORS = [PermissionBehavior.ALLOW, PermissionBehavior.DENY, PermissionBehavior.ASK]

EDITABLE_SOURCES = [
    PermissionRuleSource.USER_SETTINGS,
    PermissionRuleSource.PROJECT_SETTINGS,
    PermissionRuleSource.LOCAL_SETTINGS,
]


def should_allow_managed_permission_rules_only() -> bool:
    """Check if only managed permission rules should be used (enterprise policy)."""
    policy = _load_settings_for_source(PermissionRuleSource.POLICY_SETTINGS)
    return policy.get("allowManagedPermissionRulesOnly") is True if policy else False


def should_show_always_allow_options() -> bool:
    """Check if 'always allow' options should be shown in permission prompts."""
    return not should_allow_managed_permission_rules_only()


def _get_settings_path_for_source(source: PermissionRuleSource) -> Path | None:
    """Resolve settings file path for a source."""
    if source == PermissionRuleSource.USER_SETTINGS:
        p = Path.home() / ".claude" / "settings.json"
        return p if p.is_file() else None
    if source == PermissionRuleSource.PROJECT_SETTINGS:
        p = Path.cwd() / ".claude" / "settings.json"
        return p if p.is_file() else None
    if source == PermissionRuleSource.LOCAL_SETTINGS:
        p = Path.cwd() / ".claude" / "settings.local.json"
        return p if p.is_file() else None
    if source == PermissionRuleSource.POLICY_SETTINGS:
        p = Path.home() / ".claude" / ".settings.json"  # managed policy
        return p if p.is_file() else None
    return None


def _load_settings_for_source(source: PermissionRuleSource) -> dict[str, Any] | None:
    """Load raw settings JSON for a source."""
    path = _get_settings_path_for_source(source)
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _settings_json_to_rules(
    data: dict[str, Any] | None,
    source: PermissionRuleSource,
) -> list[PermissionRule]:
    """Convert permissions JSON to an array of PermissionRule objects."""
    if not data or "permissions" not in data:
        return []

    permissions = data["permissions"]
    rules: list[PermissionRule] = []
    for behavior in SUPPORTED_RULE_BEHAVIORS:
        behavior_array = permissions.get(behavior.value)
        if behavior_array:
            for rule_string in behavior_array:
                rules.append(
                    PermissionRule(
                        source=source,
                        rule_behavior=behavior,
                        rule_value=permission_rule_value_from_string(rule_string),
                    )
                )
    return rules


def _get_enabled_sources() -> list[PermissionRuleSource]:
    """Get all enabled setting sources in priority order."""
    return [
        PermissionRuleSource.POLICY_SETTINGS,
        PermissionRuleSource.FLAG_SETTINGS,
        PermissionRuleSource.USER_SETTINGS,
        PermissionRuleSource.PROJECT_SETTINGS,
        PermissionRuleSource.LOCAL_SETTINGS,
    ]


def load_all_permission_rules_from_disk() -> list[PermissionRule]:
    """Load all permission rules from all relevant settings sources."""
    if should_allow_managed_permission_rules_only():
        return get_permission_rules_for_source(PermissionRuleSource.POLICY_SETTINGS)

    rules: list[PermissionRule] = []
    for source in _get_enabled_sources():
        rules.extend(get_permission_rules_for_source(source))
    return rules


def get_permission_rules_for_source(
    source: PermissionRuleSource,
) -> list[PermissionRule]:
    """Load permission rules from a specific source."""
    data = _load_settings_for_source(source)
    return _settings_json_to_rules(data, source)


def delete_permission_rule_from_settings(rule: PermissionRule) -> bool:
    """Delete a rule from the appropriate settings file.

    Only works for editable sources (userSettings, projectSettings, localSettings).
    """
    if rule.source not in EDITABLE_SOURCES:
        return False

    rule_string = permission_rule_value_to_string(rule.rule_value)
    path = _get_settings_path_for_source(rule.source)
    if path is None:
        return False

    data = _load_settings_json(path)
    if not data or "permissions" not in data:
        return False

    permissions = data["permissions"]
    behavior_array = permissions.get(rule.rule_behavior.value)
    if not behavior_array:
        return False

    def normalize_entry(raw: str) -> str:
        return permission_rule_value_to_string(permission_rule_value_from_string(raw))

    if not any(normalize_entry(raw) == rule_string for raw in behavior_array):
        return False

    try:
        data["permissions"][rule.rule_behavior.value] = [
            raw for raw in behavior_array if normalize_entry(raw) != rule_string
        ]
        return _save_settings_json(path, data)
    except Exception as e:
        logger.error("Failed to delete permission rule: %s", e)
        return False


def add_permission_rules_to_settings(
    rule_values: list[PermissionRuleValue],
    rule_behavior: PermissionBehavior,
    source: PermissionRuleSource,
) -> bool:
    """Add rules to a settings file."""
    if should_allow_managed_permission_rules_only():
        return False

    if not rule_values:
        return True

    rule_strings = [permission_rule_value_to_string(r) for r in rule_values]

    path = _get_settings_path_for_source(source) or _ensure_settings_path(source)
    if path is None:
        return False

    data = _load_settings_json(path) or {}
    permissions = data.setdefault("permissions", {})
    existing_rules = permissions.get(rule_behavior.value, [])

    existing_set = {
        permission_rule_value_to_string(permission_rule_value_from_string(r))
        for r in existing_rules
    }
    new_rules = [r for r in rule_strings if r not in existing_set]

    if not new_rules:
        return True

    permissions[rule_behavior.value] = existing_rules + new_rules
    return _save_settings_json(path, data)
