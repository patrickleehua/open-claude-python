from __future__ import annotations

from open_claude.utils.diff import build_file_diff_preview, preview_for_tool_input, render_diff_preview_markup


def test_build_file_diff_preview_counts_and_markup() -> None:
    preview = build_file_diff_preview(
        file_path="/tmp/demo.py",
        old_content="a = 1\nb = 2\n",
        new_content="a = 1\nb = 3\nc = 4\n",
        operation="edit",
    )

    assert preview.additions == 2
    assert preview.removals == 1
    assert preview.hunks

    markup = render_diff_preview_markup(preview)
    assert "/tmp/demo.py" in markup
    assert "Added 2 lines" in markup
    assert "Removed 1 line" in markup
    assert "+ c = 4" in markup


def test_preview_for_tool_input_returns_none_for_unsupported_tool() -> None:
    assert preview_for_tool_input("Read", {"file_path": "/tmp/demo.py"}) is None
