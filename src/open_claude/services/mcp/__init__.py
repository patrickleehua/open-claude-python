"""MCP (Model Context Protocol) integration — public API.

Provides the main entry points for MCP functionality:

- :func:`get_mcp_tools` — Discover and return all MCP tools as ``Tool`` instances.
- :func:`connect_mcp_servers` — Connect to all configured MCP servers.
- :func:`disconnect_mcp_servers` — Disconnect from all servers.
- :func:`get_mcp_manager` — Access the underlying connection manager.
"""

from __future__ import annotations

from typing import Any

from open_claude.services.mcp.config import (
    McpConfigLoader,
    add_mcp_config,
    add_mcp_json_config,
    describe_mcp_config_path,
    get_mcp_config,
    reset_project_mcp_choices,
    remove_mcp_config,
    set_mcp_server_disabled,
)
from open_claude.services.mcp.connection import (
    MCPConnectionManager,
    McpAuthError,
    McpSessionExpiredError,
    get_mcp_manager,
)
from open_claude.services.mcp.types import (
    ConfigScope,
    ConnectedMcpServer,
    DisabledMcpServer,
    FailedMcpServer,
    McpHTTPServerConfig,
    McpSSEServerConfig,
    McpServerConfig,
    McpStdioServerConfig,
    NeedsAuthMcpServer,
    ScopedMcpServerConfig,
)
from open_claude.tools.mcp_tool import McpTool, create_mcp_tools_from_discovery

__all__ = [
    # Public API
    "connect_mcp_servers",
    "disconnect_mcp_servers",
    "get_mcp_tools",
    "get_mcp_manager",
    # Config
    "McpConfigLoader",
    "add_mcp_config",
    "add_mcp_json_config",
    "get_mcp_config",
    "describe_mcp_config_path",
    "set_mcp_server_disabled",
    "reset_project_mcp_choices",
    "remove_mcp_config",
    # Types
    "ConfigScope",
    "McpStdioServerConfig",
    "McpSSEServerConfig",
    "McpHTTPServerConfig",
    "McpServerConfig",
    "ScopedMcpServerConfig",
    "ConnectedMcpServer",
    "FailedMcpServer",
    "NeedsAuthMcpServer",
    "DisabledMcpServer",
    # Errors
    "McpAuthError",
    "McpSessionExpiredError",
    # Tool
    "McpTool",
    "create_mcp_tools_from_discovery",
]

# Cache for discovered MCP tools
_mcp_tools_cache: list[McpTool] | None = None


async def connect_mcp_servers() -> None:
    """Connect to all configured MCP servers.

    Safe to call multiple times — subsequent calls are no-ops if already
    connected.
    """
    global _mcp_tools_cache
    manager = get_mcp_manager()
    await manager.connect_all()
    # Invalidate cache on reconnect
    _mcp_tools_cache = None


async def disconnect_mcp_servers() -> None:
    """Disconnect from all MCP servers and clear the tool cache."""
    global _mcp_tools_cache
    manager = get_mcp_manager()
    await manager.disconnect_all()
    _mcp_tools_cache = None


async def get_mcp_tools() -> list[McpTool]:
    """Return all MCP tools discovered from connected servers.

    Lazily connects to servers on first call. Results are cached until
    an explicit reconnect.
    """
    global _mcp_tools_cache

    if _mcp_tools_cache is not None:
        return _mcp_tools_cache

    manager = get_mcp_manager()

    # Ensure connected
    if not manager._connected:
        await connect_mcp_servers()

    # Discover tools from all servers
    tools_info = await manager.discover_all_tools()
    _mcp_tools_cache = create_mcp_tools_from_discovery(tools_info)

    return _mcp_tools_cache
