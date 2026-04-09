"""Disk-based skill loading from /skills/ and /commands/ directories.

Port of Claude-Code-rev/src/skills/loadSkillsDir.ts

Loads skills from:
- ~/.claude/skills/ (user skills)
- .claude/skills/ (project skills)
- .claude/commands/ (legacy commands, deprecated)
- Managed/policy skills
- Additional directories (--add-dir)
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from os.path import basename, dirname, isabs, join, normpath, sep
from pathlib import Path
from typing import Any

import yaml

from open_claude.skills.types import SkillCommand

logger = logging.getLogger(__name__)

# Type alias for where a skill was loaded from
LoadedFrom = str  # 'commands_DEPRECATED' | 'skills' | 'plugin' | 'managed' | 'bundled' | 'mcp'


def _get_claude_home() -> str:
    """Get the Claude config home directory."""
    return os.environ.get(
        "CLAUDE_CONFIG_HOME",
        str(Path.home() / ".claude"),
    )


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_content).
    """
    if not content.startswith("---"):
        return {}, content

    end = content.find("---", 3)
    if end == -1:
        return {}, content

    frontmatter_str = content[3:end].strip()
    body = content[end + 3 :].lstrip("\n")

    try:
        frontmatter = yaml.safe_load(frontmatter_str) or {}
        if not isinstance(frontmatter, dict):
            return {}, content
        return frontmatter, body
    except yaml.YAMLError:
        return {}, content


def _parse_hooks_from_frontmatter(
    frontmatter: dict, skill_name: str
) -> dict | None:
    """Parse and validate hooks from frontmatter."""
    hooks = frontmatter.get("hooks")
    if not hooks or not isinstance(hooks, dict):
        return None
    return hooks


def _parse_skill_paths(frontmatter: dict) -> list[str] | None:
    """Parse paths frontmatter from a skill."""
    paths = frontmatter.get("paths")
    if not paths:
        return None

    if isinstance(paths, str):
        patterns = [p.strip() for p in paths.split(",") if p.strip()]
    elif isinstance(paths, list):
        patterns = [str(p).strip() for p in paths if str(p).strip()]
    else:
        return None

    # Remove /** suffix
    patterns = [p[:-3] if p.endswith("/**") else p for p in patterns]

    # Filter empty and match-all patterns
    patterns = [p for p in patterns if p and p != "**"]

    if not patterns:
        return None

    return patterns


def _estimate_token_count(text: str) -> int:
    """Rough token count estimation (~4 chars per token)."""
    return len(text) // 4


def parse_skill_frontmatter_fields(
    frontmatter: dict,
    markdown_content: str,
    resolved_name: str,
) -> dict[str, Any]:
    """Parse all skill frontmatter fields."""
    description = frontmatter.get("description", "")
    if not isinstance(description, str):
        description = str(description) if description else ""

    # If no description in frontmatter, try first line of content
    if not description and markdown_content:
        first_line = markdown_content.strip().split("\n")[0]
        if first_line.startswith("#"):
            description = first_line.lstrip("#").strip()

    if not description:
        description = f"Skill: {resolved_name}"

    user_invocable = frontmatter.get("user-invocable", True)
    if isinstance(user_invocable, str):
        user_invocable = user_invocable.lower() in ("true", "yes", "1")

    model = frontmatter.get("model")
    if model == "inherit":
        model = None

    return {
        "description": description,
        "allowed_tools": _parse_tools_from_frontmatter(frontmatter.get("allowed-tools")),
        "argument_hint": frontmatter.get("argument-hint"),
        "argument_names": _parse_argument_names(frontmatter.get("arguments")),
        "when_to_use": frontmatter.get("when_to_use"),
        "model": model,
        "disable_model_invocation": bool(frontmatter.get("disable-model-invocation", False)),
        "user_invocable": user_invocable,
        "hooks": _parse_hooks_from_frontmatter(frontmatter, resolved_name),
        "execution_context": "fork" if frontmatter.get("context") == "fork" else None,
        "agent": frontmatter.get("agent"),
    }


def _parse_tools_from_frontmatter(tools: Any) -> list[str]:
    """Parse allowed-tools from frontmatter."""
    if not tools:
        return []
    if isinstance(tools, str):
        return [t.strip() for t in tools.split(",") if t.strip()]
    if isinstance(tools, list):
        return [str(t).strip() for t in tools if str(t).strip()]
    return []


def _parse_argument_names(arguments: Any) -> list[str]:
    """Parse argument names from frontmatter."""
    if not arguments:
        return []
    if isinstance(arguments, str):
        return [a.strip() for a in arguments.split(",") if a.strip()]
    if isinstance(arguments, list):
        return [str(a).strip() for a in arguments if str(a).strip()]
    return []


def _substitute_arguments(content: str, args: str, arg_names: list[str]) -> str:
    """Substitute $arg_name placeholders with provided arguments."""
    if not args or not arg_names:
        return content

    # Split args by whitespace for positional substitution
    arg_values = args.split()

    for i, name in enumerate(arg_names):
        if i < len(arg_values):
            content = content.replace(f"${name}", arg_values[i])

    return content


def create_skill_command(
    skill_name: str,
    description: str,
    markdown_content: str,
    allowed_tools: list[str] | None = None,
    argument_hint: str | None = None,
    argument_names: list[str] | None = None,
    when_to_use: str | None = None,
    model: str | None = None,
    disable_model_invocation: bool = False,
    user_invocable: bool = True,
    source: str = "skills",
    base_dir: str | None = None,
    loaded_from: LoadedFrom = "skills",
    hooks: dict | None = None,
    execution_context: str | None = None,
    agent: str | None = None,
    paths: list[str] | None = None,
) -> SkillCommand:
    """Create a SkillCommand from parsed frontmatter and content."""

    async def get_prompt_for_command(args: str, context: object) -> list[dict]:
        final_content = (
            f"Base directory for this skill: {base_dir}\n\n{markdown_content}"
            if base_dir
            else markdown_content
        )

        if argument_names:
            final_content = _substitute_arguments(
                final_content, args, argument_names
            )

        # Replace ${CLAUDE_SKILL_DIR}
        if base_dir:
            skill_dir = base_dir.replace("\\", "/") if os.name == "nt" else base_dir
            final_content = final_content.replace("${CLAUDE_SKILL_DIR}", skill_dir)

        # Replace ${CLAUDE_SESSION_ID}
        session_id = os.environ.get("CLAUDE_SESSION_ID", "")
        final_content = final_content.replace("${CLAUDE_SESSION_ID}", session_id)

        return [{"type": "text", "text": final_content}]

    return SkillCommand(
        name=skill_name,
        description=description,
        aliases=[],
        when_to_use=when_to_use,
        argument_hint=argument_hint,
        allowed_tools=allowed_tools or [],
        model=model,
        disable_model_invocation=disable_model_invocation,
        user_invocable=user_invocable,
        is_enabled=lambda: True,
        hooks=hooks,
        context=execution_context,
        agent=agent,
        skill_root=base_dir,
        source=source,
        loaded_from=loaded_from,
        content_length=len(markdown_content),
        is_hidden=not user_invocable,
        get_prompt_for_command=get_prompt_for_command,
    )


async def _load_skills_from_skills_dir(
    base_path: str, source: str = "skills"
) -> list[tuple[SkillCommand, str]]:
    """Load skills from a /skills/ directory.

    Only supports directory format: skill-name/SKILL.md
    Returns list of (SkillCommand, file_path) tuples.
    """
    if not os.path.isdir(base_path):
        return []

    results: list[tuple[SkillCommand, str]] = []

    try:
        entries = sorted(os.listdir(base_path))
    except OSError:
        return []

    for entry in entries:
        entry_path = join(base_path, entry)

        if not os.path.isdir(entry_path):
            continue

        skill_file = join(entry_path, "SKILL.md")

        if not os.path.isfile(skill_file):
            continue

        try:
            with open(skill_file, "r", encoding="utf-8") as f:
                content = f.read()

            frontmatter, markdown_content = _parse_frontmatter(content)
            skill_name = entry
            parsed = parse_skill_frontmatter_fields(
                frontmatter, markdown_content, skill_name
            )
            paths = _parse_skill_paths(frontmatter)

            command = create_skill_command(
                skill_name=skill_name,
                markdown_content=markdown_content,
                base_dir=entry_path,
                loaded_from="skills",
                source=source,
                paths=paths,
                **parsed,
            )

            results.append((command, skill_file))

        except Exception as e:
            logger.debug("Failed to load skill from %s: %s", skill_file, e)

    return results


async def _load_skills_from_commands_dir(
    cwd: str,
) -> list[tuple[SkillCommand, str]]:
    """Load skills from legacy /commands/ directories.

    Supports both directory format (SKILL.md) and single .md file format.
    Scans user-level (~/.claude/commands/) and project-level (.claude/commands/).
    Nested subdirectories are treated as namespaces (e.g. opsx/apply.md -> opsx:apply).
    """
    results: list[tuple[SkillCommand, str]] = []

    # Check both user-level and project-level commands
    user_commands_dir = join(_get_claude_home(), "commands")
    project_commands_dir = join(cwd, ".claude", "commands")

    for cmd_dir in [user_commands_dir, project_commands_dir]:
        if not os.path.isdir(cmd_dir):
            continue

        try:
            _scan_commands_dir(cmd_dir, cmd_dir, "", results)
        except OSError:
            pass

    return results


def _scan_commands_dir(
    cmd_dir: str,
    base_dir: str,
    namespace: str,
    results: list[tuple[SkillCommand, str]],
) -> None:
    """Recursively scan a commands directory, handling nested namespaces.

    Flat .md files get their name directly. Subdirectories containing .md
    files use colon-separated names (e.g. opsx/apply.md -> opsx:apply).
    Subdirectories with SKILL.md use the directory name directly.
    """
    try:
        entries = sorted(os.listdir(cmd_dir))
    except OSError:
        return

    for entry in entries:
        entry_path = join(cmd_dir, entry)

        if os.path.isdir(entry_path):
            # Check for directory-with-SKILL.md format first
            skill_file = join(entry_path, "SKILL.md")
            if os.path.isfile(skill_file):
                cmd_name = f"{namespace}{entry}" if namespace else entry
                _load_single_command(skill_file, entry_path, cmd_name, results)
            else:
                # Treat as namespace: recurse into it
                child_namespace = f"{namespace}{entry}:" if namespace else f"{entry}:"
                _scan_commands_dir(entry_path, base_dir, child_namespace, results)

        elif entry.endswith(".md"):
            skill_file = entry_path
            cmd_name = f"{namespace}{entry[:-3]}" if namespace else entry[:-3]
            _load_single_command(skill_file, None, cmd_name, results)


def _load_single_command(
    skill_file: str,
    entry_dir: str | None,
    cmd_name: str,
    results: list[tuple[SkillCommand, str]],
) -> None:
    """Load a single command from a file path."""
    try:
        with open(skill_file, "r", encoding="utf-8") as f:
            content = f.read()

        frontmatter, markdown_content = _parse_frontmatter(content)
        parsed = parse_skill_frontmatter_fields(
            frontmatter, markdown_content, cmd_name
        )

        command = create_skill_command(
            skill_name=cmd_name,
            markdown_content=markdown_content,
            source="commands_DEPRECATED",
            loaded_from="commands_DEPRECATED",
            base_dir=dirname(skill_file) if entry_dir and os.path.isdir(entry_dir) else None,
            **parsed,
        )

        results.append((command, skill_file))

    except Exception as e:
        logger.debug("Failed to load command from %s: %s", skill_file, e)


async def load_all_disk_skills(cwd: str) -> list[SkillCommand]:
    """Load all skills from disk (skills dirs + commands dirs).

    Main entry point for disk-based skill loading.
    """
    user_skills_dir = join(_get_claude_home(), "skills")
    project_skills_dir = join(cwd, ".claude", "skills")

    all_skills_with_paths: list[tuple[SkillCommand, str]] = []

    # Load from all sources
    skills_sources = [
        _load_skills_from_skills_dir(user_skills_dir, "userSettings"),
        _load_skills_from_skills_dir(project_skills_dir, "projectSettings"),
        _load_skills_from_commands_dir(cwd),
    ]

    loaded_lists = await __import__("asyncio").gather(*skills_sources)

    for loaded in loaded_lists:
        all_skills_with_paths.extend(loaded)

    # Deduplicate by realpath
    seen: set[str] = set()
    deduplicated: list[SkillCommand] = []

    for skill, file_path in all_skills_with_paths:
        try:
            real_path = os.path.realpath(file_path)
        except OSError:
            real_path = file_path

        if real_path in seen:
            continue
        seen.add(real_path)
        deduplicated.append(skill)

    if deduplicated:
        logger.debug(
            "Loaded %d disk-based skills (%d deduplicated)",
            len(deduplicated),
            len(all_skills_with_paths) - len(deduplicated),
        )

    return deduplicated


# --- Dynamic skill discovery ---

_dynamic_skill_dirs: set[str] = set()


async def discover_skill_dirs_for_paths(
    file_paths: list[str], cwd: str
) -> list[str]:
    """Walk up from file paths to cwd, finding .claude/skills directories."""
    resolved_cwd = cwd.rstrip(sep)
    new_dirs: list[str] = []

    for file_path in file_paths:
        current_dir = dirname(file_path)

        while current_dir.startswith(resolved_cwd + sep):
            skill_dir = join(current_dir, ".claude", "skills")

            if skill_dir not in _dynamic_skill_dirs:
                _dynamic_skill_dirs.add(skill_dir)
                if os.path.isdir(skill_dir):
                    new_dirs.append(skill_dir)

            parent = dirname(current_dir)
            if parent == current_dir:
                break
            current_dir = parent

    # Sort deepest first
    return sorted(new_dirs, key=lambda d: d.count(sep), reverse=True)


async def add_skill_directories(dirs: list[str]) -> list[SkillCommand]:
    """Load skills from discovered directories into the dynamic registry."""
    if not dirs:
        return []

    from open_claude.skills import get_skill_registry

    registry = get_skill_registry()
    new_skills: list[SkillCommand] = []

    for dir_path in dirs:
        loaded = await _load_skills_from_skills_dir(dir_path, "projectSettings")
        for skill, _ in loaded:
            registry.add_dynamic_skill(skill)
            new_skills.append(skill)

    if new_skills:
        logger.debug(
            "Dynamically discovered %d skills from %d directories",
            len(new_skills),
            len(dirs),
        )

    return new_skills


def clear_skill_caches() -> None:
    """Clear all skill loading caches."""
    _dynamic_skill_dirs.clear()
