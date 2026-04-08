"""SkillTool - executes skills within the main conversation (name: 'Skill')."""

from __future__ import annotations

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError


class SkillToolInput(BaseModel):
    """Input schema for SkillTool."""

    skill: str = Field(
        description="The skill name to invoke"
    )
    args: str | None = Field(
        default=None,
        description="Optional arguments for the skill",
    )


class SkillTool(Tool):
    """Executes a skill within the main conversation."""

    @property
    def name(self) -> str:
        return "Skill"

    @property
    def input_schema(self) -> type[BaseModel]:
        return SkillToolInput

    @property
    def description(self) -> str:
        return (
            "Execute a skill within the main conversation\n"
            "\n"
            "When users ask you to perform tasks, check if any of the available skills match. "
            "Skills provide specialized capabilities and domain knowledge.\n"
            "\n"
            'When users reference a "slash command" or "/<something>" (e.g., "/commit", '
            '"/review-pr"), they are referring to a skill. Use this tool to invoke it.\n'
            "\n"
            "How to invoke:\n"
            "- Use this tool with the skill name and optional arguments\n"
            "- Examples:\n"
            '  - `skill: "pdf"` - invoke the pdf skill\n'
            '  - `skill: "commit", args: "-m \'Fix bug\'"` - invoke with arguments\n'
            '  - `skill: "review-pr", args: "123"` - invoke with arguments\n'
            '  - `skill: "ms-office-suite:pdf"` - invoke using fully qualified name\n'
            "\n"
            "Important:\n"
            "- Available skills are listed in system-reminder messages in the conversation\n"
            "- When a skill matches the user's request, this is a BLOCKING REQUIREMENT: invoke the "
            "relevant Skill tool BEFORE generating any other response about the task\n"
            "- NEVER mention a skill without actually calling this tool\n"
            "- Do not invoke a skill that is already running\n"
            "- Do not use this tool for built-in CLI commands (like /help, /clear, etc.)\n"
            "- If you see a <command-name> tag in the current conversation turn, the skill has "
            "ALREADY been loaded - follow the instructions directly instead of calling this tool again"
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return False

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: SkillToolInput
        raise ToolError(
            f"Skill '{data.skill}' is not yet implemented in open-claude-python."
        )
