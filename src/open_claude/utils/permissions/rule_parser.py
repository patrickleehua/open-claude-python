"""Permission rule string parsing and serialization.

Ported from Claude-Code-rev src/utils/permissions/permissionRuleParser.ts.

Rule format: "ToolName" or "ToolName(content)"
Content may contain escaped parentheses: \\( and \\)
"""

from __future__ import annotations

from open_claude.schemas.permissions import PermissionRuleValue

# Maps legacy tool names to their current canonical names.
LEGACY_TOOL_NAME_ALIASES: dict[str, str] = {
    "Task": "Agent",
    "KillShell": "TaskStop",
    "AgentOutputTool": "TaskOutput",
    "BashOutputTool": "TaskOutput",
}


def normalize_legacy_tool_name(name: str) -> str:
    """Normalize legacy tool names to their canonical form."""
    return LEGACY_TOOL_NAME_ALIASES.get(name, name)


def get_legacy_tool_names(canonical_name: str) -> list[str]:
    """Get all legacy names that map to a canonical name."""
    return [legacy for legacy, canonical in LEGACY_TOOL_NAME_ALIASES.items() if canonical == canonical_name]


def escape_rule_content(content: str) -> str:
    """Escape special characters in rule content.

    Order matters: backslashes first, then parentheses.
    """
    return content.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def unescape_rule_content(content: str) -> str:
    """Unescape special characters in rule content (reverse of escape).

    Order matters (reverse of escaping): parentheses first, then backslashes.
    """
    return content.replace("\\(", "(").replace("\\)", ")").replace("\\\\", "\\")


def permission_rule_value_from_string(rule_string: str) -> PermissionRuleValue:
    """Parse a permission rule string into its components.

    Format: "ToolName" or "ToolName(content)"
    Content may contain escaped parentheses: \\( and \\)

    Examples:
        "Bash" => PermissionRuleValue(tool_name="Bash")
        "Bash(npm install)" => PermissionRuleValue(tool_name="Bash", rule_content="npm install")
        "Bash(python -c \\"print\\\\(1\\\\)\\")"
    """
    open_paren_index = _find_first_unescaped_char(rule_string, "(")
    if open_paren_index == -1:
        return PermissionRuleValue(tool_name=normalize_legacy_tool_name(rule_string))

    close_paren_index = _find_last_unescaped_char(rule_string, ")")
    if close_paren_index == -1 or close_paren_index <= open_paren_index:
        return PermissionRuleValue(tool_name=normalize_legacy_tool_name(rule_string))

    if close_paren_index != len(rule_string) - 1:
        return PermissionRuleValue(tool_name=normalize_legacy_tool_name(rule_string))

    tool_name = rule_string[:open_paren_index]
    raw_content = rule_string[open_paren_index + 1 : close_paren_index]

    if not tool_name:
        return PermissionRuleValue(tool_name=normalize_legacy_tool_name(rule_string))

    if raw_content == "" or raw_content == "*":
        return PermissionRuleValue(tool_name=normalize_legacy_tool_name(tool_name))

    rule_content = unescape_rule_content(raw_content)
    return PermissionRuleValue(tool_name=normalize_legacy_tool_name(tool_name), rule_content=rule_content)


def permission_rule_value_to_string(rule_value: PermissionRuleValue) -> str:
    """Convert a permission rule value to its string representation.

    Examples:
        PermissionRuleValue(tool_name="Bash") => "Bash"
        PermissionRuleValue(tool_name="Bash", rule_content="npm install") => "Bash(npm install)"
    """
    if not rule_value.rule_content:
        return rule_value.tool_name
    escaped_content = escape_rule_content(rule_value.rule_content)
    return f"{rule_value.tool_name}({escaped_content})"


def _find_first_unescaped_char(s: str, char: str) -> int:
    """Find the index of the first unescaped occurrence of a character.

    A character is escaped if preceded by an odd number of backslashes.
    """
    for i, c in enumerate(s):
        if c == char:
            backslash_count = 0
            j = i - 1
            while j >= 0 and s[j] == "\\":
                backslash_count += 1
                j -= 1
            if backslash_count % 2 == 0:
                return i
    return -1


def _find_last_unescaped_char(s: str, char: str) -> int:
    """Find the index of the last unescaped occurrence of a character.

    A character is escaped if preceded by an odd number of backslashes.
    """
    for i in range(len(s) - 1, -1, -1):
        if s[i] == char:
            backslash_count = 0
            j = i - 1
            while j >= 0 and s[j] == "\\":
                backslash_count += 1
                j -= 1
            if backslash_count % 2 == 0:
                return i
    return -1
