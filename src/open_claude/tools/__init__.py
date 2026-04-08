"""Tool registry and dispatcher for the open-claude tool system."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from open_claude.tools.base import Tool, ToolError, find_tool_by_name
from open_claude.tools.file_read_tool import FileReadTool
from open_claude.tools.file_write_tool import FileWriteTool
from open_claude.tools.file_edit_tool import FileEditTool
from open_claude.tools.bash_tool import BashTool
from open_claude.tools.glob_tool import GlobTool
from open_claude.tools.grep_tool import GrepTool

logger = logging.getLogger(__name__)

__all__ = [
    "Tool",
    "ToolError",
    "get_builtin_tools",
    "get_all_tools",
    "get_tool_definitions",
    "create_tool_executor",
    "find_tool_by_name",
]


def _get_builtin_tools() -> list[Tool]:
    """Return built-in tool instances (non-MCP)."""
    return [
        FileReadTool(),
        FileWriteTool(),
        FileEditTool(),
        BashTool(),
        GlobTool(),
        GrepTool(),
    ]


def get_builtin_tools() -> list[Tool]:
    """Return enabled built-in tools only, without touching MCP."""
    return [t for t in _get_builtin_tools() if t.is_enabled()]


def _get_mcp_tools_sync() -> list[Tool]:
    """Attempt to load MCP tools synchronously.

    Returns an empty list if MCP is not available or not yet connected.
    This is safe to call from synchronous contexts — it will not block.
    """
    try:
        from open_claude.services.mcp import get_mcp_tools

        loop = asyncio.get_running_loop()
        if loop.is_running():
            # We're inside an async context — can't await here
            return []
    except RuntimeError:
        pass

    try:
        from open_claude.services.mcp import get_mcp_tools
        tools = asyncio.get_event_loop().run_until_complete(get_mcp_tools())
        return tools
    except Exception as exc:
        logger.debug("MCP tools not available: %s", exc)
        return []


async def get_all_tools_async() -> list[Tool]:
    """Return all tool instances including MCP tools (async version).

    Use this from async contexts to include dynamically discovered MCP tools.
    """
    builtin = get_builtin_tools()
    try:
        from open_claude.services.mcp import get_mcp_tools
        mcp_tools = await get_mcp_tools()
        return builtin + mcp_tools
    except Exception as exc:
        logger.debug("MCP tools unavailable: %s", exc)
        return builtin


def get_all_tools() -> list[Tool]:
    """Return all registered tool instances.

    Returns built-in tools plus any MCP tools that are already cached.
    For full MCP tool discovery, use :func:`get_all_tools_async` instead.
    """
    builtin = get_builtin_tools()
    mcp = _get_mcp_tools_sync()
    return builtin + mcp


def get_tool_definitions() -> list[dict[str, Any]]:
    """Return Anthropic API tool definitions for all enabled tools.

    Each definition is a dict with 'name', 'description', and 'input_schema'
    keys, suitable for the ``tools`` parameter of the Anthropic messages API.
    """
    return [t.get_api_definition() for t in get_all_tools()]


def create_tool_executor(
    tools: list[Tool] | None = None,
) -> Callable[[str, dict], Awaitable[str]]:
    """Create a tool_executor callback compatible with QueryEngine.

    The returned async callable matches the signature expected by
    ``QueryEngine.query_with_tool_loop()``::

        async (tool_name: str, tool_input: dict) -> str

    Args:
        tools: Optional list of Tool instances. Defaults to get_all_tools().

    Returns:
        An async function that validates input and dispatches to the right tool.
    """
    if tools is None:
        tools = get_all_tools()

    async def execute(tool_name: str, tool_input: dict) -> str:
        tool = find_tool_by_name(tools, tool_name)
        if tool is None:
            available = [t.name for t in tools]
            raise ToolError(
                f"No such tool: {tool_name}. Available tools: {available}"
            )

        # Validate input with Pydantic
        schema_cls = tool.input_schema
        try:
            validated = schema_cls.model_validate(tool_input)
        except Exception as exc:
            raise ToolError(
                f"InputValidationError for {tool_name}: {exc}"
            ) from exc

        # Execute the tool
        return await tool.call(validated)

    return execute
