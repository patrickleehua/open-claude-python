"""MCP server configuration loading from multiple scopes.

Loads MCP server configs from:
1. ``~/.claude/settings.json`` ``mcpServers`` section (user scope)
2. ``.mcp.json`` in the current working directory (project scope)
3. Environment variable ``MCP_SERVERS`` for dynamic configs

Configs are merged with project-scoped configs taking precedence over
user-scoped configs on name collision.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from open_claude.services.mcp.env_expansion import expand_config_env
from open_claude.services.mcp.types import (
    ConfigScope,
    McpHTTPServerConfig,
    McpJsonFile,
    McpServerConfig,
    McpSSEServerConfig,
    McpStdioServerConfig,
    ScopedMcpServerConfig,
)

logger = logging.getLogger(__name__)

# Key in settings.json that holds MCP server definitions
_MCP_SERVERS_KEY = "mcpServers"


def _parse_server_config(raw: dict[str, Any]) -> McpServerConfig:
    """Parse a raw dict into the appropriate McpServerConfig variant.

    Determines the config type from the ``type`` field:
    - ``"stdio"`` or absent → McpStdioServerConfig
    - ``"sse"`` → McpSSEServerConfig
    - ``"http"`` → McpHTTPServerConfig
    """
    server_type = raw.get("type", "stdio")
    if server_type == "stdio":
        return McpStdioServerConfig(**raw)
    elif server_type == "sse":
        return McpSSEServerConfig(**raw)
    elif server_type == "http":
        return McpHTTPServerConfig(**raw)
    else:
        # Default to stdio for backwards compatibility
        logger.warning("Unknown MCP server type '%s', treating as stdio", server_type)
        return McpStdioServerConfig(**raw)


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file, returning {} on any error."""
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.debug("Failed to load %s: %s", path, exc)
    return {}


def _load_mcp_json_configs() -> dict[str, McpServerConfig]:
    """Load server configs from ``.mcp.json`` in the CWD."""
    mcp_json_path = Path.cwd() / ".mcp.json"
    raw = _load_json(mcp_json_path)
    if not raw:
        return {}

    try:
        parsed = McpJsonFile.model_validate(raw)
    except ValidationError:
        logger.warning("Invalid .mcp.json format")
        return {}

    servers: dict[str, McpServerConfig] = {}
    mcp_raw = raw.get(_MCP_SERVERS_KEY, {})
    for name, config_dict in mcp_raw.items():
        if not isinstance(config_dict, dict):
            continue
        try:
            expanded = expand_config_env(config_dict)
            servers[name] = _parse_server_config(expanded)
        except (ValidationError, Exception) as exc:
            logger.warning("Invalid MCP config for '%s': %s", name, exc)

    return servers


def _load_settings_json_mcp_configs() -> dict[str, McpServerConfig]:
    """Load MCP server configs from ``~/.claude/settings.json``."""
    settings_path = Path.home() / ".claude" / "settings.json"
    raw = _load_json(settings_path)
    mcp_raw = raw.get(_MCP_SERVERS_KEY, {})
    if not isinstance(mcp_raw, dict):
        return {}

    servers: dict[str, McpServerConfig] = {}
    for name, config_dict in mcp_raw.items():
        if not isinstance(config_dict, dict):
            continue
        try:
            expanded = expand_config_env(config_dict)
            servers[name] = _parse_server_config(expanded)
        except (ValidationError, Exception) as exc:
            logger.warning("Invalid MCP config for '%s' in settings.json: %s", name, exc)

    return servers


def _load_disabled_servers() -> set[str]:
    """Load the set of disabled MCP server names from settings."""
    settings_path = Path.home() / ".claude" / "settings.json"
    raw = _load_json(settings_path)
    disabled = raw.get("disabledMcpjsonServers", [])
    if isinstance(disabled, list):
        return set(disabled)
    return set()


class McpConfigLoader:
    """Loads and merges MCP server configurations from multiple scopes."""

    def __init__(self) -> None:
        self._disabled_servers: set[str] | None = None

    @property
    def disabled_servers(self) -> set[str]:
        """Lazily load and cache the disabled server set."""
        if self._disabled_servers is None:
            self._disabled_servers = _load_disabled_servers()
        return self._disabled_servers

    def is_server_disabled(self, name: str) -> bool:
        """Check if a server is in the disabled list."""
        return name in self.disabled_servers

    def get_all_configs(
        self,
        include_disabled: bool = False,
    ) -> dict[str, ScopedMcpServerConfig]:
        """Load and merge MCP configs from all scopes.

        Precedence (higher wins on name collision):
        1. Project scope (``.mcp.json`` in CWD)
        2. User scope (``~/.claude/settings.json`` ``mcpServers``)

        Disabled servers are excluded from the result.
        """
        result: dict[str, ScopedMcpServerConfig] = {}

        # User scope (lowest precedence)
        user_servers = _load_settings_json_mcp_configs()
        for name, config in user_servers.items():
            result[name] = ScopedMcpServerConfig(config=config, scope=ConfigScope.USER)

        # Project scope (highest precedence, overwrites user)
        project_servers = _load_mcp_json_configs()
        for name, config in project_servers.items():
            result[name] = ScopedMcpServerConfig(config=config, scope=ConfigScope.PROJECT)

        # Filter out disabled servers
        disabled = self.disabled_servers
        if disabled and not include_disabled:
            result = {
                k: v for k, v in result.items() if k not in disabled
            }

        return result


def add_mcp_config(
    name: str,
    config: McpServerConfig,
    scope: ConfigScope = ConfigScope.PROJECT,
) -> None:
    """Add an MCP server config to the specified scope.

    Writes to ``.mcp.json`` for project scope,
    ``~/.claude/settings.json`` for user scope.
    """
    if scope == ConfigScope.PROJECT:
        _add_to_mcp_json(name, config)
    elif scope == ConfigScope.USER:
        _add_to_settings_json(name, config)
    else:
        raise ValueError(f"Cannot write to scope: {scope}")


def add_mcp_json_config(
    name: str,
    raw_config: dict[str, Any],
    scope: ConfigScope = ConfigScope.PROJECT,
) -> McpServerConfig:
    """Parse and add a raw MCP JSON config to the specified scope."""
    if not isinstance(raw_config, dict):
        raise ValueError("MCP JSON config must be an object")
    config = _parse_server_config(raw_config)
    add_mcp_config(name, config, scope=scope)
    return config


def remove_mcp_config(name: str, scope: ConfigScope = ConfigScope.PROJECT) -> None:
    """Remove an MCP server config from the specified scope."""
    if scope == ConfigScope.PROJECT:
        _remove_from_mcp_json(name)
    elif scope == ConfigScope.USER:
        _remove_from_settings_json(name)
    else:
        raise ValueError(f"Cannot remove from scope: {scope}")


def get_mcp_config(name: str) -> ScopedMcpServerConfig | None:
    """Look up a configured MCP server by name across all scopes."""
    return McpConfigLoader().get_all_configs(include_disabled=True).get(name)


def describe_mcp_config_path(scope: ConfigScope) -> Path:
    """Return the file path that stores MCP config for the given scope."""
    if scope == ConfigScope.PROJECT:
        return Path.cwd() / ".mcp.json"
    if scope == ConfigScope.USER:
        return Path.home() / ".claude" / "settings.json"
    raise ValueError(f"Unsupported scope: {scope}")


def set_mcp_server_disabled(name: str, disabled: bool) -> None:
    """Persist enabled/disabled state for an MCP server."""
    path = Path.home() / ".claude" / "settings.json"
    raw = _load_json(path)
    disabled_servers = raw.get("disabledMcpjsonServers", [])
    if not isinstance(disabled_servers, list):
        disabled_servers = []
    disabled_set = set(str(item) for item in disabled_servers)
    if disabled:
        disabled_set.add(name)
    else:
        disabled_set.discard(name)
    if disabled_set:
        raw["disabledMcpjsonServers"] = sorted(disabled_set)
    else:
        raw.pop("disabledMcpjsonServers", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def reset_project_mcp_choices() -> None:
    """Clear project MCP approval/disable choices stored in settings.json."""
    path = Path.home() / ".claude" / "settings.json"
    raw = _load_json(path)
    raw["enabledMcpjsonServers"] = []
    raw["disabledMcpjsonServers"] = []
    raw["enableAllProjectMcpServers"] = False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _add_to_mcp_json(name: str, config: McpServerConfig) -> None:
    """Add a server to the project ``.mcp.json`` file."""
    path = Path.cwd() / ".mcp.json"
    raw = _load_json(path)
    if _MCP_SERVERS_KEY not in raw:
        raw[_MCP_SERVERS_KEY] = {}
    raw[_MCP_SERVERS_KEY][name] = config.model_dump(exclude_none=True)
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _remove_from_mcp_json(name: str) -> None:
    """Remove a server from the project ``.mcp.json`` file."""
    path = Path.cwd() / ".mcp.json"
    raw = _load_json(path)
    servers = raw.get(_MCP_SERVERS_KEY, {})
    servers.pop(name, None)
    if not servers and _MCP_SERVERS_KEY in raw:
        del raw[_MCP_SERVERS_KEY]
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _add_to_settings_json(name: str, config: McpServerConfig) -> None:
    """Add a server to the user ``~/.claude/settings.json`` file."""
    path = Path.home() / ".claude" / "settings.json"
    raw = _load_json(path)
    if _MCP_SERVERS_KEY not in raw:
        raw[_MCP_SERVERS_KEY] = {}
    raw[_MCP_SERVERS_KEY][name] = config.model_dump(exclude_none=True)
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _remove_from_settings_json(name: str) -> None:
    """Remove a server from the user ``~/.claude/settings.json`` file."""
    path = Path.home() / ".claude" / "settings.json"
    raw = _load_json(path)
    servers = raw.get(_MCP_SERVERS_KEY, {})
    servers.pop(name, None)
    if not servers and _MCP_SERVERS_KEY in raw:
        del raw[_MCP_SERVERS_KEY]
    path.write_text(json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
