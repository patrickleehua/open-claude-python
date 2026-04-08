"""Permission system for open-claude-python.

This package provides a multi-layered permission pipeline:
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

from open_claude.utils.permissions.auto_mode_state import (
    get_auto_mode_flag_cli,
    is_auto_mode_active,
    is_auto_mode_circuit_broken,
    set_auto_mode_active,
    set_auto_mode_circuit_broken,
    set_auto_mode_flag_cli,
)
from open_claude.utils.permissions.classifier_decision import (
    SAFE_YOLO_ALLOWLISTED_TOOLS,
    is_auto_mode_allowlisted_tool,
)
from open_claude.utils.permissions.denial_tracking import (
    DENIAL_LIMITS,
    DenialTrackingState,
    create_denial_tracking_state,
    record_denial,
    record_success,
    should_fallback_to_prompting,
)
from open_claude.utils.permissions.loader import (
    add_permission_rules_to_settings,
    delete_permission_rule_from_settings,
    get_permission_rules_for_source,
    load_all_permission_rules_from_disk,
    should_allow_managed_permission_rules_only,
    should_show_always_allow_options,
)
from open_claude.utils.permissions.pipeline import (
    check_rule_based_permissions,
    create_permission_request_message,
    get_allow_rules,
    get_ask_rule_for_tool,
    get_ask_rules,
    get_deny_rule_for_tool,
    get_deny_rules,
    get_rule_source_display_string,
    has_permissions_to_use_tool,
    sync_permission_rules_from_disk,
    tool_always_allowed_rule,
)
from open_claude.utils.permissions.result import get_rule_behavior_description
from open_claude.utils.permissions.rule_parser import (
    escape_rule_content,
    get_legacy_tool_names,
    normalize_legacy_tool_name,
    permission_rule_value_from_string,
    permission_rule_value_to_string,
    unescape_rule_content,
)
from open_claude.utils.permissions.setup import (
    initialize_tool_permission_context,
    is_dangerous_agent_permission,
    is_dangerous_bash_permission,
    transition_permission_mode,
)
from open_claude.utils.permissions.update import (
    apply_permission_update,
    apply_permission_updates,
    create_read_rule_suggestion,
    extract_rules,
    has_rules,
    persist_permission_update,
    persist_permission_updates,
    supports_persistence,
)

__all__ = [
    # Auto mode state
    "get_auto_mode_flag_cli",
    "is_auto_mode_active",
    "is_auto_mode_circuit_broken",
    "set_auto_mode_active",
    "set_auto_mode_circuit_broken",
    "set_auto_mode_flag_cli",
    # Classifier decision
    "SAFE_YOLO_ALLOWLISTED_TOOLS",
    "is_auto_mode_allowlisted_tool",
    # Denial tracking
    "DENIAL_LIMITS",
    "DenialTrackingState",
    "create_denial_tracking_state",
    "record_denial",
    "record_success",
    "should_fallback_to_prompting",
    # Loader
    "add_permission_rules_to_settings",
    "delete_permission_rule_from_settings",
    "get_permission_rules_for_source",
    "load_all_permission_rules_from_disk",
    "should_allow_managed_permission_rules_only",
    "should_show_always_allow_options",
    # Pipeline
    "check_rule_based_permissions",
    "create_permission_request_message",
    "get_allow_rules",
    "get_ask_rule_for_tool",
    "get_ask_rules",
    "get_deny_rule_for_tool",
    "get_deny_rules",
    "get_rule_source_display_string",
    "has_permissions_to_use_tool",
    "sync_permission_rules_from_disk",
    "tool_always_allowed_rule",
    # Result
    "get_rule_behavior_description",
    # Rule parser
    "escape_rule_content",
    "get_legacy_tool_names",
    "normalize_legacy_tool_name",
    "permission_rule_value_from_string",
    "permission_rule_value_to_string",
    "unescape_rule_content",
    # Setup
    "initialize_tool_permission_context",
    "is_dangerous_agent_permission",
    "is_dangerous_bash_permission",
    "transition_permission_mode",
    # Update
    "apply_permission_update",
    "apply_permission_updates",
    "create_read_rule_suggestion",
    "extract_rules",
    "has_rules",
    "persist_permission_update",
    "persist_permission_updates",
    "supports_persistence",
]
