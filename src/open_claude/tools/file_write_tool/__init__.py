"""FileWriteTool - writes/creates files on the local filesystem (name: 'Write')."""

from __future__ import annotations

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError
from open_claude.tools.shared.utils import expand_path


class FileWriteToolInput(BaseModel):
    """Input schema for FileWriteTool."""

    file_path: str = Field(
        description="The absolute path to the file to write (must be absolute, not relative)"
    )
    content: str = Field(
        description="The content to write to the file"
    )


class FileWriteTool(Tool):
    """Writes a file to the local filesystem."""

    @property
    def name(self) -> str:
        return "Write"

    @property
    def aliases(self) -> list[str]:
        return ["FileWrite"]

    @property
    def input_schema(self) -> type[BaseModel]:
        return FileWriteToolInput

    @property
    def description(self) -> str:
        return (
            "Writes a file to the local filesystem.\n"
            "\n"
            "Usage:\n"
            "- This tool will overwrite the existing file if there is one at the provided path.\n"
            "- If this is an existing file, you MUST use the Read tool first to read the file's "
            "contents. This tool will fail if you did not read the file first.\n"
            "- Prefer the Edit tool for modifying existing files \u2014 it only sends the diff. "
            "Only use this tool to create new files or for complete rewrites.\n"
            "- NEVER create documentation files (*.md) or README files unless explicitly requested "
            "by the User.\n"
            "- Only use emojis if the user explicitly requests it. Avoid writing emojis to files "
            "unless asked."
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return False

    def is_read_only(self, input_data: BaseModel) -> bool:
        return False

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: FileWriteToolInput
        path = expand_path(data.file_path)

        if not path.is_absolute():
            raise ToolError(f"File path must be absolute, not relative: {data.file_path}")

        # Create parent directories if needed
        path.parent.mkdir(parents=True, exist_ok=True)

        # Determine create vs update
        is_update = path.exists()

        # Write content
        try:
            path.write_text(data.content, encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Failed to write file: {exc}")

        action = "updated" if is_update else "created"
        line_count = data.content.count("\n") + (
            1 if data.content and not data.content.endswith("\n") else 0
        )
        return f"File {action} successfully: {path} ({line_count} lines)"
