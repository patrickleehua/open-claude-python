"""MCP tool wrapper — adapts discovered MCP tools to the Tool ABC.

Each tool discovered from an MCP server is wrapped as an :class:`McpTool`
instance that:
- Uses the ``mcp__<server>__<tool>`` naming convention
- Generates a dynamic Pydantic model from the tool's JSON Schema input
- Delegates ``call()`` to :class:`MCPConnectionManager`
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import BaseModel, Field, create_model

from open_claude.tools.base import Tool, ToolError
from open_claude.utils.mcp.naming import (
    build_mcp_tool_name,
    get_mcp_display_name,
    normalize_name_for_mcp,
)

logger = logging.getLogger(__name__)

# Maximum description length (matches TS truncation)
_MAX_DESCRIPTION_LENGTH = 2048


def _json_schema_to_pydantic(
    schema: dict[str, Any], model_name: str
) -> type[BaseModel]:
    """Convert a JSON Schema dict to a Pydantic model class.

    For complex schemas, falls back to a generic ``arguments`` dict field
    so that any JSON-serialisable input is accepted.
    """
    if not isinstance(schema, dict):
        schema = {"type": "object", "properties": {}}

    properties = schema.get("properties", {})
    if not properties:
        # No properties defined — accept arbitrary dict
        return create_model(
            model_name,
            arguments=(dict | None, Field(default=None, description="Tool arguments")),
        )

    # Build field definitions from properties
    field_definitions: dict[str, Any] = {}
    required = set(schema.get("required", []))

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            field_definitions[prop_name] = (Any, Field(default=None))
            continue

        prop_type = prop_schema.get("type", "string")
        description = prop_schema.get("description", "")
        default = ... if prop_name in required else None

        # Map JSON Schema types to Python types
        type_map: dict[str, Any] = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        python_type = type_map.get(prop_type, Any)

        if prop_name not in required:
            field_definitions[prop_name] = (
                python_type | None,
                Field(default=default, description=description),
            )
        else:
            field_definitions[prop_name] = (
                python_type,
                Field(default=default, description=description),
            )

    try:
        return create_model(model_name, **field_definitions)
    except Exception:
        # Fallback for schemas that create_model can't handle
        logger.debug("Falling back to generic model for %s", model_name)
        return create_model(
            model_name,
            arguments=(dict | None, Field(default=None, description="Tool arguments")),
        )


class McpTool(Tool):
    """A tool discovered from an MCP server, adapted to the Tool ABC.

    Attributes:
        server_name: The MCP server that provides this tool.
        original_name: The tool name as reported by the MCP server.
    """

    def __init__(
        self,
        server_name: str,
        original_name: str,
        description: str,
        input_schema_dict: dict[str, Any],
        annotations: dict[str, Any] | None = None,
    ) -> None:
        self._server_name = server_name
        self._original_name = original_name
        self._description = description[:_MAX_DESCRIPTION_LENGTH]
        self._input_schema_dict = input_schema_dict
        self._annotations = annotations or {}
        # Lazily created Pydantic model
        self._schema_cls: type[BaseModel] | None = None

    @property
    def server_name(self) -> str:
        return self._server_name

    @property
    def original_name(self) -> str:
        return self._original_name

    @property
    def name(self) -> str:
        return build_mcp_tool_name(self._server_name, self._original_name)

    @property
    def input_schema(self) -> type[BaseModel]:
        if self._schema_cls is None:
            model_name = f"McpInput_{normalize_name_for_mcp(self._server_name)}_{normalize_name_for_mcp(self._original_name)}"
            self._schema_cls = _json_schema_to_pydantic(
                self._input_schema_dict, model_name
            )
        return self._schema_cls

    @property
    def description(self) -> str:
        return self._description

    def is_read_only(self, input_data: BaseModel) -> bool:
        """Check the readOnlyHint annotation from the MCP server."""
        return bool(self._annotations.get("readOnlyHint", False))

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        """MCP tools are generally safe to run concurrently unless annotated otherwise."""
        return not self._annotations.get("destructiveHint", False)

    async def call(self, input_data: BaseModel) -> str:
        """Execute this tool via the MCP connection manager."""
        from open_claude.services.mcp.connection import McpAuthError, McpSessionExpiredError, get_mcp_manager

        # Extract arguments — handle both typed and generic models
        if hasattr(input_data, "arguments") and input_data.arguments is not None:
            arguments = input_data.arguments
        else:
            arguments = input_data.model_dump(exclude_none=True)

        manager = get_mcp_manager()
        try:
            return await manager.call_tool(
                self._server_name, self._original_name, arguments
            )
        except McpAuthError as exc:
            raise ToolError(f"Authentication required for MCP server '{exc.server_name}'. "
                          f"Please re-authenticate.") from exc
        except McpSessionExpiredError:
            # Try reconnecting once
            try:
                await manager.disconnect_all()
                await manager.connect_all()
                return await manager.call_tool(
                    self._server_name, self._original_name, arguments
                )
            except Exception as retry_exc:
                raise ToolError(
                    f"MCP tool '{self.name}' failed after reconnection: {retry_exc}"
                ) from retry_exc
        except Exception as exc:
            raise ToolError(f"MCP tool '{self.name}' error: {exc}") from exc


def create_mcp_tools_from_discovery(
    tools_info: list[dict[str, Any]],
) -> list[McpTool]:
    """Create McpTool instances from discovered tool info dicts.

    Each dict should have keys: ``server_name``, ``name``, ``description``,
    ``input_schema``, ``annotations``.
    """
    result: list[McpTool] = []
    seen: set[str] = set()

    for info in tools_info:
        server_name = info["server_name"]
        tool_name = info["name"]
        full_name = build_mcp_tool_name(server_name, tool_name)

        if full_name in seen:
            logger.warning(
                "Duplicate MCP tool name '%s', skipping", full_name
            )
            continue
        seen.add(full_name)

        result.append(
            McpTool(
                server_name=server_name,
                original_name=tool_name,
                description=info.get("description", ""),
                input_schema_dict=info.get("input_schema", {"type": "object", "properties": {}}),
                annotations=info.get("annotations"),
            )
        )

    return result
