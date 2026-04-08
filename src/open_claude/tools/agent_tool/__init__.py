"""AgentTool - launches specialized agents for complex tasks (name: 'Agent')."""

from __future__ import annotations

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError


class AgentToolInput(BaseModel):
    """Input schema for AgentTool."""

    prompt: str = Field(
        description="The task description to send to the agent"
    )
    description: str = Field(
        description="A short description (3-5 words) of what the agent will do"
    )
    subagent_type: str | None = Field(
        default=None,
        description="The type of agent to use. If omitted, the general-purpose agent is used.",
    )
    name: str | None = Field(
        default=None,
        description="A short name for the agent (1-2 words, lowercase)",
    )
    run_in_background: bool = Field(
        default=False,
        description="Run the agent in the background",
    )


class AgentTool(Tool):
    """Launches specialized agents for complex, multi-step tasks."""

    @property
    def name(self) -> str:
        return "Agent"

    @property
    def input_schema(self) -> type[BaseModel]:
        return AgentToolInput

    @property
    def description(self) -> str:
        return (
            "Launch a new agent to handle complex, multi-step tasks autonomously.\n"
            "\n"
            "The Agent tool launches specialized agents (subprocesses) that autonomously handle "
            "complex tasks. Each agent type has specific capabilities and tools available to it.\n"
            "\n"
            "When using the Agent tool, specify a subagent_type parameter to select which agent "
            "type to use. If omitted, the general-purpose agent is used.\n"
            "\n"
            "When NOT to use the Agent tool:\n"
            "- If you want to read a specific file path, use the Read tool or the Glob tool instead "
            "of the Agent tool, to find the match more quickly\n"
            '- If you are searching for a specific class definition like "class Foo", use the Glob '
            "tool instead, to find the match more quickly\n"
            "- If you are searching for code within a specific file or set of 2-3 files, use the "
            "Read tool instead of the Agent tool, to find the match more quickly\n"
            "- Other tasks that are not related to the agent descriptions above\n"
            "\n"
            "Usage notes:\n"
            "- Always include a short description (3-5 words) summarizing what the agent will do\n"
            "- Launch multiple agents concurrently whenever possible, to maximize performance; to "
            "do that, use a single message with multiple tool uses\n"
            "- When the agent is done, it will return a single message back to you. The result "
            "returned by the agent is not visible to the user. To show the user the result, you "
            "should send a text message back to the user with a concise summary of the result.\n"
            "- You can optionally run agents in the background using the run_in_background parameter. "
            "When an agent runs in the background, you will be automatically notified when it "
            "completes — do NOT sleep, poll, or proactively check on its progress. Continue with "
            "other work or respond to the user instead.\n"
            "- **Foreground vs background**: Use foreground (default) when you need the agent's "
            "results before you can proceed — e.g., research agents whose findings inform your "
            "next steps. Use background when you have genuinely independent work to do in parallel.\n"
            "- The agent's outputs should generally be trusted\n"
            "- Clearly tell the agent whether you expect it to write code or just to do research "
            "(search, file reads, web fetches, etc.)\n"
            "- If the user specifies that they want you to run agents \"in parallel\", you MUST send "
            "a single message with multiple Agent tool use content blocks. For example, if you need "
            "to launch both a build-validator agent and a test-runner agent in parallel, send a "
            "single message with both tool calls.\n"
            "\n"
            "## Writing the prompt\n"
            "\n"
            "Brief the agent like a smart colleague who just walked into the room — it hasn't seen "
            "this conversation, doesn't know what you've tried, doesn't understand why this task matters.\n"
            "- Explain what you're trying to accomplish and why.\n"
            "- Describe what you've already learned or ruled out.\n"
            "- Give enough context about the surrounding problem that the agent can make judgment "
            "calls rather than just following a narrow instruction.\n"
            '- If you need a short response, say so ("report in under 200 words").\n'
            "- Lookups: hand over the exact command. Investigations: hand over the question — "
            "prescribed steps become dead weight when the premise is wrong.\n"
            "\n"
            "Terse command-style prompts produce shallow, generic work.\n"
            "\n"
            '**Never delegate understanding.** Don\'t write "based on your findings, fix the bug" or '
            '"based on the research, implement it." Those phrases push synthesis onto the agent instead '
            "of doing it yourself. Write prompts that prove you understood: include file paths, line "
            "numbers, what specifically to change."
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return False

    def is_read_only(self, input_data: BaseModel) -> bool:
        return False

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: AgentToolInput
        raise ToolError(
            "Agent tool is not yet implemented in open-claude-python."
        )
