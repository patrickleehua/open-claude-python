"""SkillTool - executes skills within the main conversation (name: 'Skill')."""

from __future__ import annotations

from pydantic import BaseModel, Field

from open_claude.schemas import ToolExecutionResult
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

    async def call(self, input_data: BaseModel) -> ToolExecutionResult:
        """Execute the skill and return structured result with new_messages.

        Mirrors the TS SkillTool.call() flow:
        1. Look up skill in registry
        2. Call get_prompt_for_command(args, context)
        3. Build metadata wrapping (<command-message>, <command-name> tags)
        4. Return ToolExecutionResult with skill content as new_messages
        5. The query engine injects new_messages as user messages
        """
        data = input_data  # type: SkillToolInput
        skill_name = data.skill.lstrip("/")
        args = data.args or ""

        from open_claude.skills import get_skill_registry

        registry = get_skill_registry()
        skill = registry.find(skill_name)

        if skill is None:
            available = [s.name for s in registry.get_user_invocable()]
            raise ToolError(
                f"Skill '{skill_name}' not found. Available skills: {available}"
            )

        if skill.get_prompt_for_command is None:
            raise ToolError(
                f"Skill '{skill_name}' has no prompt generator."
            )

        blocks = await skill.get_prompt_for_command(args, {})

        # Extract text from content blocks
        text_parts = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
        prompt_content = "\n".join(t for t in text_parts if t)

        if not prompt_content:
            return ToolExecutionResult(output=f"Skill '{skill_name}' returned empty content.")

        # Build metadata wrapping (matches TS formatSlashCommandLoadingMetadata)
        metadata_lines = [
            f"<command-message>{skill_name}</command-message>",
            f"<command-name>/{skill_name}</command-name>",
        ]
        if args:
            metadata_lines.append(f"<command-args>{args}</command-args>")

        # Build new_messages: metadata + skill content as user messages
        # (mirrors TS getMessagesForPromptSlashCommand message construction)
        new_messages = [
            # Metadata user message (visible marker for the skill invocation)
            {"role": "user", "content": "\n".join(metadata_lines)},
            # Skill content as user message (the actual instructions)
            {"role": "user", "content": prompt_content},
        ]

        return ToolExecutionResult(
            output=f"Launching skill: {skill_name}",
            new_messages=new_messages,
        )
