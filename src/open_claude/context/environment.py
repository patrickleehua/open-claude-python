"""Environment information collection for the system prompt."""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any


def _detect_platform() -> str:
    """Return a normalized platform name."""
    system = sys.platform
    if system == "win32":
        return "windows"
    if system == "darwin":
        return "macos"
    return "linux"


def _detect_shell() -> str:
    """Return the name of the current shell."""
    # On Windows, check COMSPEC first
    comspec = os.environ.get("COMSPEC", "")
    if comspec:
        name = os.path.basename(comspec).lower()
        if "powershell" in name or "pwsh" in name:
            return "powershell"
        if "cmd" in name:
            return "cmd"

    # Unix shells
    shell_path = os.environ.get("SHELL", "")
    if shell_path:
        return os.path.basename(shell_path)

    # Fallback
    if sys.platform == "win32":
        return "cmd"
    return "bash"


def _get_os_version() -> str:
    """Return a human-readable OS version string."""
    try:
        if sys.platform == "win32":
            import platform
            return platform.version()
        if sys.platform == "darwin":
            return platform.mac_ver()[0]
        # Linux
        return platform.uname().release
    except Exception:
        return ""


async def _run_git_command(*args: str) -> str | None:
    """Run a git command and return its stdout, or None on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode().strip()
    except (OSError, FileNotFoundError):
        pass
    return None


async def collect_environment(work_dir: str | None = None) -> dict[str, Any]:
    """Gather raw environment data as a dict.

    Formatting is handled by the prompts module — this function only collects.
    """
    cwd = work_dir or os.getcwd()

    # Check git repo and collect branch/user in parallel
    is_git, branch, user = await asyncio.gather(
        _run_git_command("rev-parse", "--is-inside-work-tree"),
        _run_git_command("branch", "--show-current"),
        _run_git_command("config", "user.name"),
    )

    return {
        "platform": _detect_platform(),
        "shell": _detect_shell(),
        "working_dir": cwd,
        "os_version": _get_os_version(),
        "date": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"),
        "is_git_repo": is_git == "true",
        "git_branch": branch,
        "git_user": user,
    }
