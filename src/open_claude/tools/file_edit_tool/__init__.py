"""FileEditTool - performs string replacements in files (name: 'Edit')."""

from __future__ import annotations

from pydantic import BaseModel, Field

from open_claude.schemas import ToolExecutionResult
from open_claude.tools.base import Tool, ToolError
from open_claude.tools.shared.utils import expand_path
from open_claude.utils.diff import build_file_diff_preview


class FileEditToolInput(BaseModel):
    """Input schema for FileEditTool."""

    file_path: str = Field(
        description="The absolute path to the file to modify"
    )
    old_string: str = Field(
        description="The text to replace"
    )
    new_string: str = Field(
        description="The text to replace it with (must be different from old_string)"
    )
    replace_all: bool = Field(
        default=False,
        description="Replace all occurrences of old_string (default false)",
    )


class FileEditTool(Tool):
    """Performs exact string replacements in files."""

    @property
    def name(self) -> str:
        return "Edit"

    @property
    def aliases(self) -> list[str]:
        return ["FileEdit"]

    @property
    def input_schema(self) -> type[BaseModel]:
        return FileEditToolInput

    @property
    def description(self) -> str:
        return (
            "Performs exact string replacements in files.\n"
            "\n"
            "Usage:\n"
            "- You must use your `Read` tool at least once in the conversation before editing. "
            "This tool will error if you attempt an edit without reading the file.\n"
            "- When editing text from Read tool output, ensure you preserve the exact indentation "
            "(tabs/spaces) as it appears AFTER the line number prefix. The line number prefix format is: "
            "line number + tab. Everything after that is the actual file content to match. Never include "
            "any part of the line number prefix in the old_string or new_string.\n"
            "- ALWAYS prefer editing existing files in the codebase. NEVER write new files unless "
            "explicitly required.\n"
            "- Only use emojis if the user explicitly requests it. Avoid adding emojis to files unless asked.\n"
            "- The edit will FAIL if `old_string` is not unique in the file. Either provide a larger "
            "string with more surrounding context to make it unique or use `replace_all` to change "
            "every instance of `old_string`.\n"
            "- Use `replace_all` for replacing and renaming strings across the file. This parameter is "
            "useful if you want to rename a variable for instance."
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return False

    def is_read_only(self, input_data: BaseModel) -> bool:
        return False

    async def call(self, input_data: BaseModel) -> str | ToolExecutionResult:
        data = input_data  # type: FileEditToolInput
        path = expand_path(data.file_path)

        if not path.exists():
            raise ToolError(f"File not found: {path}")

        if data.old_string == data.new_string:
            raise ToolError("old_string and new_string are identical. No changes needed.")

        # Read current content
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ToolError(f"Cannot read file as UTF-8 text: {path}")

        # Count occurrences
        count = content.count(data.old_string)
        if count == 0:
            raise ToolError(
                f"old_string not found in {path}. "
                f"Make sure the string matches exactly, including whitespace and indentation."
            )

        if not data.replace_all and count > 1:
            raise ToolError(
                f"old_string appears {count} times in {path}. "
                f"Use replace_all=true to replace all occurrences, "
                f"or provide more context to make old_string unique."
            )

        # Perform replacement
        if data.replace_all:
            new_content = content.replace(data.old_string, data.new_string)
            replaced = count
        else:
            new_content = content.replace(data.old_string, data.new_string, 1)
            replaced = 1

        # Write back
        preview = build_file_diff_preview(
            file_path=str(path),
            old_content=content,
            new_content=new_content,
            operation="edit",
        )

        try:
            path.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Failed to write file: {exc}")

        return ToolExecutionResult(
            output=f"Edited {path}: replaced {replaced} occurrence(s)",
            display_data=preview.to_display_data(
                title=f"Edit {path.name}",
                status="applied",
                dim=False,
            ),
        )
