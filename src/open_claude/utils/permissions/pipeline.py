"""Main permission pipeline — orchestrates tool permission decisions.

Ported from Claude-Code-rev src/utils/permissions/permissions.ts.

Permission flow:
    Tool Execution Request
      |
      +-- [1a] Deny Rules
      +-- [1b] Ask Rules
      +-- [1c] Tool-specific checkPermissions()
      +-- [1d] Tool implementation denial
      +-- [1e] requiresUserInteraction tools
      +-- [1f] Content-specific ask rules
      +-- [1g] Safety checks (bypass-immune)
      +-- [2a] Mode bypass
      +-- [2b] Always-allow rules
      +-- [3]  Convert passthrough -> ask
      +-- [Mode transforms: dontAsk/auto/headless]
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from open_claude.schemas.permissions import (
    ModeDecisionReason,
    OtherDecisionReason,
    PassthroughResult,
    PermissionAllowDecision,
    PermissionAskDecision,
    PermissionBehavior,
    PermissionDenyDecision,
    PermissionDecision,
    PermissionDecisionReason,
    PermissionMode,
    PermissionResult,
    PermissionRule,
    PermissionRuleSource,
    RuleDecisionReason,
    ToolPermissionContext,
    ToolPermissionRulesBySource,
)
from open_claude.utils.permissions.auto_mode_state import is_auto_mode_active
from open_claude.utils.permissions.classifier_decision import is_auto_mode_allowlisted_tool
from open_claude.utils.permissions.denial_tracking import (
    DenialTrackingState,
    create_denial_tracking_state,
    record_denial,
    record_success,
    should_fallback_to_prompting,
)
from open_claude.utils.permissions.rule_parser import (
    permission_rule_value_from_string,
    permission_rule_value_to_string,
)
from open_claude.utils.permissions.update import apply_permission_update

logger = logging.getLogger(__name__)

PERMISSION_RULE_SOURCES: list[PermissionRuleSource] = [
    PermissionRuleSource.POLICY_SETTINGS,
    PermissionRuleSource.FLAG_SETTINGS,
    PermissionRuleSource.USER_SETTINGS,
    PermissionRuleSource.PROJECT_SETTINGS,
    PermissionRuleSource.LOCAL_SETTINGS,
    PermissionRuleSource.CLI_ARG,
    PermissionRuleSource.COMMAND,
    PermissionRuleSource.SESSION,
]


# ============================================================================
# Rule retrieval helpers
# ============================================================================


def _get_rules_by_behavior(
    context: ToolPermissionContext,
    behavior: PermissionBehavior,
) -> list[PermissionRule]:
    """Get all rules for a given behavior, flattened from all sources."""
    rules_map: ToolPermissionRulesBySource = {
        PermissionBehavior.ALLOW: context.always_allow_rules,
        PermissionBehavior.DENY: context.always_deny_rules,
        PermissionBehavior.ASK: context.always_ask_rules,
    }[behavior]
    result: list[PermissionRule] = []
    for source in PERMISSION_RULE_SOURCES:
        for rule_string in rules_map.get(source, []):
            result.append(
                PermissionRule(
                    source=source,
                    rule_behavior=behavior,
                    rule_value=permission_rule_value_from_string(rule_string),
                )
            )
    return result


def get_allow_rules(context: ToolPermissionContext) -> list[PermissionRule]:
    return _get_rules_by_behavior(context, PermissionBehavior.ALLOW)


def get_deny_rules(context: ToolPermissionContext) -> list[PermissionRule]:
    return _get_rules_by_behavior(context, PermissionBehavior.DENY)


def get_ask_rules(context: ToolPermissionContext) -> list[PermissionRule]:
    return _get_rules_by_behavior(context, PermissionBehavior.ASK)


def _tool_matches_rule(tool_name: str, rule: PermissionRule) -> bool:
    """Check if a tool matches a whole-tool rule (no content)."""
    if rule.rule_value.rule_content is not None:
        return False
    return rule.rule_value.tool_name == tool_name


def tool_always_allowed_rule(
    context: ToolPermissionContext,
    tool_name: str,
) -> PermissionRule | None:
    """Check if a tool is listed in the always-allow rules."""
    for rule in get_allow_rules(context):
        if _tool_matches_rule(tool_name, rule):
            return rule
    return None


def get_deny_rule_for_tool(
    context: ToolPermissionContext,
    tool_name: str,
) -> PermissionRule | None:
    """Check if a tool is listed in the always-deny rules."""
    for rule in get_deny_rules(context):
        if _tool_matches_rule(tool_name, rule):
            return rule
    return None


def get_ask_rule_for_tool(
    context: ToolPermissionContext,
    tool_name: str,
) -> PermissionRule | None:
    """Check if a tool is listed in the always-ask rules."""
    for rule in get_ask_rules(context):
        if _tool_matches_rule(tool_name, rule):
            return rule
    return None


# ============================================================================
# Message helpers
# ============================================================================


def create_permission_request_message(
    tool_name: str,
    decision_reason: PermissionDecisionReason | None = None,
) -> str:
    """Create a human-readable permission request message."""
    if decision_reason is not None:
        if decision_reason.type == "rule":
            rule_str = permission_rule_value_to_string(decision_reason.rule.rule_value)
            return f"Permission rule '{rule_str}' requires approval for this {tool_name} command"
        if decision_reason.type == "mode":
            return f"Current permission mode requires approval for this {tool_name} command"
        if decision_reason.type == "hook":
            return f"Hook '{decision_reason.hook_name}' requires approval for this {tool_name} command"
        if decision_reason.type == "classifier":
            return f"Classifier '{decision_reason.classifier}' requires approval for this {tool_name} command: {decision_reason.reason}"
        if decision_reason.type in ("safetyCheck", "other"):
            return decision_reason.reason
        if decision_reason.type == "workingDir":
            return decision_reason.reason
        if decision_reason.type == "asyncAgent":
            return decision_reason.reason

    return f"Claude requested permissions to use {tool_name}, but you haven't granted it yet."


# ============================================================================
# Main pipeline
# ============================================================================


async def check_rule_based_permissions(
    tool_name: str,
    input_data: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionAskDecision | PermissionDenyDecision | None:
    """Check only the rule-based steps (1a, 1b).

    This is the subset that bypassPermissions mode respects.
    """
    # 1a. Entire tool is denied by rule
    deny_rule = get_deny_rule_for_tool(context, tool_name)
    if deny_rule:
        return PermissionDenyDecision(
            message=f"Permission to use {tool_name} has been denied.",
            decision_reason=RuleDecisionReason(rule=deny_rule),
        )

    # 1b. Entire tool has an ask rule
    ask_rule = get_ask_rule_for_tool(context, tool_name)
    if ask_rule:
        return PermissionAskDecision(
            message=create_permission_request_message(tool_name),
            decision_reason=RuleDecisionReason(rule=ask_rule),
        )

    return None


def _get_updated_input_or_fallback(
    permission_result: PermissionResult | None,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    """Extract updated_input from a permission result, falling back."""
    if permission_result and hasattr(permission_result, "updated_input"):
        return permission_result.updated_input or fallback  # type: ignore
    return fallback


async def has_permissions_to_use_tool(
    tool_name: str,
    input_data: dict[str, Any],
    context: ToolPermissionContext,
    *,
    denial_state: DenialTrackingState | None = None,
    tool_is_read_only: bool = False,
    tool_requires_user_interaction: bool = False,
    check_permissions: Callable[
        [str, dict[str, Any], ToolPermissionContext],
        Awaitable[PermissionResult],
    ]
    | None = None,
) -> PermissionDecision:
    """Main entry point for the permission pipeline.

    Args:
        tool_name: Name of the tool being checked.
        input_data: The tool input dict.
        context: Current permission context.
        denial_state: Optional denial tracking state.
        tool_is_read_only: Whether the tool is read-only.
        tool_requires_user_interaction: Whether the tool requires user interaction.
        check_permissions: Optional async callable for tool-specific checks.

    Returns:
        PermissionDecision: allow, ask, or deny.
    """
    # ---- Step 1: Pre-bypass checks ----

    # 1a. Entire tool is denied by rule
    deny_rule = get_deny_rule_for_tool(context, tool_name)
    if deny_rule:
        return PermissionDenyDecision(
            message=f"Permission to use {tool_name} has been denied.",
            decision_reason=RuleDecisionReason(rule=deny_rule),
        )

    # 1b. Entire tool has an ask rule
    ask_rule = get_ask_rule_for_tool(context, tool_name)
    if ask_rule:
        return PermissionAskDecision(
            message=create_permission_request_message(tool_name),
            decision_reason=RuleDecisionReason(rule=ask_rule),
        )

    # 1c. Tool-specific permission check
    tool_permission_result: PermissionResult = PassthroughResult(
        message=create_permission_request_message(tool_name),
    )
    if check_permissions is not None:
        try:
            tool_permission_result = await check_permissions(tool_name, input_data, context)
        except Exception as e:
            logger.error("Tool permission check failed: %s", e)

    # 1d. Tool implementation denied permission
    if tool_permission_result.behavior == "deny":
        return tool_permission_result  # type: ignore

    # 1e. Tool requires user interaction even in bypass mode
    if tool_requires_user_interaction and tool_permission_result.behavior == "ask":
        return tool_permission_result  # type: ignore

    # 1f. Content-specific ask rules from tool.checkPermissions
    if (
        tool_permission_result.behavior == "ask"
        and hasattr(tool_permission_result, "decision_reason")
        and tool_permission_result.decision_reason is not None
        and tool_permission_result.decision_reason.type == "rule"
        and tool_permission_result.decision_reason.rule.rule_behavior == PermissionBehavior.ASK
    ):
        return tool_permission_result  # type: ignore

    # 1g. Safety checks are bypass-immune
    if (
        tool_permission_result.behavior == "ask"
        and hasattr(tool_permission_result, "decision_reason")
        and tool_permission_result.decision_reason is not None
        and tool_permission_result.decision_reason.type == "safetyCheck"
    ):
        return tool_permission_result  # type: ignore

    # ---- Step 2: Bypass / Allow checks ----

    # 2a. Check if mode allows bypassing permissions
    should_bypass = (
        context.mode == PermissionMode.BYPASS_PERMISSIONS
        or (
            context.mode == PermissionMode.PLAN
            and context.is_bypass_permissions_mode_available
        )
    )
    if should_bypass:
        return PermissionAllowDecision(
            updated_input=_get_updated_input_or_fallback(tool_permission_result, input_data),
            decision_reason=ModeDecisionReason(mode=context.mode),
        )

    # 2b. Entire tool is allowed by rule
    always_allowed = tool_always_allowed_rule(context, tool_name)
    if always_allowed:
        return PermissionAllowDecision(
            updated_input=_get_updated_input_or_fallback(tool_permission_result, input_data),
            decision_reason=RuleDecisionReason(rule=always_allowed),
        )

    # ---- Step 3: Convert passthrough to ask ----
    result: PermissionDecision
    if tool_permission_result.behavior == "passthrough":
        result = PermissionAskDecision(
            message=create_permission_request_message(
                tool_name,
                getattr(tool_permission_result, "decision_reason", None),
            ),
            suggestions=getattr(tool_permission_result, "suggestions", None),
        )
    else:
        result = tool_permission_result  # type: ignore

    if result.behavior == "allow":
        return result

    # ---- Step 4: Mode transformations ----

    if context.mode == PermissionMode.ACCEPT_EDITS and tool_name in {"Edit", "Write"}:
        return PermissionAllowDecision(
            updated_input=input_data,
            decision_reason=ModeDecisionReason(mode=PermissionMode.ACCEPT_EDITS),
        )

    # dontAsk mode: convert ask -> deny
    if context.mode == PermissionMode.DONT_ASK:
        return PermissionDenyDecision(
            message=f"Permission to use {tool_name} was denied (dontAsk mode).",
            decision_reason=ModeDecisionReason(mode=PermissionMode.DONT_ASK),
        )

    # Auto mode: fast-path safe tools
    if context.mode == PermissionMode.AUTO or (
        context.mode == PermissionMode.PLAN and is_auto_mode_active()
    ):
        if is_auto_mode_allowlisted_tool(tool_name):
            effective_denial = denial_state or create_denial_tracking_state()
            record_success(effective_denial)
            logger.debug("Skipping auto mode classifier for %s: tool is on the safe allowlist", tool_name)
            return PermissionAllowDecision(
                updated_input=input_data,
                decision_reason=ModeDecisionReason(mode=PermissionMode.AUTO),
            )

        # Denial limit fallback
        if denial_state and should_fallback_to_prompting(denial_state):
            logger.warning("Denial limit exceeded, falling back to prompting")
            return result

    # Headless / no interactive prompts: auto-deny
    if context.should_avoid_permission_prompts:
        return PermissionDenyDecision(
            message=f"Permission to use {tool_name} was denied (no interactive prompts available).",
            decision_reason=OtherDecisionReason(
                reason="Permission prompts are not available in this context"
            ),
        )

    return result


# ============================================================================
# Rule management helpers
# ============================================================================


def get_rule_source_display_string(source: PermissionRuleSource) -> str:
    """Get a human-readable display string for a rule source."""
    display_names = {
        PermissionRuleSource.POLICY_SETTINGS: "managed policy",
        PermissionRuleSource.FLAG_SETTINGS: "feature flags",
        PermissionRuleSource.USER_SETTINGS: "user settings",
        PermissionRuleSource.PROJECT_SETTINGS: "project settings",
        PermissionRuleSource.LOCAL_SETTINGS: "local settings",
        PermissionRuleSource.CLI_ARG: "command line",
        PermissionRuleSource.COMMAND: "command",
        PermissionRuleSource.SESSION: "session",
    }
    return display_names.get(source, source.value)


def apply_permission_rules_to_context(
    context: ToolPermissionContext,
    rules: list[PermissionRule],
) -> ToolPermissionContext:
    """Apply permission rules to context (additive — for initial setup)."""
    from open_claude.schemas.permissions import (
        AddRulesUpdate,
        PermissionRuleValue,
        PermissionUpdateDestination,
    )

    grouped: dict[str, list[PermissionRuleValue]] = {}
    for rule in rules:
        key = f"{rule.source.value}:{rule.rule_behavior.value}"
        grouped.setdefault(key, []).append(rule.rule_value)

    updates = []
    for key, rule_values in grouped.items():
        source_str, behavior_str = key.split(":")
        updates.append(
            AddRulesUpdate(
                destination=PermissionUpdateDestination(source_str),
                rules=rule_values,
                behavior=PermissionBehavior(behavior_str),
            )
        )

    from open_claude.utils.permissions.update import apply_permission_updates

    return apply_permission_updates(context, updates)


def sync_permission_rules_from_disk(
    context: ToolPermissionContext,
    rules: list[PermissionRule],
) -> ToolPermissionContext:
    """Sync permission rules from disk (replacement — for settings changes)."""
    from open_claude.schemas.permissions import (
        PermissionUpdateDestination,
        ReplaceRulesUpdate,
    )
    from open_claude.utils.permissions.update import apply_permission_updates

    ctx = context

    # Clear all disk-based sources
    disk_sources: list[PermissionUpdateDestination] = [
        PermissionUpdateDestination.USER_SETTINGS,
        PermissionUpdateDestination.PROJECT_SETTINGS,
        PermissionUpdateDestination.LOCAL_SETTINGS,
    ]
    for disk_source in disk_sources:
        for behavior in [PermissionBehavior.ALLOW, PermissionBehavior.DENY, PermissionBehavior.ASK]:
            ctx = apply_permission_update(
                ctx,
                ReplaceRulesUpdate(
                    destination=disk_source,
                    rules=[],
                    behavior=behavior,
                ),
            )

    # Group and apply new rules
    grouped: dict[str, list] = {}
    for rule in rules:
        key = f"{rule.source.value}:{rule.rule_behavior.value}"
        grouped.setdefault(key, []).append(rule.rule_value)

    updates = []
    for key, rule_values in grouped.items():
        source_str, behavior_str = key.split(":")
        updates.append(
            ReplaceRulesUpdate(
                destination=PermissionUpdateDestination(source_str),
                rules=rule_values,
                behavior=PermissionBehavior(behavior_str),
            )
        )

    return apply_permission_updates(ctx, updates)
