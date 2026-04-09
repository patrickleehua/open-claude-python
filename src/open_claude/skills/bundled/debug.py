"""Debug skill - debug session issues.

Port of Claude-Code-rev/src/skills/bundled/debug.ts
"""

from __future__ import annotations

import os
from pathlib import Path

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition, is_ant_user

DEFAULT_DEBUG_LINES_READ = 20
TAIL_READ_BYTES = 64 * 1024


def _get_debug_log_path() -> str:
    """Get the debug log path for the current session."""
    claude_dir = Path.home() / ".claude"
    debug_dir = claude_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    return str(debug_dir / "debug.log")


def _tail_file(path: str, max_bytes: int, lines: int) -> tuple[str, str | None]:
    """Tail a file, reading at most max_bytes and returning last N lines.

    Returns (tail_content, error_message_or_None).
    """
    try:
        file_size = os.path.getsize(path)
        read_size = min(file_size, max_bytes)
        start_offset = file_size - read_size
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            f.seek(start_offset)
            content = f.read()
        tail_lines = content.split("\n")[-lines:]
        return "\n".join(tail_lines), None
    except FileNotFoundError:
        return "", "No debug log exists yet."
    except Exception as e:
        return "", f"Failed to read debug log: {e}"


def _format_file_size(size: int) -> str:
    """Format file size in human-readable form."""
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f}{unit}"
        size /= 1024
    return f"{size:.0f}TB"


async def _get_prompt(args: str, context: object) -> list[dict]:
    debug_log_path = _get_debug_log_path()

    tail_content, error = _tail_file(debug_log_path, TAIL_READ_BYTES, DEFAULT_DEBUG_LINES_READ)

    if error:
        log_info = error
    else:
        try:
            file_size = os.path.getsize(debug_log_path)
            size_str = _format_file_size(file_size)
        except Exception:
            size_str = "unknown"
        log_info = f"Log size: {size_str}\n\n### Last {DEFAULT_DEBUG_LINES_READ} lines\n\n```\n{tail_content}\n```"

    settings_user = str(Path.home() / ".claude" / "settings.json")
    settings_project = ".claude/settings.json"
    settings_local = ".claude/settings.local.json"

    prompt = f"""# Debug Skill

Help the user debug an issue they're encountering in this current Claude Code session.

## Session Debug Log

The debug log for the current session is at: `{debug_log_path}`

{log_info}

For additional context, grep for [ERROR] and [WARN] lines across the full file.

## Issue Description

{args or 'The user did not describe a specific issue. Read the debug log and summarize any errors, warnings, or notable issues.'}

## Settings

Remember that settings are in:
* user - {settings_user}
* project - {settings_project}
* local - {settings_local}

## Instructions

1. Review the user's issue description
2. The last {DEFAULT_DEBUG_LINES_READ} lines show the debug file format. Look for [ERROR] and [WARN] entries, stack traces, and failure patterns across the file
3. Explain what you found in plain language
4. Suggest concrete fixes or next steps
"""
    return [{"type": "text", "text": prompt}]


def register_debug_skill() -> None:
    register_bundled_skill(
        BundledSkillDefinition(
            name="debug",
            description=(
                "Debug your current Claude Code session by reading the session debug log. Includes all event logging"
                if is_ant_user()
                else "Enable debug logging for this session and help diagnose issues"
            ),
            allowed_tools=["Read", "Grep", "Glob"],
            argument_hint="[issue description]",
            disable_model_invocation=True,
            user_invocable=True,
            get_prompt_for_command=_get_prompt,
        )
    )
