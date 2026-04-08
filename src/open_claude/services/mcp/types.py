"""Pydantic schemas for MCP server configuration and connection state.

Mirrors the TypeScript types from Claude-Code-rev ``services/mcp/types.ts``,
adapted for Pydantic v2 and the subset of transports supported by the Python
MCP SDK (stdio, sse, http).
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Configuration scope
# ---------------------------------------------------------------------------

class ConfigScope(str, Enum):
    """Where an MCP server configuration comes from.

    Ordered by precedence (higher wins on conflict).
    """

    LOCAL = "local"
    USER = "user"
    PROJECT = "project"
    ENTERPRISE = "enterprise"


# ---------------------------------------------------------------------------
# OAuth configuration (nested inside SSE/HTTP configs)
# ---------------------------------------------------------------------------

class McpOAuthConfig(BaseModel):
    """OAuth parameters for a remote MCP server."""

    client_id: str | None = None
    callback_port: int | None = None
    auth_server_metadata_url: str | None = None


# ---------------------------------------------------------------------------
# Server configuration schemas (discriminated union on ``type``)
# ---------------------------------------------------------------------------

class McpStdioServerConfig(BaseModel):
    """Configuration for a stdio-based MCP server (subprocess)."""

    type: Literal["stdio"] = "stdio"
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] | None = None


class McpSSEServerConfig(BaseModel):
    """Configuration for an SSE-based MCP server."""

    type: Literal["sse"] = "sse"
    url: str
    headers: dict[str, str] | None = None
    oauth: McpOAuthConfig | None = None


class McpHTTPServerConfig(BaseModel):
    """Configuration for a Streamable HTTP MCP server."""

    type: Literal["http"] = "http"
    url: str
    headers: dict[str, str] | None = None
    oauth: McpOAuthConfig | None = None


# Discriminated union of all supported server config types
McpServerConfig = Annotated[
    Union[McpStdioServerConfig, McpSSEServerConfig, McpHTTPServerConfig],
    Field(discriminator="type"),
]


class ScopedMcpServerConfig(BaseModel):
    """A server configuration together with its source scope."""

    config: McpServerConfig
    scope: ConfigScope


# ---------------------------------------------------------------------------
# .mcp.json file schema
# ---------------------------------------------------------------------------

class McpJsonFile(BaseModel):
    """Schema for ``.mcp.json`` project configuration files."""

    mcpServers: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Connection state types (runtime, not persisted)
# ---------------------------------------------------------------------------

class ConnectedMcpServer:
    """A successfully connected MCP server with an active session."""

    __slots__ = ("name", "session", "server_info", "capabilities", "instructions", "cleanup")

    def __init__(
        self,
        name: str,
        session: Any,  # mcp.ClientSession
        server_info: Any | None = None,  # mcp.types.Implementation
        capabilities: Any | None = None,  # mcp.types.ServerCapabilities
        instructions: str | None = None,
        cleanup: Any | None = None,  # Callable[[], Awaitable[None]]
    ) -> None:
        self.name = name
        self.session = session
        self.server_info = server_info
        self.capabilities = capabilities
        self.instructions = instructions
        self.cleanup = cleanup


class FailedMcpServer:
    """An MCP server that failed to connect."""

    __slots__ = ("name", "error")

    def __init__(self, name: str, error: str) -> None:
        self.name = name
        self.error = error


class NeedsAuthMcpServer:
    """An MCP server that requires OAuth authentication."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


class DisabledMcpServer:
    """An MCP server explicitly disabled by the user."""

    __slots__ = ("name",)

    def __init__(self, name: str) -> None:
        self.name = name


# Union of all connection states
McpServerConnection = ConnectedMcpServer | FailedMcpServer | NeedsAuthMcpServer | DisabledMcpServer
