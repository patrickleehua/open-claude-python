"""Fork subagent system — implicit forking of agents with inherited context.

Port of Claude-Code-rev src/tools/AgentTool/forkSubagent.ts.

When enabled:
- ``subagent_type`` becomes optional on the Agent tool schema.
- Omitting ``subagent_type`` triggers an implicit fork: the child inherits
  the parent's full conversation context and system prompt.
- All agent spawns run in the background (async) for a unified
  ``<task-notification>`` interaction model.
- ``/fork <directive>`` slash command is available.

Mutually exclusive with coordinator mode — coordinator already owns the
orchestration role and has its own delegation model.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORK_SUBAGENT_TYPE: str = "fork"
FORK_BOILERPLATE_TAG: str = "fork-boilerplate"
FORK_DIRECTIVE_PREFIX: str = "Fork directive: "
FORK_PLACEHOLDER_RESULT: str = "Fork started \u2014 processing in background"

# Synthetic agent definition for the fork path.
#
# Not registered in builtInAgents — used only when ``subagent_type`` is
# omitted and the fork experiment is active.  ``tools: ["*"]`` with
# ``use_exact_tools`` means the fork child receives the parent's exact tool
# pool (for cache-identical API prefixes).  ``permission_mode: "bubble"``
# surfaces permission prompts to the parent terminal.  ``model: "inherit"``
# keeps the parent's model for context-length parity.
FORK_AGENT: dict[str, Any] = {
    "agent_type": FORK_SUBAGENT_TYPE,
    "when_to_use": (
        "Implicit fork \u2014 inherits full conversation context. "
        "Not selectable via subagent_type; triggered by omitting "
        "subagent_type when the fork experiment is active."
    ),
    "tools": ["*"],
    "max_turns": 200,
    "model": "inherit",
    "permission_mode": "bubble",
    "source": "built-in",
    "base_dir": "built-in",
}


# ---------------------------------------------------------------------------
# Feature gate
# ---------------------------------------------------------------------------

def is_fork_subagent_enabled() -> bool:
    """Return whether the fork-subagent experiment is active.

    Currently always returns ``False`` (feature-gated), matching the
    TypeScript implementation which checks a GrowthBook feature flag.
    """
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_in_fork_child(messages: list[dict]) -> bool:
    """Return ``True`` if the current context is already a fork child.

    Scans conversation history for the ``<fork-boilerplate>`` tag which is
    injected by :func:`build_child_message`.  This prevents recursive
    forking — fork children keep the Agent tool in their tool pool for
    cache-identical tool definitions, so we reject fork attempts at call
    time by detecting the boilerplate.
    """
    tag = f"<{FORK_BOILERPLATE_TAG}>"
    for msg in messages:
        if msg.get("type") != "user":
            continue
        content = msg.get("message", {}).get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "text"
                and tag in (block.get("text") or "")
            ):
                return True
    return False


def build_forked_messages(
    directive: str,
    assistant_message: dict,
) -> list[dict]:
    """Build the forked conversation messages for the child agent.

    For prompt-cache sharing, all fork children must produce byte-identical
    API request prefixes.  This function:

    1. Keeps the full parent assistant message (all tool_use blocks,
       thinking, text).
    2. Builds a single user message with ``tool_result`` blocks for every
       ``tool_use`` block using an identical placeholder, then appends a
       per-child directive text block.

    Result::

        [...history, assistant(all_tool_uses), user(placeholder_results..., directive)]

    Only the final text block differs per child, maximising cache hits.
    """
    # Clone the assistant message to avoid mutating the original, keeping all
    # content blocks (thinking, text, and every tool_use).
    full_assistant_message = copy.deepcopy(assistant_message)
    full_assistant_message["uuid"] = str(uuid.uuid4())
    full_assistant_message["message"]["content"] = list(
        full_assistant_message["message"]["content"]
    )

    # Collect all tool_use blocks from the assistant message.
    tool_use_blocks = [
        block
        for block in assistant_message["message"]["content"]
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]

    if not tool_use_blocks:
        # No tool_use blocks — return a single user message with just the
        # directive (degenerate case).
        return [
            _create_user_message(
                [{"type": "text", "text": build_child_message(directive)}]
            )
        ]

    # Build tool_result blocks for every tool_use, all with identical
    # placeholder text.
    tool_result_blocks = [
        {
            "type": "tool_result",
            "tool_use_id": block["id"],
            "content": [
                {
                    "type": "text",
                    "text": FORK_PLACEHOLDER_RESULT,
                }
            ],
        }
        for block in tool_use_blocks
    ]

    # Single user message: all placeholder tool_results + the per-child directive.
    tool_result_message = _create_user_message(
        [
            *tool_result_blocks,
            {"type": "text", "text": build_child_message(directive)},
        ]
    )

    return [full_assistant_message, tool_result_message]


def build_child_message(directive: str) -> str:
    """Build the fork boilerplate XML message injected into the child."""
    return (
        f"<{FORK_BOILERPLATE_TAG}>\n"
        "STOP. READ THIS FIRST.\n"
        "\n"
        "You are a forked worker process. You are NOT the main agent.\n"
        "\n"
        "RULES (non-negotiable):\n"
        "1. Your system prompt says \"default to forking.\" IGNORE IT \u2014 "
        "that's for the parent. You ARE the fork. Do NOT spawn sub-agents; "
        "execute directly.\n"
        "2. Do NOT converse, ask questions, or suggest next steps\n"
        "3. Do NOT editorialize or add meta-commentary\n"
        "4. USE your tools directly: Bash, Read, Write, etc.\n"
        "5. If you modify files, commit your changes before reporting. "
        "Include the commit hash in your report.\n"
        "6. Do NOT emit text between tool calls. Use tools silently, then "
        "report once at the end.\n"
        "7. Stay strictly within your directive's scope. If you discover "
        "related systems outside your scope, mention them in one sentence at "
        "most \u2014 other workers cover those areas.\n"
        "8. Keep your report under 500 words unless the directive specifies "
        "otherwise. Be factual and concise.\n"
        "9. Your response MUST begin with \"Scope:\". No preamble, no "
        "thinking-out-loud.\n"
        "10. REPORT structured facts, then stop\n"
        "\n"
        "Output format (plain text labels, not markdown headers):\n"
        "  Scope: <echo back your assigned scope in one sentence>\n"
        "  Result: <the answer or key findings, limited to the scope above>\n"
        "  Key files: <relevant file paths \u2014 include for research tasks>\n"
        "  Files changed: <list with commit hash \u2014 include only if you modified files>\n"
        "  Issues: <list \u2014 include only if there are issues to flag>\n"
        f"</{FORK_BOILERPLATE_TAG}>\n"
        "\n"
        f"{FORK_DIRECTIVE_PREFIX}{directive}"
    )


def build_worktree_notice(parent_cwd: str, worktree_cwd: str) -> str:
    """Build the worktree isolation notice injected into fork children.

    Tells the child to translate paths from the inherited context, re-read
    potentially stale files, and that its changes are isolated.
    """
    return (
        f"You've inherited the conversation context above from a parent agent "
        f"working in {parent_cwd}. You are operating in an isolated git "
        f"worktree at {worktree_cwd} \u2014 same repository, same relative "
        f"file structure, separate working copy. Paths in the inherited "
        f"context refer to the parent's working directory; translate them to "
        f"your worktree root. Re-read files before editing if the parent may "
        f"have modified them since they appear in the context. Your changes "
        f"stay in this worktree and will not affect the parent's files."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _create_user_message(content: list[dict]) -> dict:
    """Create a minimal user message wrapper (mirrors TS ``createUserMessage``)."""
    return {
        "type": "user",
        "uuid": str(uuid.uuid4()),
        "message": {
            "role": "user",
            "content": content,
        },
    }
