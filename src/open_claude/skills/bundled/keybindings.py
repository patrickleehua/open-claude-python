"""Keybindings skill - customize keyboard shortcuts.

Port of Claude-Code-rev/src/skills/bundled/keybindings.ts
"""

from __future__ import annotations

import json

from open_claude.skills import register_bundled_skill
from open_claude.skills.types import BundledSkillDefinition


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    """Build a markdown table from headers and rows."""
    separator = ["---"] * len(headers)
    lines = [
        f"| {' | '.join(headers)} |",
        f"| {' | '.join(separator)} |",
    ]
    for row in rows:
        lines.append(f"| {' | '.join(row)} |")
    return "\n".join(lines)


# Keybinding contexts and their descriptions
KEYBINDING_CONTEXTS = [
    "Global", "Chat", "Autocomplete", "Confirmation",
    "Tabs", "Transcript", "HistorySearch", "Task",
    "ThemePicker", "Help", "Attachments", "Footer",
    "MessageSelector", "DiffDialog", "ModelPicker",
]

KEYBINDING_CONTEXT_DESCRIPTIONS = {
    "Global": "Active everywhere unless overridden",
    "Chat": "Main chat input area",
    "Autocomplete": "When autocomplete suggestions are shown",
    "Confirmation": "Permission/approval dialogs",
    "Tabs": "Tab navigation",
    "Transcript": "Message transcript area",
    "HistorySearch": "Search through command history",
    "Task": "Background task notifications",
    "ThemePicker": "Theme selection menu",
    "Help": "Help overlay",
    "Attachments": "File attachment handling",
    "Footer": "Footer status bar",
    "MessageSelector": "Select specific messages",
    "DiffDialog": "Diff review dialog",
    "ModelPicker": "Model selection menu",
}

KEYBINDING_ACTIONS = [
    "app:help", "app:quit", "app:toggleTodos",
    "chat:externalEditor", "chat:submit", "chat:newline",
    "history:previous", "history:next",
    "autocomplete:accept", "autocomplete:dismiss", "autocomplete:next", "autocomplete:previous",
    "confirm:accept", "confirm:dismiss",
    "tabs:next", "tabs:previous",
]

# Default bindings (simplified subset)
DEFAULT_BINDINGS = [
    {"context": "Global", "bindings": {"escape": "app:help", "ctrl+q": "app:quit"}},
    {"context": "Chat", "bindings": {"enter": "chat:submit", "shift+enter": "chat:newline", "ctrl+e": "chat:externalEditor"}},
    {"context": "Autocomplete", "bindings": {"tab": "autocomplete:accept", "escape": "autocomplete:dismiss", "down": "autocomplete:next", "up": "autocomplete:previous"}},
]


def _generate_contexts_table() -> str:
    return _markdown_table(
        ["Context", "Description"],
        [[f"`{ctx}`", KEYBINDING_CONTEXT_DESCRIPTIONS.get(ctx, "")] for ctx in KEYBINDING_CONTEXTS],
    )


def _generate_actions_table() -> str:
    action_info: dict[str, dict] = {}
    for block in DEFAULT_BINDINGS:
        for key, action in block["bindings"].items():
            if action and action not in action_info:
                action_info[action] = {"keys": [], "context": block["context"]}
            if action:
                action_info[action]["keys"].append(key)

    return _markdown_table(
        ["Action", "Default Key(s)", "Context"],
        [
            [
                f"`{action}`",
                ", ".join(f"`{k}`" for k in action_info.get(action, {}).get("keys", [])) or "(none)",
                action_info.get(action, {}).get("context", "Unknown"),
            ]
            for action in KEYBINDING_ACTIONS
        ],
    )


async def _get_prompt(args: str, context: object) -> list[dict]:
    contexts_table = _generate_contexts_table()
    actions_table = _generate_actions_table()

    file_format_example = {
        "$schema": "https://www.schemastore.org/claude-code-keybindings.json",
        "$docs": "https://code.claude.com/docs/en/keybindings",
        "bindings": [
            {
                "context": "Chat",
                "bindings": {"ctrl+e": "chat:externalEditor"},
            }
        ],
    }

    sections = [
        "# Keybindings Skill",
        "",
        "Create or modify `~/.claude/keybindings.json` to customize keyboard shortcuts.",
        "",
        "## CRITICAL: Read Before Write",
        "",
        "**Always read `~/.claude/keybindings.json` first** (it may not exist yet). Merge changes with existing bindings.",
        "",
        "## File Format",
        "",
        f"```json\n{json.dumps(file_format_example, indent=2)}\n```",
        "",
        "Always include the `$schema` and `$docs` fields.",
        "",
        "## Keystroke Syntax",
        "",
        "**Modifiers** (combine with `+`): `ctrl`, `alt`, `shift`, `meta` (aliases: `cmd`, `command`)",
        "",
        "**Special keys**: `escape`/`esc`, `enter`/`return`, `tab`, `space`, `backspace`, `delete`, `up`, `down`, `left`, `right`",
        "",
        "**Chords**: Space-separated keystrokes, e.g. `ctrl+k ctrl+s`",
        "",
        "## How User Bindings Interact with Defaults",
        "",
        "- User bindings are **additive** — appended after defaults",
        "- To **move** a binding: unbind old key (`null`) AND add new binding",
        "- A context only needs to appear if the user wants to change something",
        "",
        "## Behavioral Rules",
        "",
        "1. Only include contexts the user wants to change",
        "2. Validate actions and contexts are from the known lists below",
        "3. Warn about conflicts with reserved shortcuts",
        "4. When adding a new binding, it's additive (existing default still works)",
        "",
        f"## Available Contexts\n\n{contexts_table}",
        "",
        f"## Available Actions\n\n{actions_table}",
    ]

    if args:
        sections.append(f"## User Request\n\n{args}")

    return [{"type": "text", "text": "\n\n".join(sections)}]


def register_keybindings_skill() -> None:
    register_bundled_skill(
        BundledSkillDefinition(
            name="keybindings-help",
            description=(
                "Use when the user wants to customize keyboard shortcuts, rebind keys, "
                "add chord bindings, or modify ~/.claude/keybindings.json."
            ),
            allowed_tools=["Read"],
            user_invocable=False,
            is_enabled=lambda: True,  # isKeybindingCustomizationEnabled
            get_prompt_for_command=_get_prompt,
        )
    )
