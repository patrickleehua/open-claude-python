"""MCP tool/server name normalization and parsing utilities.

Pure functions with no external dependencies. Provides the `mcp__<server>__<tool>`
naming convention used throughout the MCP integration.
"""

from __future__ import annotations

import re


def normalize_name_for_mcp(name: str) -> str:
    """Normalize a name to be compatible with MCP tool name patterns.

    Replaces any character that is not alphanumeric, underscore, or hyphen
    with an underscore. Collapses consecutive underscores and strips
    leading/trailing underscores to prevent interference with the ``__``
    delimiter used in MCP tool names.
    """
    normalized = re.sub(r"[^a-zA-Z0-9_-]", "_", name)
    # Collapse consecutive underscores and strip edges
    normalized = re.sub(r"_+", "_", normalized)
    normalized = normalized.strip("_")
    return normalized


def build_mcp_tool_name(server_name: str, tool_name: str) -> str:
    """Build a fully qualified MCP tool name.

    Returns ``mcp__<server>__<tool>`` with both names normalized.
    Inverse of :func:`parse_mcp_tool_name`.
    """
    return f"mcp__{normalize_name_for_mcp(server_name)}__{normalize_name_for_mcp(tool_name)}"


def parse_mcp_tool_name(full_name: str) -> tuple[str, str] | None:
    """Parse an MCP tool name into (server_name, tool_name).

    Returns ``None`` if the name does not follow the ``mcp__<server>__<tool>``
    convention.

    Known limitation: If a server name contains ``__``, parsing will be
    incorrect. The split takes the first segment after ``mcp__`` as server
    name and joins the rest as tool name.
    """
    if not full_name.startswith("mcp__"):
        return None
    rest = full_name[5:]  # strip "mcp__"
    parts = rest.split("__", 1)
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    return (parts[0], parts[1])


def is_mcp_tool_name(name: str) -> bool:
    """Check if a name follows the MCP tool naming convention."""
    return name.startswith("mcp__") and parse_mcp_tool_name(name) is not None


def get_mcp_prefix(server_name: str) -> str:
    """Return the ``mcp__<server>__`` prefix for a given server."""
    return f"mcp__{normalize_name_for_mcp(server_name)}__"


def get_mcp_display_name(full_name: str, server_name: str) -> str:
    """Strip the MCP prefix to get the display tool name."""
    prefix = get_mcp_prefix(server_name)
    if full_name.startswith(prefix):
        return full_name[len(prefix):]
    return full_name
