"""Context module — builds system prompt and user context injection."""

from __future__ import annotations

from .claude_md import find_claude_md_files, format_claude_md_section, read_claude_md_content
from .environment import collect_environment
from .git_context import GitContext, collect_git_context, format_git_section
from .prompt_builder import (
    PromptAssembly,
    build_prompt_assembly,
    build_system_prompt,
    build_user_context,
)


def get_user_context(work_dir: str | None = None) -> dict:
    """Synchronous helper that returns raw environment data as a dict."""
    import asyncio

    return asyncio.get_event_loop().run_until_complete(collect_environment(work_dir))


def get_system_context(work_dir: str | None = None) -> str:
    """Synchronous helper that returns only the git context section text."""
    import asyncio
    from pathlib import Path

    cwd = Path(work_dir) if work_dir else Path.cwd()
    git_ctx = asyncio.get_event_loop().run_until_complete(collect_git_context(cwd))
    if git_ctx is None:
        return ""
    return format_git_section(git_ctx)


__all__ = [
    "build_system_prompt",
    "build_user_context",
    "build_prompt_assembly",
    "PromptAssembly",
    "get_user_context",
    "get_system_context",
    "GitContext",
    "collect_environment",
    "collect_git_context",
    "find_claude_md_files",
    "read_claude_md_content",
]
