"""MCP skill builders - write-once registry for MCP skill discovery.

Port of Claude-Code-rev/src/skills/mcpSkillBuilders.ts

Breaks dependency cycle between mcpSkills and load_skills_dir.
"""

from __future__ import annotations

from typing import Any, Callable


class MCPSkillBuilders:
    """Holds references to create_skill_command and parse_skill_frontmatter_fields."""

    def __init__(
        self,
        create_skill_command: Callable[..., Any],
        parse_skill_frontmatter_fields: Callable[..., Any],
    ) -> None:
        self.create_skill_command = create_skill_command
        self.parse_skill_frontmatter_fields = parse_skill_frontmatter_fields


_builders: MCPSkillBuilders | None = None


def register_mcp_skill_builders(builders: MCPSkillBuilders) -> None:
    """Register MCP skill builders (called from load_skills_dir at module init)."""
    global _builders
    _builders = builders


def get_mcp_skill_builders() -> MCPSkillBuilders:
    """Get MCP skill builders, raising if not yet registered."""
    if _builders is None:
        raise RuntimeError(
            "MCP skill builders not registered — load_skills_dir not yet evaluated"
        )
    return _builders
