"""WebSearchTool - web search for up-to-date information (name: 'WebSearch')."""

from __future__ import annotations

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError


class WebSearchToolInput(BaseModel):
    """Input schema for WebSearchTool."""

    query: str = Field(
        description="The search query to use"
    )
    allowed_domains: list[str] | None = Field(
        default=None,
        description="Only include search results from these domains",
    )
    blocked_domains: list[str] | None = Field(
        default=None,
        description="Never include search results from these domains",
    )


class WebSearchTool(Tool):
    """Allows Claude to search the web and use the results to inform responses."""

    @property
    def name(self) -> str:
        return "WebSearch"

    @property
    def input_schema(self) -> type[BaseModel]:
        return WebSearchToolInput

    @property
    def description(self) -> str:
        return (
            "- Allows Claude to search the web and use the results to inform responses\n"
            "- Provides up-to-date information for current events and recent data\n"
            "- Returns search result information formatted as search result blocks, including links as markdown hyperlinks\n"
            "- Use this tool for accessing information beyond Claude's knowledge cutoff\n"
            "- Searches are performed automatically within a single API call\n"
            "\n"
            "CRITICAL REQUIREMENT - You MUST follow this:\n"
            '  - After answering the user\'s question, you MUST include a "Sources:" section at the end of your response\n'
            "  - In the Sources section, list all relevant URLs from the search results as markdown hyperlinks: [Title](URL)\n"
            "  - This is MANDATORY - never skip including sources in your response\n"
            "  - Example format:\n"
            "\n"
            "    [Your answer here]\n"
            "\n"
            "    Sources:\n"
            "    - [Source Title 1](https://example.com/1)\n"
            "    - [Source Title 2](https://example.com/2)\n"
            "\n"
            "Usage notes:\n"
            "  - Domain filtering is supported to include or block specific websites\n"
            "  - Web search is only available in the US\n"
            "\n"
            "IMPORTANT - Use the correct year in search queries:\n"
            "  - The current month is April 2026. You MUST use this year when searching for "
            "recent information, documentation, or current events.\n"
            '  - Example: If the user asks for "latest React docs", search for "React documentation" '
            "with the current year, NOT last year"
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return True

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: WebSearchToolInput
        raise ToolError(
            "WebSearch is not yet implemented in open-claude-python. "
            "Use an MCP-provided web search tool instead."
        )
