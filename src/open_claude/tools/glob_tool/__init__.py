"""GlobTool - fast file pattern matching (name: 'Glob')."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError
from open_claude.tools.shared.utils import expand_path, to_relative_path

MAX_RESULTS = 100


class GlobToolInput(BaseModel):
    """Input schema for GlobTool."""

    pattern: str = Field(
        description="The glob pattern to match files against (e.g. '**/*.js', 'src/**/*.ts')"
    )
    path: str | None = Field(
        default=None,
        description="The directory to search in. Defaults to CWD. Must be a valid directory if provided.",
    )


class GlobTool(Tool):
    """Fast file pattern matching tool."""

    @property
    def name(self) -> str:
        return "Glob"

    @property
    def aliases(self) -> list[str]:
        return ["FileGlob"]

    @property
    def input_schema(self) -> type[BaseModel]:
        return GlobToolInput

    @property
    def description(self) -> str:
        return (
            "- Fast file pattern matching tool that works with any codebase size\n"
            '- Supports glob patterns like "**/*.js" or "src/**/*.ts"\n'
            "- Returns matching file paths sorted by modification time\n"
            "- Use this tool when you need to find files by name patterns\n"
            "- When you are doing an open ended search that may require multiple rounds "
            "of globbing and grepping, use the Agent tool instead"
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return True

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: GlobToolInput

        # Resolve search directory
        if data.path:
            search_dir = expand_path(data.path)
            if not search_dir.exists():
                raise ToolError(f"Directory not found: {search_dir}")
            if not search_dir.is_dir():
                raise ToolError(f"Path is not a directory: {search_dir}")
        else:
            search_dir = Path.cwd()

        # Collect matches
        try:
            matches = list(search_dir.glob(data.pattern))
        except ValueError as exc:
            raise ToolError(f"Invalid glob pattern '{data.pattern}': {exc}")

        # Filter to files only
        matches = [p for p in matches if p.is_file()]

        # Sort by modification time (newest first)
        try:
            matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        except OSError:
            matches.sort(key=lambda p: p.name)

        # Apply limit
        truncated = len(matches) > MAX_RESULTS
        matches = matches[:MAX_RESULTS]

        if not matches:
            return "No files matched the pattern."

        # Relativize paths
        filenames = [to_relative_path(p, search_dir) for p in matches]

        header = f"Found {len(matches)} file(s)"
        if truncated:
            header += f" (showing first {MAX_RESULTS})"
        return header + "\n" + "\n".join(filenames)
