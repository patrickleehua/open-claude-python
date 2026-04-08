"""Safe tool allowlist for the auto mode classifier.

Ported from Claude-Code-rev src/utils/permissions/classifierDecision.ts.

Tools that are safe and don't need classifier checking.
Used by the auto mode classifier to skip unnecessary API calls.
"""

from __future__ import annotations

# Tools that are safe to auto-approve without classifier API calls.
# Read-only tools, task management, plan mode UI, and safe misc tools.
SAFE_YOLO_ALLOWLISTED_TOOLS: set[str] = {
    # Read-only file operations
    "Read",
    # Search / read-only
    "Grep",
    "Glob",
    "ToolSearch",
    "ListMcpResources",
    "ReadMcpResourceTool",
    # Task management (metadata only)
    "TodoWrite",
    "TaskCreate",
    "TaskGet",
    "TaskUpdate",
    "TaskList",
    "TaskStop",
    "TaskOutput",
    # Plan mode / UI
    "AskUserQuestion",
    "EnterPlanMode",
    "ExitPlanMode",
    # Swarm coordination
    "TeamCreate",
    "TeamDelete",
    "SendMessage",
    # Misc safe
    "Sleep",
}


def is_auto_mode_allowlisted_tool(tool_name: str) -> bool:
    """Check if a tool is on the safe allowlist for auto mode."""
    return tool_name in SAFE_YOLO_ALLOWLISTED_TOOLS
