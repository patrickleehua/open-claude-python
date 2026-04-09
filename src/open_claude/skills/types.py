"""Skill type definitions for the skills system.

Direct port of TypeScript BundledSkillDefinition and Command types from
Claude-Code-rev/src/skills/bundledSkills.ts and loadSkillsDir.ts.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


def is_feature_enabled(feature_name: str) -> bool:
    """Check if a feature flag is enabled via environment variable.

    Uses CLAUDE_CODE_FEATURE_{name} convention.
    """
    val = os.environ.get(f"CLAUDE_CODE_FEATURE_{feature_name}", "").lower()
    return val in ("1", "true", "yes")


def is_ant_user() -> bool:
    """Check if current user is internal (ant)."""
    return os.environ.get("CLAUDE_CODE_USER_TYPE", "") == "ant"


@dataclass
class BundledSkillDefinition:
    """Definition for a bundled skill that ships with the CLI.

    Direct port of TypeScript BundledSkillDefinition from bundledSkills.ts.
    """

    name: str
    description: str
    get_prompt_for_command: Callable[[str, Any], Awaitable[list[dict]]]
    aliases: list[str] = field(default_factory=list)
    when_to_use: str | None = None
    argument_hint: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    is_enabled: Callable[[], bool] = field(default=lambda: True)
    hooks: dict[str, Any] | None = None
    context: str | None = None  # 'inline' | 'fork'
    agent: str | None = None
    files: dict[str, str] | None = None


@dataclass
class SkillCommand:
    """Registered skill command.

    Stored in the SkillRegistry. The get_prompt_for_command callable
    generates the text content blocks that get injected into the conversation.
    """

    name: str
    description: str
    aliases: list[str] = field(default_factory=list)
    when_to_use: str | None = None
    argument_hint: str | None = None
    allowed_tools: list[str] = field(default_factory=list)
    model: str | None = None
    disable_model_invocation: bool = False
    user_invocable: bool = True
    is_enabled: Callable[[], bool] = field(default=lambda: True)
    hooks: dict[str, Any] | None = None
    context: str | None = None
    agent: str | None = None
    skill_root: str | None = None
    source: str = "bundled"
    loaded_from: str = "bundled"
    content_length: int = 0
    is_hidden: bool = False
    get_prompt_for_command: Callable[[str, Any], Awaitable[list[dict]]] | None = None
