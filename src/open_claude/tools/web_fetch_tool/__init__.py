"""WebFetchTool - fetches and processes web content (name: 'WebFetch')."""

from __future__ import annotations

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError


class WebFetchToolInput(BaseModel):
    """Input schema for WebFetchTool."""

    url: str = Field(
        description="The URL to fetch"
    )
    prompt: str = Field(
        description="The prompt to run on the fetched content"
    )


class WebFetchTool(Tool):
    """Fetches content from a URL and processes it."""

    @property
    def name(self) -> str:
        return "WebFetch"

    @property
    def input_schema(self) -> type[BaseModel]:
        return WebFetchToolInput

    @property
    def description(self) -> str:
        return (
            "- Fetches content from a specified URL and processes it using an AI model\n"
            "- Takes a URL and a prompt as input\n"
            "- Fetches the URL content, converts HTML to markdown\n"
            "- Processes the content with the prompt using a small, fast model\n"
            "- Returns the model's response about the content\n"
            "- Use this tool when you need to retrieve and analyze web content\n"
            "\n"
            "Usage notes:\n"
            "  - IMPORTANT: If an MCP-provided web fetch tool is available, prefer using that tool "
            "instead of this one, as it may have fewer restrictions.\n"
            "  - The URL must be a fully-formed valid URL\n"
            "  - HTTP URLs will be automatically upgraded to HTTPS\n"
            "  - The prompt should describe what information you want to extract from the page\n"
            "  - This tool is read-only and does not modify any files\n"
            "  - Results may be summarized if the content is very large\n"
            "  - Includes a self-cleaning 15-minute cache for faster responses when repeatedly "
            "accessing the same URL\n"
            "  - When a URL redirects to a different host, the tool will inform you and provide "
            "the redirect URL in a special format. You should then make a new WebFetch request "
            "with the redirect URL to fetch the content.\n"
            "  - For GitHub URLs, prefer using the gh CLI via Bash instead (e.g., gh pr view, "
            "gh issue view, gh api)."
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return True

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: WebFetchToolInput
        raise ToolError(
            "WebFetch is not yet implemented in open-claude-python. "
            "Use an MCP-provided web fetch tool instead."
        )
