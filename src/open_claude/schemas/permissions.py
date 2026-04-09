"""Permission type definitions for the tool permission system.

Ported from Claude-Code-rev src/types/permissions.ts.
Pure type definitions with no runtime dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Union


# ============================================================================
# Permission Modes
# ============================================================================


class PermissionMode(str, Enum):
    """Permission mode controlling how tool access is decided."""

    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    BYPASS_PERMISSIONS = "bypassPermissions"
    DONT_ASK = "dontAsk"
    PLAN = "plan"
    AUTO = "auto"
    BUBBLE = "bubble"


# ============================================================================
# Permission Behaviors
# ============================================================================


class PermissionBehavior(str, Enum):
    """Outcome of a permission check."""

    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


# ============================================================================
# Permission Rules
# ============================================================================


class PermissionRuleSource(str, Enum):
    """Where a permission rule originated from."""

    USER_SETTINGS = "userSettings"
    PROJECT_SETTINGS = "projectSettings"
    LOCAL_SETTINGS = "localSettings"
    FLAG_SETTINGS = "flagSettings"
    POLICY_SETTINGS = "policySettings"
    CLI_ARG = "cliArg"
    COMMAND = "command"
    SESSION = "session"


class PermissionUpdateDestination(str, Enum):
    """Where a permission update should be persisted."""

    USER_SETTINGS = "userSettings"
    PROJECT_SETTINGS = "projectSettings"
    LOCAL_SETTINGS = "localSettings"
    SESSION = "session"
    CLI_ARG = "cliArg"


# ============================================================================
# Rule Value & Rule
# ============================================================================


@dataclass(frozen=True)
class PermissionRuleValue:
    """Specifies which tool and optional content for a rule."""

    tool_name: str
    rule_content: str | None = None


@dataclass(frozen=True)
class PermissionRule:
    """A permission rule with its source and behavior."""

    source: PermissionRuleSource
    rule_behavior: PermissionBehavior
    rule_value: PermissionRuleValue


# ============================================================================
# Additional Working Directory
# ============================================================================


@dataclass(frozen=True)
class AdditionalWorkingDirectory:
    """An additional directory included in permission scope."""

    path: str
    source: PermissionRuleSource


# ============================================================================
# Permission Updates (discriminated union via dataclasses)
# ============================================================================


@dataclass(frozen=True)
class AddRulesUpdate:
    type: Literal["addRules"] = field(default="addRules", init=False)
    destination: PermissionUpdateDestination = PermissionUpdateDestination.SESSION
    rules: list[PermissionRuleValue] = field(default_factory=list)
    behavior: PermissionBehavior = PermissionBehavior.ALLOW


@dataclass(frozen=True)
class ReplaceRulesUpdate:
    type: Literal["replaceRules"] = field(default="replaceRules", init=False)
    destination: PermissionUpdateDestination = PermissionUpdateDestination.SESSION
    rules: list[PermissionRuleValue] = field(default_factory=list)
    behavior: PermissionBehavior = PermissionBehavior.ALLOW


@dataclass(frozen=True)
class RemoveRulesUpdate:
    type: Literal["removeRules"] = field(default="removeRules", init=False)
    destination: PermissionUpdateDestination = PermissionUpdateDestination.SESSION
    rules: list[PermissionRuleValue] = field(default_factory=list)
    behavior: PermissionBehavior = PermissionBehavior.ALLOW


@dataclass(frozen=True)
class SetModeUpdate:
    type: Literal["setMode"] = field(default="setMode", init=False)
    destination: PermissionUpdateDestination = PermissionUpdateDestination.SESSION
    mode: PermissionMode = PermissionMode.DEFAULT


@dataclass(frozen=True)
class AddDirectoriesUpdate:
    type: Literal["addDirectories"] = field(default="addDirectories", init=False)
    destination: PermissionUpdateDestination = PermissionUpdateDestination.SESSION
    directories: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RemoveDirectoriesUpdate:
    type: Literal["removeDirectories"] = field(default="removeDirectories", init=False)
    destination: PermissionUpdateDestination = PermissionUpdateDestination.SESSION
    directories: list[str] = field(default_factory=list)


PermissionUpdate = Union[
    AddRulesUpdate,
    ReplaceRulesUpdate,
    RemoveRulesUpdate,
    SetModeUpdate,
    AddDirectoriesUpdate,
    RemoveDirectoriesUpdate,
]


# ============================================================================
# Permission Decision Reasons
# ============================================================================


@dataclass(frozen=True)
class RuleDecisionReason:
    type: Literal["rule"] = field(default="rule", init=False)
    rule: PermissionRule = field(default=None)  # type: ignore


@dataclass(frozen=True)
class ModeDecisionReason:
    type: Literal["mode"] = field(default="mode", init=False)
    mode: PermissionMode = field(default=None)  # type: ignore


@dataclass
class SubcommandResultsDecisionReason:
    type: Literal["subcommandResults"] = field(default="subcommandResults", init=False)
    reasons: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookDecisionReason:
    type: Literal["hook"] = field(default="hook", init=False)
    hook_name: str = ""
    hook_source: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class AsyncAgentDecisionReason:
    type: Literal["asyncAgent"] = field(default="asyncAgent", init=False)
    reason: str = ""


@dataclass(frozen=True)
class SandboxOverrideDecisionReason:
    type: Literal["sandboxOverride"] = field(default="sandboxOverride", init=False)
    reason: str = ""


@dataclass(frozen=True)
class ClassifierDecisionReason:
    type: Literal["classifier"] = field(default="classifier", init=False)
    classifier: str = ""
    reason: str = ""


@dataclass(frozen=True)
class WorkingDirDecisionReason:
    type: Literal["workingDir"] = field(default="workingDir", init=False)
    reason: str = ""


@dataclass(frozen=True)
class SafetyCheckDecisionReason:
    type: Literal["safetyCheck"] = field(default="safetyCheck", init=False)
    reason: str = ""
    classifier_approvable: bool = False


@dataclass(frozen=True)
class OtherDecisionReason:
    type: Literal["other"] = field(default="other", init=False)
    reason: str = ""


PermissionDecisionReason = Union[
    RuleDecisionReason,
    ModeDecisionReason,
    SubcommandResultsDecisionReason,
    HookDecisionReason,
    AsyncAgentDecisionReason,
    SandboxOverrideDecisionReason,
    ClassifierDecisionReason,
    WorkingDirDecisionReason,
    SafetyCheckDecisionReason,
    OtherDecisionReason,
]


# ============================================================================
# Permission Decisions
# ============================================================================


@dataclass
class PermissionAllowDecision:
    behavior: Literal["allow"] = field(default="allow", init=False)
    updated_input: dict[str, Any] | None = None
    user_modified: bool = False
    decision_reason: PermissionDecisionReason | None = None
    tool_use_id: str | None = None
    accept_feedback: str | None = None
    display_data: dict[str, Any] | None = None


@dataclass
class PendingClassifierCheck:
    """Metadata for a pending classifier check that will run asynchronously."""

    command: str = ""
    cwd: str = ""
    descriptions: list[str] = field(default_factory=list)


@dataclass
class PermissionAskDecision:
    behavior: Literal["ask"] = field(default="ask", init=False)
    message: str = ""
    updated_input: dict[str, Any] | None = None
    decision_reason: PermissionDecisionReason | None = None
    suggestions: list[PermissionUpdate] | None = None
    blocked_path: str | None = None
    pending_classifier_check: PendingClassifierCheck | None = None
    display_data: dict[str, Any] | None = None


@dataclass
class PermissionDenyDecision:
    behavior: Literal["deny"] = field(default="deny", init=False)
    message: str = ""
    decision_reason: PermissionDecisionReason | None = None
    tool_use_id: str | None = None
    display_data: dict[str, Any] | None = None


@dataclass
class PassthroughResult:
    behavior: Literal["passthrough"] = field(default="passthrough", init=False)
    message: str = ""
    decision_reason: PermissionDecisionReason | None = None
    suggestions: list[PermissionUpdate] | None = None
    blocked_path: str | None = None
    pending_classifier_check: PendingClassifierCheck | None = None


PermissionDecision = Union[PermissionAllowDecision, PermissionAskDecision, PermissionDenyDecision]
PermissionResult = Union[PermissionDecision, PassthroughResult]


# ============================================================================
# Classifier Types
# ============================================================================


@dataclass
class ClassifierUsage:
    """Token usage from a classifier API call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class YoloClassifierResult:
    """Result from the YOLO/auto-mode security classifier."""

    thinking: str | None = None
    should_block: bool = False
    reason: str = ""
    unavailable: bool = False
    transcript_too_long: bool = False
    model: str = ""
    usage: ClassifierUsage | None = None
    duration_ms: float | None = None
    prompt_lengths: dict[str, int] | None = None
    error_dump_path: str | None = None
    stage: str | None = None


# ============================================================================
# Risk Level & Explanation
# ============================================================================


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


@dataclass
class PermissionExplanation:
    risk_level: RiskLevel = RiskLevel.LOW
    explanation: str = ""
    reasoning: str = ""
    risk: str = ""


# ============================================================================
# Tool Permission Context
# ============================================================================

ToolPermissionRulesBySource = dict[PermissionRuleSource, list[str]]


@dataclass
class ToolPermissionContext:
    """Full permission context carried through the permission pipeline."""

    mode: PermissionMode = PermissionMode.DEFAULT
    additional_working_directories: dict[str, AdditionalWorkingDirectory] = field(
        default_factory=dict
    )
    always_allow_rules: ToolPermissionRulesBySource = field(default_factory=dict)
    always_deny_rules: ToolPermissionRulesBySource = field(default_factory=dict)
    always_ask_rules: ToolPermissionRulesBySource = field(default_factory=dict)
    is_bypass_permissions_mode_available: bool = False
    stripped_dangerous_rules: ToolPermissionRulesBySource | None = None
    should_avoid_permission_prompts: bool = False
    await_automated_checks_before_dialog: bool = False
    pre_plan_mode: PermissionMode | None = None
