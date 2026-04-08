"""AskUserQuestionTool - asks the user questions during execution (name: 'AskUserQuestion')."""

from __future__ import annotations

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool


class AskUserQuestionToolInput(BaseModel):
    """Input schema for AskUserQuestionTool."""

    question: str = Field(
        description="The question to ask the user"
    )
    options: list[str] | None = Field(
        default=None,
        description="List of options for the user to choose from",
    )
    multi_select: bool = Field(
        default=False,
        description="Allow multiple answers to be selected",
    )


class AskUserQuestionTool(Tool):
    """Asks the user questions during execution."""

    @property
    def name(self) -> str:
        return "AskUserQuestion"

    @property
    def input_schema(self) -> type[BaseModel]:
        return AskUserQuestionToolInput

    @property
    def description(self) -> str:
        return (
            "Use this tool when you need to ask the user questions during execution. "
            "This allows you to:\n"
            "1. Gather user preferences or requirements\n"
            "2. Clarify ambiguous instructions\n"
            "3. Get decisions on implementation choices as you work\n"
            "4. Offer choices to the user about what direction to take.\n"
            "\n"
            "Usage notes:\n"
            '- Users will always be able to select "Other" to provide custom text input\n'
            "- Use multiSelect: true to allow multiple answers to be selected for a question\n"
            "- If you recommend a specific option, make that the first option in the list and "
            'add "(Recommended)" at the end of the label'
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return False

    def is_read_only(self, input_data: BaseModel) -> bool:
        return True

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: AskUserQuestionToolInput
        parts = [f"Question: {data.question}"]
        if data.options:
            parts.append("Options:")
            for i, opt in enumerate(data.options, 1):
                parts.append(f"  {i}. {opt}")
        if data.multi_select:
            parts.append("(multi-select)")
        return "\n".join(parts)
