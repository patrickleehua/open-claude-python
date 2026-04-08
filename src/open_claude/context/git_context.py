"""Git context collection for the system prompt."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GitContext:
    """Collected git repository state."""

    branch: str | None
    main_branch: str | None  # "main" or "master"
    recent_commits: list[str]  # last 5 commit messages (truncated)
    status_summary: str | None  # git status --short (truncated to 2000 chars)
    git_user: str | None


_STATUS_MAX_LENGTH = 2000
_COMMIT_MAX_LENGTH = 120


async def _run_git(*args: str, cwd: str | Path | None = None) -> str | None:
    """Run a git command and return stripped stdout, or None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode().strip()
    except (OSError, FileNotFoundError):
        pass
    return None


def _detect_main_branch(branches_output: str | None) -> str | None:
    """Determine the main branch from a list of branch names."""
    if not branches_output:
        return None
    branches = [b.strip().lstrip("* ") for b in branches_output.splitlines()]
    if "main" in branches:
        return "main"
    if "master" in branches:
        return "master"
    return None


async def collect_git_context(work_dir: Path) -> GitContext | None:
    """Collect git context. Returns None if not a git repo."""
    is_repo = await _run_git(
        "rev-parse", "--is-inside-work-tree", cwd=work_dir,
    )
    if is_repo != "true":
        return None

    # Gather all git info in parallel (using --no-optional-locks)
    branch, log, status, user, branches_raw = await asyncio.gather(
        _run_git("branch", "--show-current", cwd=work_dir),
        _run_git("--no-optional-locks", "log", "--oneline", "-5", cwd=work_dir),
        _run_git("--no-optional-locks", "status", "--short", cwd=work_dir),
        _run_git("config", "user.name"),
        _run_git("branch", "--list", "--format=%(refname:short)", cwd=work_dir),
    )

    # Parse recent commits
    recent_commits: list[str] = []
    if log:
        for line in log.splitlines():
            truncated = line[:_COMMIT_MAX_LENGTH]
            recent_commits.append(truncated)

    # Truncate status
    status_summary: str | None = None
    if status:
        status_summary = status[:_STATUS_MAX_LENGTH]

    return GitContext(
        branch=branch,
        main_branch=_detect_main_branch(branches_raw),
        recent_commits=recent_commits,
        status_summary=status_summary,
        git_user=user,
    )


def format_git_section(ctx: GitContext) -> str:
    """Format git context as plain text matching the original Claude Code format.

    No XML tags — just structured plain text with framing instructions.
    """
    sections: list[str] = []

    # Header with framing
    header = "This is the git status at the start of the conversation. Note that this status is a snapshot in time, and will not update during the conversation."

    parts: list[str] = [header]

    if ctx.branch:
        parts.append(f"Current branch: {ctx.branch}")

    if ctx.main_branch:
        parts.append(f"Main branch (you will usually use this for PRs): {ctx.main_branch}")

    if ctx.git_user:
        parts.append(f"Git user: {ctx.git_user}")

    # Status section
    if ctx.status_summary:
        status_text = ctx.status_summary
        if len(ctx.status_summary) >= _STATUS_MAX_LENGTH:
            status_text += (
                "\n\n... (truncated because it exceeds 2k characters. "
                'If you need more information, run "git status\" using BashTool)'
            )
        parts.append(f"Status:\n{status_text}")
    else:
        parts.append("Status:\n(clean)")

    # Recent commits — no "- " prefix, just raw lines
    if ctx.recent_commits:
        commit_lines = "\n".join(ctx.recent_commits)
        parts.append(f"Recent commits:\n{commit_lines}")

    return "\n\n".join(parts)
