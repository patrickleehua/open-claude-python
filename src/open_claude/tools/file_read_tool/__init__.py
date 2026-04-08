"""FileReadTool - reads files from the local filesystem (name: 'Read')."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError
from open_claude.tools.shared.utils import (
    expand_path,
    format_file_content,
    is_binary_extension,
)

MAX_LINES_DEFAULT = 2000
MAX_BYTE_SIZE = 1_048_576  # 1 MB


class FileReadToolInput(BaseModel):
    """Input schema for FileReadTool."""

    file_path: str = Field(description="The absolute path to the file to read")
    offset: int | None = Field(
        default=None,
        ge=0,
        description="Line number to start reading from",
    )
    limit: int | None = Field(
        default=None,
        gt=0,
        description="Number of lines to read",
    )
    pages: str | None = Field(
        default=None,
        description="Page range for PDF files (e.g. '1-5'). Only applicable to PDFs.",
    )


class FileReadTool(Tool):
    """Reads a file from the local filesystem."""

    @property
    def name(self) -> str:
        return "Read"

    @property
    def aliases(self) -> list[str]:
        return ["FileRead"]

    @property
    def input_schema(self) -> type[BaseModel]:
        return FileReadToolInput

    @property
    def description(self) -> str:
        return (
            "Reads a file from the local filesystem. You can access any file directly by using this tool.\n"
            "Assume this tool is able to read all files on the machine. If the User provides a path "
            "to a file assume that path is valid. It is okay to read a file that does not exist; "
            "an error will be returned.\n"
            "\n"
            "Usage:\n"
            "- The file_path parameter must be an absolute path, not a relative path\n"
            "- By default, it reads up to 2000 lines starting from the beginning of the file\n"
            "- You can optionally specify a line offset and limit (especially handy for long files), "
            "but it's recommended to read the whole file by not providing these parameters\n"
            "- Results are returned using cat -n format, with line numbers starting at 1\n"
            "- This tool allows Claude Code to read images (eg PNG, JPG, etc). When reading an image "
            "file the contents are presented visually as Claude Code is a multimodal LLM.\n"
            "- This tool can read PDF files (.pdf). For large PDFs (more than 10 pages), you MUST "
            'provide the pages parameter to read specific page ranges (e.g., pages: "1-5"). Reading '
            "a large PDF without the pages parameter will fail. Maximum 20 pages per request.\n"
            "- This tool can read Jupyter notebooks (.ipynb files) and returns all cells with their "
            "outputs, combining code, text, and visualizations.\n"
            "- This tool can only read files, not directories. To read a directory, use an ls command "
            "via the Bash tool.\n"
            "- You will regularly be asked to read screenshots. If the user provides a path to a "
            "screenshot, ALWAYS use this tool to view the file at the path. This tool will work with "
            "all temporary file paths.\n"
            "- If you read a file that exists but has empty contents you will receive a system reminder "
            "warning in place of file contents."
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return True

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: FileReadToolInput
        path = expand_path(data.file_path)

        if not path.exists():
            raise ToolError(f"File not found: {path}")

        if path.is_dir():
            raise ToolError(f"Path is a directory, not a file: {path}")

        if is_binary_extension(path):
            raise ToolError(
                f"Cannot read binary file: {path.suffix}. "
                f"Use Bash tool for binary files."
            )

        # Jupyter notebook
        if path.suffix.lower() == ".ipynb":
            return self._read_notebook(path)

        # Text file
        return self._read_text(path, data.offset, data.limit)

    def _read_text(self, path: Path, offset: int | None, limit: int | None) -> str:
        """Read a text file with optional offset/limit."""
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ToolError(
                f"Cannot read file as UTF-8 text: {path}. "
                f"The file may be binary."
            )

        file_size = len(content.encode("utf-8"))
        if file_size > MAX_BYTE_SIZE * 10:
            raise ToolError(
                f"File too large ({file_size:,} bytes). "
                f"Use offset and limit parameters to read in chunks."
            )

        lines = content.split("\n")
        # Remove trailing empty line from final newline
        if lines and lines[-1] == "":
            lines = lines[:-1]

        total_lines = len(lines)
        start = 0
        if offset is not None:
            start = min(offset, total_lines)
        end = total_lines
        if limit is not None:
            end = min(start + limit, total_lines)

        selected_lines = lines[start:end]
        if not selected_lines:
            return f"(empty, lines {start}-{start} of {total_lines})"

        text = "\n".join(selected_lines)
        formatted = format_file_content(text, start_line=start + 1)

        if offset is not None or limit is not None:
            formatted += f"\n(total {total_lines} lines)"

        return formatted

    def _read_notebook(self, path: Path) -> str:
        """Read a Jupyter notebook (.ipynb) file."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ToolError(f"Failed to parse notebook: {exc}")

        cells = data.get("cells", [])
        if not cells:
            return "(empty notebook)"

        parts: list[str] = []
        for i, cell in enumerate(cells):
            cell_type = cell.get("cell_type", "unknown")
            source = "".join(cell.get("source", []))

            if not source.strip():
                continue

            parts.append(f"--- Cell {i} ({cell_type}) ---")
            if cell_type == "code":
                outputs = cell.get("outputs", [])
                parts.append(source)
                for output in outputs:
                    output_type = output.get("output_type", "")
                    if output_type == "stream":
                        text = "".join(output.get("text", []))
                        if text.strip():
                            parts.append(f"# Output:\n{text.rstrip()}")
                    elif output_type in ("execute_result", "display_data"):
                        text_data = output.get("data", {})
                        if "text/plain" in text_data:
                            out = "".join(text_data["text/plain"]).rstrip()
                            parts.append(f"# Output:\n{out}")
            else:
                parts.append(source)

        return "\n\n".join(parts)
