from __future__ import annotations

from open_claude.schemas import ToolExecutionResult
from open_claude.tools import create_tool_executor


async def test_edit_tool_returns_structured_diff_payload(tmp_path) -> None:
    target = tmp_path / "demo.py"
    target.write_text("value = 1\n", encoding="utf-8")

    executor = create_tool_executor()
    result = await executor(
        "Edit",
        {
            "file_path": str(target),
            "old_string": "value = 1",
            "new_string": "value = 2",
        },
    )

    assert isinstance(result, ToolExecutionResult)
    assert "Edited" in result.output
    assert result.display_data is not None
    assert result.display_data["kind"] == "file_diff"
    assert result.display_data["status"] == "applied"
    assert "value = 2" in result.display_data["markup"]


async def test_write_tool_returns_structured_diff_payload(tmp_path) -> None:
    target = tmp_path / "created.txt"

    executor = create_tool_executor()
    result = await executor(
        "Write",
        {
            "file_path": str(target),
            "content": "hello\nworld\n",
        },
    )

    assert isinstance(result, ToolExecutionResult)
    assert "created" in result.output
    assert result.display_data is not None
    assert result.display_data["kind"] == "file_diff"
    assert result.display_data["status"] == "applied"
    assert "Added 2 lines" in result.display_data["markup"]
