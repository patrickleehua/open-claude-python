"""NotebookEditTool - replaces cells in Jupyter notebooks (name: 'NotebookEdit')."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError
from open_claude.tools.shared.utils import expand_path


class NotebookEditToolInput(BaseModel):
    """Input schema for NotebookEditTool."""

    notebook_path: str = Field(
        description="The absolute path to the Jupyter notebook file to edit (must be absolute, not relative)"
    )
    cell_number: int = Field(
        description="The 0-indexed cell number to edit"
    )
    new_source: str = Field(
        description="The new source for the cell"
    )
    cell_type: str | None = Field(
        default=None,
        description="The type of the cell (code or markdown). Defaults to the current cell type.",
    )
    edit_mode: str = Field(
        default="replace",
        description="The type of edit to make: 'replace', 'insert', or 'delete'",
    )
    cell_id: str | None = Field(
        default=None,
        description="The ID of the cell to edit. When inserting a new cell, the new cell will be inserted after this cell.",
    )


class NotebookEditTool(Tool):
    """Completely replaces the contents of a specific cell in a Jupyter notebook."""

    @property
    def name(self) -> str:
        return "NotebookEdit"

    @property
    def input_schema(self) -> type[BaseModel]:
        return NotebookEditToolInput

    @property
    def description(self) -> str:
        return (
            "Completely replaces the contents of a specific cell in a Jupyter notebook (.ipynb file) "
            "with new source. Jupyter notebooks are interactive documents that combine code, text, "
            "and visualizations, commonly used for data analysis and scientific computing. "
            "The notebook_path parameter must be an absolute path, not a relative path. "
            "The cell_number is 0-indexed. Use edit_mode=insert to add a new cell at the index "
            "specified by cell_number. Use edit_mode=delete to delete the cell at the index "
            "specified by cell_number."
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return False

    def is_read_only(self, input_data: BaseModel) -> bool:
        return False

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: NotebookEditToolInput
        path = expand_path(data.notebook_path)

        if not path.exists():
            raise ToolError(f"Notebook not found: {path}")

        if not path.is_absolute():
            raise ToolError(f"Notebook path must be absolute, not relative: {data.notebook_path}")

        # Read notebook
        try:
            content = path.read_text(encoding="utf-8")
            nb = json.loads(content)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ToolError(f"Failed to parse notebook: {exc}")

        cells = nb.get("cells", [])

        if data.edit_mode == "insert":
            # Insert a new cell after cell_id or at cell_number
            new_cell = {
                "cell_type": data.cell_type or "code",
                "source": data.new_source.splitlines(True),
                "metadata": {},
            }
            if data.cell_type == "code":
                new_cell["outputs"] = []
                new_cell["execution_count"] = None
            idx = data.cell_number
            cells.insert(idx, new_cell)
        elif data.edit_mode == "delete":
            idx = data.cell_number
            if idx < 0 or idx >= len(cells):
                raise ToolError(f"Cell number {idx} out of range (0-{len(cells) - 1})")
            cells.pop(idx)
        else:
            # Replace
            idx = data.cell_number
            if idx < 0 or idx >= len(cells):
                raise ToolError(f"Cell number {idx} out of range (0-{len(cells) - 1})")
            cells[idx]["source"] = data.new_source.splitlines(True)
            if data.cell_type:
                cells[idx]["cell_type"] = data.cell_type

        nb["cells"] = cells

        try:
            path.write_text(json.dumps(nb, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"Failed to write notebook: {exc}")

        return f"Notebook edited: {path} (cell {data.cell_number}, mode={data.edit_mode})"
