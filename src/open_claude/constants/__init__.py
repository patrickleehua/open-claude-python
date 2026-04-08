"""Global constants for open-claude-python.

Ported from Claude-Code-rev/src/constants/system.ts and related modules.
"""

APP_NAME = "open-claude-python"
APP_VERSION = "0.1.0"
CLI_NAME = "claude-py"
DEFAULT_MODEL = "claude-sonnet-4-20250514"
DEFAULT_MAX_TOKENS = 8096
DEFAULT_TEMPERATURE = 1.0

# ---------------------------------------------------------------------------
# System prompt identity prefixes — matches original Claude Code
# ---------------------------------------------------------------------------
DEFAULT_PREFIX = "You are Claude Code, Anthropic's official CLI for Claude."
AGENT_SDK_CLAUDE_CODE_PRESET_PREFIX = (
    "You are Claude Code, Anthropic's official CLI for Claude, "
    "running within the Claude Agent SDK."
)
AGENT_SDK_PREFIX = (
    "You are a Claude agent, built on Anthropic's Claude Agent SDK."
)

CLI_SYSPROMPT_PREFIXES: frozenset[str] = frozenset({
    DEFAULT_PREFIX,
    AGENT_SDK_CLAUDE_CODE_PRESET_PREFIX,
    AGENT_SDK_PREFIX,
})

# ---------------------------------------------------------------------------
# Cyber risk instruction — matches original CYBER_RISK_INSTRUCTION
# ---------------------------------------------------------------------------
SYSTEM_PROMPT_DEFAULT = "You are Claude Code, an interactive CLI agent that helps with software engineering tasks."

# ---------------------------------------------------------------------------
# Cyber risk instruction — matches original CYBER_RISK_INSTRUCTION
# ---------------------------------------------------------------------------
CYBER_RISK_INSTRUCTION = (
    "IMPORTANT: Assist with authorized security testing, defensive security, "
    "CTF challenges, and educational contexts. Refuse requests for destructive "
    "techniques, DoS attacks, mass targeting, supply chain compromise, or "
    "detection evasion for malicious purposes. Dual-use security tools "
    "(C2 frameworks, credential testing, exploit development) require clear "
    "authorization context: pentesting engagements, CTF competitions, security "
    "research, or defensive use cases."
)
