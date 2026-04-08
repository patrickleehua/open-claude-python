"""Helpers for importing MCP server definitions from Claude Desktop."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from open_claude.services.mcp.types import McpServerConfig
from open_claude.services.mcp.config import add_mcp_json_config
from open_claude.services.mcp.types import ConfigScope


def get_claude_desktop_config_candidates() -> list[Path]:
    """Return likely Claude Desktop config paths for the current machine."""
    candidates: list[Path] = []

    appdata = os.environ.get("APPDATA")
    if appdata:
        candidates.append(Path(appdata) / "Claude" / "claude_desktop_config.json")

    userprofile = os.environ.get("USERPROFILE")
    if userprofile:
        candidates.append(Path(userprofile) / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json")

    home = Path.home()
    candidates.append(home / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json")
    candidates.append(home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json")
    candidates.append(home / ".config" / "Claude" / "claude_desktop_config.json")

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def find_claude_desktop_config_path() -> Path | None:
    """Find the first existing Claude Desktop config path."""
    for candidate in get_claude_desktop_config_candidates():
        if candidate.is_file():
            return candidate
    return None


def read_claude_desktop_mcp_servers() -> dict[str, dict[str, Any]]:
    """Read raw MCP server configs from Claude Desktop."""
    path = find_claude_desktop_config_path()
    if path is None:
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    mcp_servers = raw.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        return {}

    result: dict[str, dict[str, Any]] = {}
    for name, config in mcp_servers.items():
        if isinstance(name, str) and isinstance(config, dict):
            result[name] = config
    return result


def import_claude_desktop_mcp_servers(
    scope: ConfigScope = ConfigScope.PROJECT,
) -> dict[str, McpServerConfig]:
    """Import all valid MCP servers from Claude Desktop config into this project."""
    imported: dict[str, McpServerConfig] = {}
    for name, raw_config in read_claude_desktop_mcp_servers().items():
        try:
            imported[name] = add_mcp_json_config(name, raw_config, scope=scope)
        except Exception:
            continue
    return imported
