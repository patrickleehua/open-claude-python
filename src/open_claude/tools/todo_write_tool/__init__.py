"""TodoWriteTool - manages structured task lists (name: 'TodoWrite')."""

from __future__ import annotations

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool


class TodoItem(BaseModel):
    """A single todo item."""

    content: str = Field(
        description="The imperative form describing what needs to be done (e.g., 'Run tests', 'Build the project')"
    )
    status: str = Field(
        description="Task status: 'pending', 'in_progress', or 'completed'"
    )
    activeForm: str = Field(
        description="The present continuous form shown during execution (e.g., 'Running tests', 'Building the project')"
    )


class TodoWriteToolInput(BaseModel):
    """Input schema for TodoWriteTool."""

    todos: list[TodoItem] = Field(
        description="The updated todo list"
    )


class TodoWriteTool(Tool):
    """Manages a structured task list for the current coding session."""

    @property
    def name(self) -> str:
        return "TodoWrite"

    @property
    def input_schema(self) -> type[BaseModel]:
        return TodoWriteToolInput

    @property
    def description(self) -> str:
        return (
            "Use this tool to create and manage a structured task list for your current coding session. "
            "This helps you track progress, organize complex tasks, and demonstrate thoroughness to the user.\n"
            "It also helps the user understand the progress of the task and overall progress of their requests.\n"
            "\n"
            "## When to Use This Tool\n"
            "Use this tool proactively in these scenarios:\n"
            "\n"
            "1. Complex multi-step tasks - When a task requires 3 or more distinct steps or actions\n"
            "2. Non-trivial and complex tasks - Tasks that require careful planning or multiple operations\n"
            "3. User explicitly requests todo list - When the user directly asks you to use the todo list\n"
            "4. User provides multiple tasks - When users provide a list of things to be done (numbered or comma-separated)\n"
            "5. After receiving new instructions - Immediately capture user requirements as todos\n"
            "6. When you start working on a task - Mark it as in_progress BEFORE beginning work. "
            "Ideally you should only have one todo as in_progress at a time\n"
            "7. After completing a task - Mark it as completed and add any new follow-up tasks discovered during implementation\n"
            "\n"
            "## When NOT to Use This Tool\n"
            "\n"
            "Skip using this tool when:\n"
            "1. There is only a single, straightforward task\n"
            "2. The task is trivial and tracking it provides no organizational benefit\n"
            "3. The task can be completed in less than 3 trivial steps\n"
            "4. The task is purely conversational or informational\n"
            "\n"
            "NOTE that you should not use this tool if there is only one trivial task to do. "
            "In this case you are better off just doing the task directly.\n"
            "\n"
            "## Task States and Management\n"
            "\n"
            "1. **Task States**: Use these states to track progress:\n"
            "   - pending: Task not yet started\n"
            "   - in_progress: Currently working on (limit to ONE task at a time)\n"
            "   - completed: Task finished successfully\n"
            "\n"
            "   **IMPORTANT**: Task descriptions must have two forms:\n"
            '   - content: The imperative form describing what needs to be done (e.g., "Run tests", "Build the project")\n'
            '   - activeForm: The present continuous form shown during execution (e.g., "Running tests", "Building the project")\n'
            "\n"
            "2. **Task Management**:\n"
            "   - Update task status in real-time as you work\n"
            "   - Mark tasks complete IMMEDIATELY after finishing (don't batch completions)\n"
            "   - Exactly ONE task must be in_progress at any time (not less, not more)\n"
            "   - Complete current tasks before starting new ones\n"
            "   - Remove tasks that are no longer relevant from the list entirely\n"
            "\n"
            "3. **Task Completion Requirements**:\n"
            "   - ONLY mark a task as completed when you have FULLY accomplished it\n"
            "   - If you encounter errors, blockers, or cannot finish, keep the task as in_progress\n"
            "   - When blocked, create a new task describing what needs to be resolved\n"
            "   - Never mark a task as completed if:\n"
            "     - Tests are failing\n"
            "     - Implementation is partial\n"
            "     - You encountered unresolved errors\n"
            "     - You couldn't find necessary files or dependencies\n"
            "\n"
            "4. **Task Breakdown**:\n"
            "   - Create specific, actionable items\n"
            "   - Break complex tasks into smaller, manageable steps\n"
            "   - Use clear, descriptive task names\n"
            "   - Always provide both forms:\n"
            '     - content: "Fix authentication bug"\n'
            '     - activeForm: "Fixing authentication bug"\n'
            "\n"
            "When in doubt, use this tool. Being proactive with task management demonstrates "
            "attentiveness and ensures you complete all requirements successfully."
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return True

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: TodoWriteToolInput
        # Validate task states
        valid_states = {"pending", "in_progress", "completed"}
        for i, todo in enumerate(data.todos):
            if todo.status not in valid_states:
                return f"Error: Invalid status '{todo.status}' for todo {i}. Must be one of: {valid_states}"

        in_progress_count = sum(1 for t in data.todos if t.status == "in_progress")
        parts = [f"Updated todo list ({len(data.todos)} items, {in_progress_count} in progress):"]
        for todo in data.todos:
            icon = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}.get(todo.status, "[?]")
            parts.append(f"  {icon} {todo.content}")
        return "\n".join(parts)
