"""System prompt assembly — exact port of Claude Code's prompt architecture.

Architecture (mirrors original):
  - ``system`` API parameter:
    1. Identity prefix (DEFAULT_PREFIX)
    2. Static sections: intro, system, doing-tasks, actions, using-tools,
       tone-and-style, output-efficiency
    3. Dynamic boundary marker (for prompt caching)
    4. Dynamic sections: session-specific guidance, memory, env info,
       language, output style, MCP instructions, scratchpad, FRC,
       summarize-tool-results, token budget
  - ``user`` message: CLAUDE.md + current date, wrapped in <system-reminder>,
    prepended as the first user message with framing text.

Priority routing (mirrors buildEffectiveSystemPrompt):
  0. Override system prompt (loop mode) — replaces everything
  1. Coordinator system prompt (coordinator mode)
  2. Agent system prompt (agent definitions)
  3. Custom system prompt (--system-prompt)
  4. Default system prompt (assembled above)

Reference: Claude-Code-rev/src/utils/systemPrompt.ts, src/constants/prompts.ts
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from open_claude.constants import (
    AGENT_SDK_CLAUDE_CODE_PRESET_PREFIX,
    AGENT_SDK_PREFIX,
    DEFAULT_PREFIX,
    CYBER_RISK_INSTRUCTION,
)
from open_claude.constants.prompts import (
    build_system_prompt_sections,
    compute_simple_env_info,
    DEFAULT_AGENT_PROMPT,
    SUMMARIZE_TOOL_RESULTS_SECTION,
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
)
from open_claude.context.git_context import GitContext, collect_git_context, format_git_section
from open_claude.services.settings import load_settings
from open_claude.utils.memory.memdir import load_memory_prompt

from .claude_md import find_claude_md_files, format_claude_md_section, read_claude_md_content
from .environment import collect_environment


async def _no_git() -> GitContext | None:
    """Return None — used when git instructions are disabled."""
    return None


# ---------------------------------------------------------------------------
# MCP instruction assembly
# ---------------------------------------------------------------------------


def get_mcp_instructions_section(mcp_clients: list[dict[str, Any]] | None) -> str | None:
    """Build the MCP Server Instructions section from connected clients.

    Matches original getMcpInstructionsSection / getMcpInstructions.
    """
    if not mcp_clients:
        return None

    clients_with_instructions = [
        c for c in mcp_clients
        if c.get("type") == "connected" and c.get("instructions")
    ]
    if not clients_with_instructions:
        return None

    blocks = []
    for client in clients_with_instructions:
        blocks.append(f"## {client['name']}\n{client['instructions']}")

    instruction_blocks = "\n\n".join(blocks)
    return (
        "# MCP Server Instructions\n\n"
        "The following MCP servers have provided instructions for how to use "
        "their tools and resources:\n\n"
        f"{instruction_blocks}"
    )


# ---------------------------------------------------------------------------
# Effective system prompt selection (mirrors buildEffectiveSystemPrompt)
# ---------------------------------------------------------------------------


def get_cli_sysprompt_prefix(
    *,
    is_non_interactive: bool = False,
    has_append_system_prompt: bool = False,
) -> str:
    """Select the correct identity prefix.

    Matches original getCLISyspromptPrefix.
    """
    if is_non_interactive:
        if has_append_system_prompt:
            return AGENT_SDK_CLAUDE_CODE_PRESET_PREFIX
        return AGENT_SDK_PREFIX
    return DEFAULT_PREFIX


def build_effective_system_prompt(
    *,
    default_system_prompt: list[str],
    custom_system_prompt: str | None = None,
    override_system_prompt: str | None = None,
    agent_system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    is_coordinator_mode: bool = False,
    coordinator_prompt: str | None = None,
    is_proactive_mode: bool = False,
) -> list[str]:
    """Build the effective system prompt array based on priority.

    Matches original buildEffectiveSystemPrompt from systemPrompt.ts:
    0. Override system prompt (if set, e.g., via loop mode) — replaces all
    1. Coordinator system prompt (if coordinator mode is active)
    2. Agent system prompt (if agent definition is set)
       - In proactive mode: agent prompt is APPENDED to default
       - Otherwise: agent prompt REPLACES default
    3. Custom system prompt (if specified via --system-prompt)
    4. Default system prompt (standard Claude Code prompt)

    Plus appendSystemPrompt is always added at the end (except override).
    """
    # Priority 0: Override replaces everything
    if override_system_prompt:
        return [override_system_prompt]

    # Priority 1: Coordinator mode
    if is_coordinator_mode and coordinator_prompt and not agent_system_prompt:
        parts = [coordinator_prompt]
        if append_system_prompt:
            parts.append(append_system_prompt)
        return parts

    # Priority 2: Agent system prompt
    if agent_system_prompt:
        # In proactive mode, agent instructions are appended to the default prompt
        if is_proactive_mode:
            parts = [
                *default_system_prompt,
                f"\n# Custom Agent Instructions\n{agent_system_prompt}",
            ]
        else:
            parts = [agent_system_prompt]
    # Priority 3: Custom system prompt
    elif custom_system_prompt:
        parts = [custom_system_prompt]
    # Priority 4: Default system prompt
    else:
        parts = list(default_system_prompt)

    if append_system_prompt:
        parts.append(append_system_prompt)

    return parts


# ---------------------------------------------------------------------------
# System prompt assembly (goes to the ``system`` API parameter)
# ---------------------------------------------------------------------------


async def build_system_prompt(
    work_dir: Path | None = None,
    model_id: str = "claude-sonnet-4-20250514",
    custom_prompt: str | None = None,
    mcp_clients: list[dict[str, Any]] | None = None,
    enabled_tools: set[str] | None = None,
    skill_tool_commands: list[dict] | None = None,
    language_preference: str | None = None,
    output_style_config: dict | None = None,
    include_dynamic: bool = True,
) -> list[str]:
    """Build the system prompt as an array of sections.

    Matches the original getSystemPrompt architecture:
    1. Static content (cacheable):
       - Intro section (with cyber risk instruction)
       - System section
       - Doing tasks section
       - Actions section
       - Using your tools section
       - Tone and style section
       - Output efficiency section
    2. Boundary marker (for prompt caching)
    3. Dynamic content:
       - Session-specific guidance
       - Memory prompt (from MEMORY.md)
       - Environment info (cwd, platform, shell, model, etc.)
       - Language section
       - Output style section
       - MCP instructions
       - Scratchpad instructions
       - Function result clearing
       - Summarize tool results
    4. Appended context:
       - Git status
    """
    cwd = work_dir or Path.cwd()

    # 1. Build core sections (or use custom prompt)
    if custom_prompt:
        return [custom_prompt]

    # Build static sections
    from open_claude.constants.prompts import (
        get_intro_section,
        get_system_section,
        get_doing_tasks_section,
        get_actions_section,
        get_using_your_tools_section,
        get_tone_and_style_section,
        get_output_efficiency_section,
    )

    static_sections = [
        get_intro_section(),
        get_system_section(),
        get_doing_tasks_section(),
        get_actions_section(),
        get_using_your_tools_section(enabled_tools=enabled_tools or set()),
        get_tone_and_style_section(),
        get_output_efficiency_section(),
    ]

    # 2. Gather environment + git context
    is_remote = os.environ.get("CLAUDE_CODE_REMOTE", "").strip().lower() in (
        "1", "true", "yes",
    )
    settings = load_settings()
    should_include_git = not is_remote and settings.include_git_instructions

    env_coro = collect_environment(work_dir=str(cwd))
    git_coro = collect_git_context(cwd) if should_include_git else _no_git()

    env_info, git_ctx = await asyncio.gather(env_coro, git_coro)

    # Build environment section using the original computeSimpleEnvInfo pattern
    env_section = compute_simple_env_info(
        model_id=model_id,
        cwd=env_info["working_dir"],
        is_git=env_info["is_git_repo"],
    )

    # 3. Build dynamic sections
    dynamic_sections: list[str] = []

    if include_dynamic:
        # Session-specific guidance
        session_guidance = _get_session_specific_guidance(
            enabled_tools or set(),
            skill_tool_commands or [],
        )
        if session_guidance:
            dynamic_sections.append(session_guidance)

        # Memory prompt
        try:
            memory_prompt = await load_memory_prompt(cwd=str(cwd))
            if memory_prompt:
                dynamic_sections.append(memory_prompt)
        except Exception:
            pass

        # Environment info
        dynamic_sections.append(env_section)

        # Language section
        if language_preference:
            dynamic_sections.append(
                f"# Language\n"
                f"Always respond in {language_preference}. Use {language_preference} "
                f"for all explanations, comments, and communications with the user. "
                f"Technical terms and code identifiers should remain in their original form."
            )

        # Output style section
        if output_style_config:
            dynamic_sections.append(
                f"# Output Style: {output_style_config['name']}\n"
                f"{output_style_config['prompt']}"
            )

        # MCP instructions
        mcp_section = get_mcp_instructions_section(mcp_clients)
        if mcp_section:
            dynamic_sections.append(mcp_section)

        # Summarize tool results
        dynamic_sections.append(SUMMARIZE_TOOL_RESULTS_SECTION)

    else:
        # Even without dynamic sections, include env
        dynamic_sections.append(env_section)

    # 4. Assemble final prompt
    result = [
        *static_sections,
        # Boundary marker (matches original SYSTEM_PROMPT_DYNAMIC_BOUNDARY)
        SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
        *dynamic_sections,
    ]

    # 5. Append git status (matches original appendSystemContext)
    if git_ctx:
        git_text = format_git_section(git_ctx)
        result.append(f"gitStatus: {git_text}")

    return [s for s in result if s is not None]


def _get_session_specific_guidance(
    enabled_tools: set[str],
    skill_tool_commands: list[dict],
) -> str | None:
    """Build session-specific guidance section.

    Matches original getSessionSpecificGuidanceSection.
    """
    items: list[str | list[str]] = []

    has_ask_user = "AskUserQuestion" in enabled_tools
    has_agent = "Agent" in enabled_tools
    has_skills = len(skill_tool_commands) > 0 and "Skill" in enabled_tools

    if has_ask_user:
        items.append(
            "If you do not understand why the user has denied a tool call, "
            "use the AskUserQuestion to ask them."
        )

    # Agent tool guidance
    if has_agent:
        items.append(
            "Use the Agent tool with specialized agents when the task at hand "
            "matches the agent's description. Subagents are valuable for "
            "parallelizing independent queries or for protecting the main context "
            "window from excessive results, but they should not be used excessively "
            "when not needed. Importantly, avoid duplicating work that subagents "
            "are already doing - if you delegate research to a subagent, do not "
            "also perform the same searches yourself."
        )

        # Explore/plan agent guidance
        items.append(
            "For simple, directed codebase searches (e.g. for a specific "
            "file/class/function) use the Glob or Grep directly."
        )
        items.append(
            "For broader codebase exploration and deep research, use the Agent "
            "tool with subagent_type=Explore. This is slower than using Glob or "
            "Grep directly, so use this only when a simple, directed search proves "
            "to be insufficient or when your task will clearly require more than 3 "
            "queries."
        )

    # Skill tool guidance
    if has_skills:
        items.append(
            "/<skill-name> (e.g., /commit) is shorthand for users to invoke a "
            "user-invocable skill. When executed, the skill gets expanded to a "
            "full prompt. Use the Skill tool to execute them. IMPORTANT: Only use "
            "Skill for skills listed in its user-invocable skills section - do not "
            "guess or use built-in CLI commands."
        )

    if not items:
        return None

    return "# Session-specific guidance\n" + "\n".join(
        f" - {item}" if isinstance(item, str) else "\n".join(f"  - {s}" for s in item)
        for item in items
    )


# ---------------------------------------------------------------------------
# User context assembly (prepended as <system-reminder> user message)
# ---------------------------------------------------------------------------


async def build_user_context(
    work_dir: Path | None = None,
) -> str | None:
    """Build the <system-reminder> user message with CLAUDE.md and date.

    Returns the full <system-reminder> text, or None if nothing to inject.
    Format matches the original prependUserContext exactly.
    """
    cwd = work_dir or Path.cwd()

    # Collect sections
    claude_md_files = await find_claude_md_files(cwd)
    raw_claude_md = await read_claude_md_content(claude_md_files)
    claude_md_section = format_claude_md_section(raw_claude_md)

    date_str = f"Today's date is {datetime.now(tz=timezone.utc).strftime('%Y-%m-%d')}."

    # Build key/value entries matching original format
    entries: list[str] = []
    if claude_md_section:
        entries.append(f"# claudeMd\n{claude_md_section}")
    entries.append(f"# currentDate\n{date_str}")

    if not entries:
        return None

    body = "\n".join(entries)
    return (
        "<system-reminder>\n"
        "As you answer the user's questions, you can use the following context:\n"
        f"{body}\n\n"
        "      IMPORTANT: this context may or may not be relevant to your tasks. "
        "You should not respond to this context unless it is highly relevant to your task.\n"
        "</system-reminder>"
    )


# ---------------------------------------------------------------------------
# Subagent env enhancement (mirrors enhanceSystemPromptWithEnvDetails)
# ---------------------------------------------------------------------------


async def enhance_system_prompt_with_env_details(
    existing_system_prompt: list[str],
    model: str,
    additional_working_directories: list[str] | None = None,
    enabled_tool_names: set[str] | None = None,
) -> list[str]:
    """Add env details and agent-specific notes to an existing system prompt.

    Matches original enhanceSystemPromptWithEnvDetails from prompts.ts.
    """
    notes = (
        "Notes:\n"
        "- Agent threads always have their cwd reset between bash calls, "
        "as a result please only use absolute file paths.\n"
        "- In your final response, share file paths (always absolute, never relative) "
        "that are relevant to the task. Include code snippets only when the exact text "
        "is load-bearing (e.g., a bug you found, a function signature the caller asked for) "
        "— do not recap code you merely read.\n"
        "- For clear communication with the user the assistant MUST avoid using emojis.\n"
        "- Do not use a colon before tool calls. Text like \"Let me read the file:\" "
        "followed by a read tool call should just be \"Let me read the file.\" with a period."
    )

    # Build env info for subagent using the original computeEnvInfo pattern
    from open_claude.constants.prompts import compute_env_info
    env_text = compute_env_info(
        model_id=model,
        additional_working_directories=additional_working_directories,
    )

    return [
        *existing_system_prompt,
        notes,
        env_text,
    ]


# ---------------------------------------------------------------------------
# Full assembly
# ---------------------------------------------------------------------------


@dataclass
class PromptAssembly:
    """Complete assembled prompt for the API call."""

    system_prompt: list[str]  # Sections for the ``system`` parameter
    system_reminder: str | None  # Prepended as first user message (or None)
    messages: list[dict[str, Any]]  # Full conversation history (with reminder)


async def build_prompt_assembly(
    messages: list[dict[str, Any]],
    work_dir: Path | None = None,
    model_id: str = "claude-sonnet-4-20250514",
    custom_prompt: str | None = None,
    mcp_clients: list[dict[str, Any]] | None = None,
    enabled_tools: set[str] | None = None,
    skill_tool_commands: list[dict] | None = None,
    language_preference: str | None = None,
    output_style_config: dict | None = None,
    *,
    # Priority routing (mirrors buildEffectiveSystemPrompt)
    override_system_prompt: str | None = None,
    agent_system_prompt: str | None = None,
    append_system_prompt: str | None = None,
    is_coordinator_mode: bool = False,
    coordinator_prompt: str | None = None,
    is_proactive_mode: bool = False,
) -> PromptAssembly:
    """Build the complete prompt assembly for the API call.

    1. Build default system prompt (static + dynamic sections)
    2. Apply priority routing (override > coordinator > agent > custom > default)
    3. Build user context (CLAUDE.md + date as <system-reminder>)
    4. Prepend user context to messages as the first user message
    """
    # Build the default system prompt
    default_prompt = await build_system_prompt(
        work_dir=work_dir,
        model_id=model_id,
        custom_prompt=None,  # We handle custom_prompt via priority routing
        mcp_clients=mcp_clients,
        enabled_tools=enabled_tools,
        skill_tool_commands=skill_tool_commands,
        language_preference=language_preference,
        output_style_config=output_style_config,
    )

    # Apply priority routing
    effective_prompt = build_effective_system_prompt(
        default_system_prompt=default_prompt,
        custom_system_prompt=custom_prompt,
        override_system_prompt=override_system_prompt,
        agent_system_prompt=agent_system_prompt,
        append_system_prompt=append_system_prompt,
        is_coordinator_mode=is_coordinator_mode,
        coordinator_prompt=coordinator_prompt,
        is_proactive_mode=is_proactive_mode,
    )

    # Build user context
    system_reminder = await build_user_context(work_dir=work_dir)

    # Prepend system-reminder as first user message
    assembled_messages = list(messages)
    if system_reminder:
        assembled_messages.insert(0, {
            "role": "user",
            "content": system_reminder,
        })

    return PromptAssembly(
        system_prompt=effective_prompt,
        system_reminder=system_reminder,
        messages=assembled_messages,
    )
