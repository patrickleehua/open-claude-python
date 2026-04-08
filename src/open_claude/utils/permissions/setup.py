"""Permission context initialization and mode transitions.

Ported from Claude-Code-rev src/utils/permissions/permissionSetup.ts.
"""

from __future__ import annotations

import logging
from typing import Any

from open_claude.schemas.permissions import (
    PermissionBehavior,
    PermissionMode,
    PermissionRuleSource,
    ToolPermissionContext,
    ToolPermissionRulesBySource,
)
from open_claude.utils.permissions.loader import (
    load_all_permission_rules_from_disk,
    should_allow_managed_permission_rules_only,
)
from open_claude.utils.permissions.update import apply_permission_update, apply_permission_updates

logger = logging.getLogger(__name__)

# Dangerous Bash permission patterns that should be stripped in auto mode
DANGEROUS_BASH_PATTERNS = {"Bash(*)", "Bash(python:*)", "Bash(python3:*)", "Bash(sh:*)", "Bash(bash:*)"}

DANGEROUS_AGENT_PATTERNS = {"Agent(*)", "Agent(Explore:*)", "Agent(general-purpose:*)"}


def is_dangerous_bash_permission(rule_string: str) -> bool:
    """Check if a Bash permission rule is overly broad."""
    return rule_string in DANGEROUS_BASH_PATTERNS or rule_string == "Bash"


def is_dangerous_agent_permission(rule_string: str) -> bool:
    """Check if an Agent permission rule is overly broad."""
    return rule_string in DANGEROUS_AGENT_PATTERNS or rule_string == "Agent"


def initialize_tool_permission_context(
    mode: PermissionMode = PermissionMode.DEFAULT,
    allowed_tools: list[str] | None = None,
    disallowed_tools: list[str] | None = None,
    additional_directories: list[str] | None = None,
    cli_permission_mode: PermissionMode | None = None,
) -> ToolPermissionContext:
    """Initialize the tool permission context.

    Loads rules from all settings sources, applies CLI overrides,
    and detects dangerous permissions for auto mode stripping.

    Args:
        mode: The initial permission mode.
        allowed_tools: Tools to auto-allow from CLI args.
        disallowed_tools: Tools to auto-deny from CLI args.
        additional_directories: Additional directories in scope.
        cli_permission_mode: Permission mode override from CLI flag.
    """
    from open_claude.schemas.permissions import (
        AddDirectoriesUpdate,
        AddRulesUpdate,
        PermissionRuleValue,
        PermissionUpdateDestination,
    )
    from open_claude.utils.permissions.rule_parser import permission_rule_value_from_string

    effective_mode = cli_permission_mode or mode

    # Start with empty rules
    allow_rules: ToolPermissionRulesBySource = {}
    deny_rules: ToolPermissionRulesBySource = {}
    ask_rules: ToolPermissionRulesBySource = {}

    ctx = ToolPermissionContext(
        mode=effective_mode,
        always_allow_rules=allow_rules,
        always_deny_rules=deny_rules,
        always_ask_rules=ask_rules,
    )

    # Load rules from disk
    all_rules = load_all_permission_rules_from_disk()
    for rule in all_rules:
        from open_claude.utils.permissions.rule_parser import permission_rule_value_to_string

        rule_str = permission_rule_value_to_string(rule.rule_value)
        rule_kind = {
            PermissionBehavior.ALLOW: "always_allow_rules",
            PermissionBehavior.DENY: "always_deny_rules",
            PermissionBehavior.ASK: "always_ask_rules",
        }[rule.rule_behavior]
        rules_map = getattr(ctx, rule_kind)
        if rule.source not in rules_map:
            rules_map[rule.source] = []
        rules_map[rule.source].append(rule_str)

    # Apply CLI-arg allowed tools
    if allowed_tools:
        cli_rules = [permission_rule_value_from_string(t) for t in allowed_tools]
        ctx = apply_permission_update(
            ctx,
            AddRulesUpdate(
                destination=PermissionUpdateDestination.CLI_ARG,
                rules=cli_rules,
                behavior=PermissionBehavior.ALLOW,
            ),
        )

    # Apply CLI-arg disallowed tools
    if disallowed_tools:
        cli_rules = [permission_rule_value_from_string(t) for t in disallowed_tools]
        ctx = apply_permission_update(
            ctx,
            AddRulesUpdate(
                destination=PermissionUpdateDestination.CLI_ARG,
                rules=cli_rules,
                behavior=PermissionBehavior.DENY,
            ),
        )

    # Apply additional directories
    if additional_directories:
        ctx = apply_permission_update(
            ctx,
            AddDirectoriesUpdate(
                destination=PermissionUpdateDestination.CLI_ARG,
                directories=additional_directories,
            ),
        )

    # If entering auto mode, strip dangerous permissions
    if effective_mode == PermissionMode.AUTO:
        ctx = _strip_dangerous_permissions(ctx)

    return ctx


def transition_permission_mode(
    context: ToolPermissionContext,
    new_mode: PermissionMode,
) -> ToolPermissionContext:
    """Transition to a new permission mode.

    Strips dangerous permissions when entering auto mode.
    Restores them when leaving auto mode.
    """
    if new_mode == PermissionMode.AUTO and context.mode != PermissionMode.AUTO:
        return _strip_dangerous_permissions(context)

    if new_mode != PermissionMode.AUTO and context.mode == PermissionMode.AUTO:
        ctx = _restore_dangerous_permissions(context)
        ctx.mode = new_mode
        return ctx

    context.mode = new_mode
    return context


def _strip_dangerous_permissions(
    context: ToolPermissionContext,
) -> ToolPermissionContext:
    """Strip dangerous permissions for auto mode."""
    from copy import deepcopy

    ctx = deepcopy(context)
    ctx.mode = PermissionMode.AUTO

    stripped: ToolPermissionRulesBySource = {}
    all_dangerous = DANGEROUS_BASH_PATTERNS | DANGEROUS_AGENT_PATTERNS

    for source in list(ctx.always_allow_rules.keys()):
        rules = ctx.always_allow_rules.get(source, [])
        safe_rules = [r for r in rules if r not in all_dangerous]
        dangerous_rules = [r for r in rules if r in all_dangerous]

        if dangerous_rules:
            stripped[source] = dangerous_rules
            ctx.always_allow_rules[source] = safe_rules

    ctx.stripped_dangerous_rules = stripped or None
    return ctx


def _restore_dangerous_permissions(
    context: ToolPermissionContext,
) -> ToolPermissionContext:
    """Restore previously stripped dangerous permissions."""
    from copy import deepcopy

    ctx = deepcopy(context)
    ctx.mode = context.pre_plan_mode or PermissionMode.DEFAULT

    if ctx.stripped_dangerous_rules:
        for source, rules in ctx.stripped_dangerous_rules.items():
            existing = ctx.always_allow_rules.get(source, [])
            ctx.always_allow_rules[source] = existing + rules
    ctx.stripped_dangerous_rules = None
    return ctx
