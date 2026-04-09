"""Skills system for open-claude-python.

Provides skill registration, discovery, and execution. Port of the TypeScript
skills system from Claude-Code-rev/src/skills/.

Usage:
    from open_claude.skills import get_skill_registry, init_bundled_skills

    init_bundled_skills()  # Register all bundled skills
    registry = get_skill_registry()
    commands = registry.get_skill_commands_for_prompt()
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from functools import partial
from pathlib import Path

from open_claude.skills.registry import SkillRegistry
from open_claude.skills.types import BundledSkillDefinition, SkillCommand

logger = logging.getLogger(__name__)

__all__ = [
    "BundledSkillDefinition",
    "SkillCommand",
    "SkillRegistry",
    "get_skill_registry",
    "reset_skill_registry",
    "register_bundled_skill",
    "init_bundled_skills",
]

# Module-level singleton
_registry: SkillRegistry | None = None

# Per-process temp directory for skill file extraction
_skills_temp_dir: str | None = None


def _get_skills_temp_dir() -> str:
    """Get or create the per-process temp directory for skill files."""
    global _skills_temp_dir
    if _skills_temp_dir is None:
        _skills_temp_dir = tempfile.mkdtemp(prefix="claude-skills-")
    return _skills_temp_dir


def get_skill_registry() -> SkillRegistry:
    """Get the global skill registry singleton."""
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
    return _registry


def reset_skill_registry() -> None:
    """Reset the global skill registry (for testing)."""
    global _registry
    if _registry is not None:
        _registry.clear()
    _registry = None


def get_bundled_skill_extract_dir(skill_name: str) -> str:
    """Deterministic extraction directory for a bundled skill's reference files."""
    return os.path.join(_get_skills_temp_dir(), skill_name)


def _resolve_skill_file_path(base_dir: str, rel_path: str) -> str:
    """Normalize and validate a skill-relative path; raises on traversal."""
    normalized = os.path.normpath(rel_path)
    if os.path.isabs(normalized) or ".." in normalized.split(os.sep):
        raise ValueError(f"bundled skill file path escapes skill dir: {rel_path}")
    return os.path.join(base_dir, normalized)


def _safe_write_file(path: str, content: str) -> None:
    """Write a file safely with O_CREAT | O_EXCL to prevent symlink attacks."""
    parent = os.path.dirname(path)
    os.makedirs(parent, mode=0o700, exist_ok=True)

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(path, flags, 0o600)
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)


def _write_skill_files(dir_path: str, files: dict[str, str]) -> None:
    """Extract bundled skill reference files to disk."""
    for rel_path, content in files.items():
        target = _resolve_skill_file_path(dir_path, rel_path)
        parent = os.path.dirname(target)
        os.makedirs(parent, mode=0o700, exist_ok=True)
        _safe_write_file(target, content)


def _extract_bundled_skill_files(
    skill_name: str, files: dict[str, str]
) -> str | None:
    """Extract a bundled skill's reference files to disk.

    Returns the directory written to, or None if write failed.
    """
    dir_path = get_bundled_skill_extract_dir(skill_name)
    try:
        _write_skill_files(dir_path, files)
        return dir_path
    except Exception as e:
        logger.debug(
            "Failed to extract bundled skill '%s' to %s: %s",
            skill_name,
            dir_path,
            e,
        )
        return None


def register_bundled_skill(definition: BundledSkillDefinition) -> None:
    """Register a bundled skill with the global registry.

    Handles file extraction (if definition.files is set) and wraps
    get_prompt_for_command with base-directory prefix logic.
    """
    files = definition.files
    skill_root: str | None = None
    get_prompt = definition.get_prompt_for_command

    if files and len(files) > 0:
        skill_root = get_bundled_skill_extract_dir(definition.name)
        inner = definition.get_prompt_for_command
        extracted: bool = False

        async def wrapped_get_prompt(
            args: str, context: object
        ) -> list[dict]:
            nonlocal extracted
            if not extracted:
                extracted_dir = _extract_bundled_skill_files(
                    definition.name, files
                )
                extracted = True
                if extracted_dir:
                    # Prepend base dir to first content block
                    blocks = await inner(args, context)
                    prefix = f"Base directory for this skill: {extracted_dir}\n\n"
                    if blocks and blocks[0].get("type") == "text":
                        blocks[0] = {
                            "type": "text",
                            "text": prefix + blocks[0].get("text", ""),
                        }
                    else:
                        blocks.insert(0, {"type": "text", "text": prefix})
                    return blocks
            return await inner(args, context)

        get_prompt = wrapped_get_prompt

    command = SkillCommand(
        name=definition.name,
        description=definition.description,
        aliases=definition.aliases,
        when_to_use=definition.when_to_use,
        argument_hint=definition.argument_hint,
        allowed_tools=definition.allowed_tools,
        model=definition.model,
        disable_model_invocation=definition.disable_model_invocation,
        user_invocable=definition.user_invocable,
        is_enabled=definition.is_enabled,
        hooks=definition.hooks,
        context=definition.context,
        agent=definition.agent,
        skill_root=skill_root,
        source="bundled",
        loaded_from="bundled",
        content_length=0,
        is_hidden=not definition.user_invocable,
        get_prompt_for_command=get_prompt,
    )

    get_skill_registry().register(command)


def init_bundled_skills() -> None:
    """Initialize all bundled skills.

    Called at startup to register skills that ship with the CLI.
    Feature-flagged skills are gated via environment variables.
    """
    from open_claude.skills.bundled import _init_bundled_skills

    _init_bundled_skills()
