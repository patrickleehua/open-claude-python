from __future__ import annotations

from open_claude.schemas.permissions import PermissionMode, ToolPermissionContext
from open_claude.utils.permissions.pipeline import has_permissions_to_use_tool


async def test_accept_edits_mode_auto_allows_edit_and_write() -> None:
    context = ToolPermissionContext(mode=PermissionMode.ACCEPT_EDITS)

    edit_decision = await has_permissions_to_use_tool(
        tool_name="Edit",
        input_data={"file_path": "/tmp/demo.py", "old_string": "a", "new_string": "b"},
        context=context,
    )
    write_decision = await has_permissions_to_use_tool(
        tool_name="Write",
        input_data={"file_path": "/tmp/demo.py", "content": "hello"},
        context=context,
    )

    assert edit_decision.behavior == "allow"
    assert write_decision.behavior == "allow"
