"""Tool base class and error types for the tool system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel

from open_claude.schemas import ToolExecutionResult


class ToolError(Exception):
    """Raised when a tool encounters an error during execution."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class Tool(ABC):
    """Abstract base class for all tools available to the model.

    Each tool must implement:
    - name: unique identifier the model uses to invoke it
    - input_schema: Pydantic model for input validation
    - description: text description included in the API tool definition
    - call(): async execution that returns a string result

    Optional overrides with safe defaults (matching TS TOOL_DEFAULTS):
    - is_concurrency_safe() -> False (fail-closed)
    - is_read_only() -> False (fail-closed)
    - is_enabled() -> True
    - aliases -> []
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Primary tool name used by the model (e.g. 'Read', 'Bash')."""
        ...

    @property
    def aliases(self) -> list[str]:
        """Optional alternative names for backwards compatibility."""
        return []

    @property
    @abstractmethod
    def input_schema(self) -> type[BaseModel]:
        """Pydantic model class for input validation."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description included in the API tool definition."""
        ...

    @abstractmethod
    async def call(self, input_data: BaseModel) -> str | ToolExecutionResult:
        """Execute the tool and return a string result for the model.

        Args:
            input_data: Validated Pydantic model instance matching input_schema.

        Returns:
            String output or a structured tool result to send back to the model.
        """
        ...

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        """Whether this tool call can run in parallel with others. Default: False."""
        return False

    def is_read_only(self, input_data: BaseModel) -> bool:
        """Whether this tool only reads, never writes. Default: False."""
        return False

    def is_enabled(self) -> bool:
        """Whether the tool is currently available. Default: True."""
        return True

    def get_api_definition(self) -> dict[str, Any]:
        """Generate the Anthropic API tool definition dict.

        Returns a dict with 'name', 'description', and 'input_schema' keys
        suitable for passing as the ``tools`` parameter to the API.
        """
        schema = self.input_schema.model_json_schema()
        # Anthropic API requires input_schema to be of type "object"
        if "type" not in schema:
            schema["type"] = "object"
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": schema,
        }


def find_tool_by_name(tools: list[Tool], name: str) -> Tool | None:
    """Find a tool by primary name or alias."""
    for tool in tools:
        if tool.name == name or name in tool.aliases:
            return tool
    return None
