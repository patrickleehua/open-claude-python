"""Load settings from settings.json and apply environment variables."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Settings:
    """Loaded application settings."""

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    verbose: bool = False
    include_git_instructions: bool = True
    raw: dict[str, Any] = field(default_factory=dict)


def _find_settings_json() -> Path | None:
    """Find settings.json in standard locations.

    Search order:
    1. Current working directory
    2. .claude/ directory in cwd
    3. ~/.claude/settings.json
    """
    candidates = [
        Path.cwd() / "settings.json",
        Path.cwd() / ".claude" / "settings.json",
        Path.home() / ".claude" / "settings.json",
    ]
    for path in candidates:
        if path.is_file():
            return path
    return None


def load_settings(settings_path: str | Path | None = None) -> Settings:
    """Load settings from settings.json and apply env vars to os.environ.

    The settings.json ``env`` section is applied as environment variables
    so that downstream code (client factory, etc.) can read them via
    ``os.environ`` — matching Claude Code's behavior.

    Returns a Settings dataclass with the resolved values.
    """
    if settings_path is not None:
        path = Path(settings_path)
    else:
        path = _find_settings_json()

    if path is None or not path.is_file():
        # No settings.json found — use env vars as-is
        return Settings(
            api_key=os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"),
            base_url=os.environ.get("ANTHROPIC_BASE_URL"),
            model=os.environ.get("ANTHROPIC_MODEL"),
        )

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        raw = {}

    # Apply env section to os.environ (if not already set)
    env_section = raw.get("env", {})
    for key, value in env_section.items():
        if isinstance(value, str) and key not in os.environ:
            os.environ[key] = value

    # Resolve effective values (env var takes priority, then settings.json)
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or None
    )
    base_url = os.environ.get("ANTHROPIC_BASE_URL")
    model = os.environ.get("ANTHROPIC_MODEL")

    # Resolve includeGitInstructions (env var > settings.json > default true)
    include_git = True
    disable_env = os.environ.get("CLAUDE_CODE_DISABLE_GIT_INSTRUCTIONS", "").strip().lower()
    if disable_env in ("1", "true", "yes"):
        include_git = False
    elif disable_env in ("0", "false", "no"):
        include_git = True
    elif "includeGitInstructions" in raw:
        include_git = bool(raw["includeGitInstructions"])

    return Settings(
        api_key=api_key,
        base_url=base_url,
        model=model,
        include_git_instructions=include_git,
        raw=raw,
    )
