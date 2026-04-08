"""MCP connection manager — orchestrates server connections, tool discovery, and execution.

Manages the lifecycle of MCP server connections:
1. Load configs via :class:`McpConfigLoader`
2. Create transports (stdio/sse/http) using the Python MCP SDK
3. Establish ``ClientSession`` and call ``initialize()``
4. Discover tools via ``session.list_tools()``
5. Route tool calls through ``session.call_tool()``

Each server connection runs in its own background task, keeping the anyio
task scopes consistent (enter/exit within the same task).
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

from open_claude.services.mcp.config import McpConfigLoader
from open_claude.services.mcp.types import (
    ConnectedMcpServer,
    DisabledMcpServer,
    FailedMcpServer,
    McpHTTPServerConfig,
    McpSSEServerConfig,
    McpStdioServerConfig,
    McpServerConnection,
    NeedsAuthMcpServer,
    ScopedMcpServerConfig,
)

logger = logging.getLogger(__name__)

# Concurrency limits for connection batching
_LOCAL_CONCURRENCY = 3
_REMOTE_CONCURRENCY = 20
_LOCAL_CONNECT_TIMEOUT_SECONDS = 15
_REMOTE_CONNECT_TIMEOUT_SECONDS = 30


class McpSessionExpiredError(Exception):
    """Raised when an MCP session has expired (server returned 404)."""


class McpAuthError(Exception):
    """Raised when an MCP server requires authentication."""

    def __init__(self, server_name: str, message: str = "") -> None:
        self.server_name = server_name
        super().__init__(message or f"MCP server '{server_name}' requires authentication")


class MCPConnectionManager:
    """Manages connections to all configured MCP servers.

    Each connection runs in a dedicated background asyncio Task that owns
    the ``AsyncExitStack`` — this avoids the anyio "cancel scope in
    different task" error that occurs when the stack is shared.
    """

    def __init__(self) -> None:
        self._config_loader = McpConfigLoader()
        self._connections: dict[str, McpServerConnection] = {}
        self._connected = False
        self._lock = asyncio.Lock()
        # Per-server background tasks and their exit stacks
        self._server_tasks: dict[str, asyncio.Task[None]] = {}
        self._server_stacks: dict[str, AsyncExitStack] = {}
        # Events to signal when a server's session is ready
        self._ready_events: dict[str, asyncio.Event] = {}

    @property
    def connections(self) -> dict[str, McpServerConnection]:
        return dict(self._connections)

    async def connect_all(self) -> None:
        """Connect to all configured and enabled MCP servers."""
        async with self._lock:
            if self._connected:
                return

            configs = self._config_loader.get_all_configs()

            for name, scoped in configs.items():
                if self._config_loader.is_server_disabled(name):
                    self._connections[name] = DisabledMcpServer(name)
                    continue

                config = scoped.config
                is_local = isinstance(config, McpStdioServerConfig)
                sem = asyncio.Semaphore(_LOCAL_CONCURRENCY if is_local else _REMOTE_CONCURRENCY)

                # Create ready event
                evt = asyncio.Event()
                self._ready_events[name] = evt

                # Launch background task
                task = asyncio.create_task(
                    self._server_lifecycle(name, scoped, sem, evt)
                )
                self._server_tasks[name] = task

            # Wait for all servers to become ready (or fail)
            if self._ready_events:
                await asyncio.gather(
                    *[evt.wait() for evt in self._ready_events.values()],
                    return_exceptions=True,
                )

            self._connected = True

    async def _server_lifecycle(
        self,
        name: str,
        scoped: ScopedMcpServerConfig,
        sem: asyncio.Semaphore,
        ready_event: asyncio.Event,
    ) -> None:
        """Run a single server connection in its own task.

        The ``AsyncExitStack`` lives entirely within this task, so
        enter/exit happen in the same anyio task scope.
        """
        async with sem:
            stack = AsyncExitStack()
            self._server_stacks[name] = stack
            timeout_seconds = self._get_connect_timeout_seconds(scoped)
            try:
                await stack.__aenter__()
                session = await asyncio.wait_for(
                    self._connect_to_server(name, scoped, stack),
                    timeout=timeout_seconds,
                )

                init_result = await asyncio.wait_for(
                    session.initialize(),
                    timeout=timeout_seconds,
                )

                self._connections[name] = ConnectedMcpServer(
                    name=name,
                    session=session,
                    server_info=init_result.serverInfo,
                    capabilities=init_result.capabilities,
                    instructions=init_result.instructions,
                    cleanup=None,
                )
            except asyncio.TimeoutError:
                message = f"connection timed out after {timeout_seconds}s"
                logger.warning("MCP server '%s' %s", name, message)
                self._connections[name] = FailedMcpServer(name, message)
            except McpAuthError:
                self._connections[name] = NeedsAuthMcpServer(name)
            except Exception as exc:
                logger.warning("MCP server '%s' connection failed: %s", name, exc)
                self._connections[name] = FailedMcpServer(name, str(exc))
            finally:
                ready_event.set()

            # Keep the task alive so the context managers stay open
            try:
                await asyncio.Future()  # block forever
            except asyncio.CancelledError:
                pass
            finally:
                # Clean up the stack within the same task
                try:
                    await stack.__aexit__(None, None, None)
                except Exception:
                    pass
                self._server_stacks.pop(name, None)
                self._connections.pop(name, None)

    def _get_connect_timeout_seconds(self, scoped: ScopedMcpServerConfig) -> float:
        config = scoped.config
        if isinstance(config, McpStdioServerConfig):
            return _LOCAL_CONNECT_TIMEOUT_SECONDS
        return _REMOTE_CONNECT_TIMEOUT_SECONDS

    async def _connect_to_server(
        self, name: str, scoped: ScopedMcpServerConfig, stack: AsyncExitStack
    ) -> ClientSession:
        """Create a transport and session, managed by the given stack."""
        config = scoped.config

        if isinstance(config, McpStdioServerConfig):
            return await self._connect_stdio(name, config, stack)
        elif isinstance(config, McpSSEServerConfig):
            return await self._connect_sse(name, config, stack)
        elif isinstance(config, McpHTTPServerConfig):
            return await self._connect_http(name, config, stack)
        else:
            raise ValueError(f"Unsupported config type for server '{name}'")

    async def _connect_stdio(
        self, name: str, config: McpStdioServerConfig, stack: AsyncExitStack
    ) -> ClientSession:
        params = StdioServerParameters(
            command=config.command,
            args=config.args,
            env={
                **{k: v for k, v in os.environ.items()},
                **(config.env or {}),
            },
        )
        read_stream, write_stream = await stack.enter_async_context(
            stdio_client(params)
        )
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        return session

    async def _connect_sse(
        self, name: str, config: McpSSEServerConfig, stack: AsyncExitStack
    ) -> ClientSession:
        read_stream, write_stream = await stack.enter_async_context(
            sse_client(
                url=config.url,
                headers=config.headers or {},
            )
        )
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        return session

    async def _connect_http(
        self, name: str, config: McpHTTPServerConfig, stack: AsyncExitStack
    ) -> ClientSession:
        read_stream, write_stream, _ = await stack.enter_async_context(
            streamable_http_client(url=config.url)
        )
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        return session

    async def discover_tools(self, server_name: str) -> list[dict[str, Any]]:
        """Discover tools from a connected MCP server."""
        conn = self._connections.get(server_name)
        if not isinstance(conn, ConnectedMcpServer):
            return []

        if not conn.capabilities or not conn.capabilities.tools:
            return []

        try:
            result = await conn.session.list_tools()
        except Exception as exc:
            logger.warning("Failed to list tools from '%s': %s", server_name, exc)
            return []

        tools_info: list[dict[str, Any]] = []
        for tool in result.tools:
            tools_info.append({
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema or {"type": "object", "properties": {}},
                "annotations": (
                    tool.annotations.model_dump(exclude_none=True)
                    if tool.annotations
                    else {}
                ),
            })
        return tools_info

    async def discover_all_tools(self) -> list[dict[str, Any]]:
        """Discover tools from all connected servers."""
        all_tools: list[dict[str, Any]] = []
        for name, conn in list(self._connections.items()):
            if isinstance(conn, ConnectedMcpServer):
                server_tools = await self.discover_tools(name)
                for t in server_tools:
                    t["server_name"] = name
                all_tools.extend(server_tools)
        return all_tools

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> str:
        """Execute a tool on a connected MCP server."""
        conn = self._connections.get(server_name)

        if not isinstance(conn, ConnectedMcpServer):
            if isinstance(conn, NeedsAuthMcpServer):
                raise McpAuthError(server_name)
            raise RuntimeError(f"MCP server '{server_name}' is not connected")

        try:
            result = await conn.session.call_tool(tool_name, arguments)
        except Exception as exc:
            error_str = str(exc)
            if "404" in error_str or "Session not found" in error_str:
                raise McpSessionExpiredError(
                    f"Session expired for '{server_name}'"
                ) from exc
            if "401" in error_str or "Unauthorized" in error_str:
                self._connections[server_name] = NeedsAuthMcpServer(server_name)
                raise McpAuthError(server_name, error_str) from exc
            raise

        # Convert result content to string
        parts: list[str] = []
        for block in result.content:
            if hasattr(block, "text"):
                parts.append(block.text)
            elif hasattr(block, "data"):
                parts.append(f"[binary data: {getattr(block, 'mimeType', 'unknown')}]")
            else:
                parts.append(str(block))

        return "\n".join(parts) if parts else ""

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers and clean up."""
        async with self._lock:
            if not self._connected:
                return

            # Cancel all background tasks
            for task in self._server_tasks.values():
                task.cancel()
            # Wait for cancellation
            if self._server_tasks:
                await asyncio.gather(
                    *self._server_tasks.values(), return_exceptions=True
                )
            self._server_tasks.clear()
            self._server_stacks.clear()
            self._ready_events.clear()
            self._connections.clear()
            self._connected = False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_manager: MCPConnectionManager | None = None


def get_mcp_manager() -> MCPConnectionManager:
    """Return the global MCP connection manager singleton."""
    global _manager
    if _manager is None:
        _manager = MCPConnectionManager()
    return _manager
