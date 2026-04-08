"""BashTool - executes shell commands (name: 'Bash')."""

from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel, Field

from open_claude.tools.base import Tool, ToolError

# Dangerous command patterns that are always blocked
DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+-rf\s+/($|\s)", re.IGNORECASE),
    re.compile(r"\brm\s+-rf\s+/\*", re.IGNORECASE),
    re.compile(r"\bgit\s+push\s+.*--force", re.IGNORECASE),
    re.compile(r"\bgit\s+push\s+-f\b", re.IGNORECASE),
    re.compile(r"\bgit\s+reset\s+--hard", re.IGNORECASE),
    re.compile(r"\bgit\s+checkout\s+\.\s*$", re.IGNORECASE),
    re.compile(r"\bgit\s+clean\s+-f", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\s+if=", re.IGNORECASE),
    re.compile(r":\(\)\{.*:\|:&\s*\}", re.IGNORECASE),  # fork bomb
    re.compile(r">\s*/dev/sd", re.IGNORECASE),
    re.compile(r"\bchmod\s+-R\s+777\s+/", re.IGNORECASE),
    re.compile(r"\bchown\s+-R\s+.*\s+/", re.IGNORECASE),
]

DEFAULT_TIMEOUT_MS = 120_000
MAX_OUTPUT_BYTES = 64 * 1024 * 1024  # 64 MB


class BashToolInput(BaseModel):
    """Input schema for BashTool."""

    command: str = Field(
        description="The bash command to run"
    )
    timeout: int | None = Field(
        default=DEFAULT_TIMEOUT_MS,
        description="Optional timeout in milliseconds (max 600000)",
    )
    description: str | None = Field(
        default=None,
        description="A clear, concise description of what this command does",
    )
    run_in_background: bool = Field(
        default=False,
        description="Run the command in the background and return immediately",
    )


class BashTool(Tool):
    """Executes a bash shell command."""

    @property
    def name(self) -> str:
        return "Bash"

    @property
    def input_schema(self) -> type[BaseModel]:
        return BashToolInput

    @property
    def description(self) -> str:
        return (
            "Executes a given bash command and returns its output.\n"
            "\n"
            "The working directory persists between commands, but shell state does not. "
            "The shell environment is initialized from the user's profile (bash or zsh).\n"
            "\n"
            "IMPORTANT: Avoid using this tool to run `find`, `grep`, `cat`, `head`, "
            "`tail`, `sed`, `awk`, or `echo` commands, unless explicitly instructed "
            "or after you have verified that a dedicated tool cannot accomplish your task. "
            "Instead, use the appropriate dedicated tool as this will provide a much better "
            "experience for the user:\n"
            "\n"
            " - File search: Use Glob (NOT find or ls)\n"
            ' - Content search: Use Grep (NOT grep or rg)\n'
            " - Read files: Use Read (NOT cat/head/tail)\n"
            " - Edit files: Use Edit (NOT sed/awk)\n"
            " - Write files: Use Write (NOT echo >/cat <<EOF)\n"
            " - Communication: Output text directly (NOT echo/printf)\n"
            "While the Bash tool can do similar things, it's better to use the built-in tools "
            "as they provide a better user experience and make it easier to review tool calls "
            "and give permission.\n"
            "\n"
            "# Instructions\n"
            " - If your command will create new directories or files, first use this tool to run "
            "`ls` to verify the parent directory exists and is the correct location.\n"
            ' - Always quote file paths that contain spaces with double quotes in your command '
            '(e.g., cd "path with spaces/file.txt")\n'
            " - Try to maintain your current working directory throughout the session by using "
            "absolute paths and avoiding usage of `cd`. You may use `cd` if the User explicitly "
            "requests it.\n"
            " - You may specify an optional timeout in milliseconds (up to 600000ms / 10 minutes). "
            "By default, your command will timeout after 120000ms (2 minutes).\n"
            " - You can use the `run_in_background` parameter to run the command in the background. "
            "Only use this if you don't need the result immediately and are OK being notified when "
            "the command completes later. You do not need to check the output right away - you'll "
            "be notified when it finishes. You do not need to use '&' at the end of the command "
            "when using this parameter.\n"
            " - When issuing multiple commands:\n"
            "   - If the commands are independent and can run in parallel, make multiple Bash tool "
            'calls in a single message. Example: if you need to run "git status" and "git diff", '
            "send a single message with two Bash tool calls in parallel.\n"
            "   - If the commands depend on each other and must run sequentially, use a single "
            "Bash call with '&&' to chain them together.\n"
            "   - Use ';' only when you need to run commands sequentially but don't care if earlier "
            "commands fail.\n"
            "   - DO NOT use newlines to separate commands (newlines are ok in quoted strings).\n"
            " - For git commands:\n"
            "   - Prefer to create a new commit rather than amending an existing commit.\n"
            "   - Before running destructive operations (e.g., git reset --hard, git push --force, "
            "git checkout --), consider whether there is a safer alternative that achieves the same "
            "goal. Only use destructive operations when they are truly the best approach.\n"
            "   - Never skip hooks (--no-verify) or bypass signing (--no-gpg-sign, "
            "-c commit.gpgsign=false) unless the user has explicitly asked for it. If a hook fails, "
            "investigate and fix the underlying issue.\n"
            " - Avoid unnecessary `sleep` commands:\n"
            "   - Do not sleep between commands that can run immediately — just run them.\n"
            "   - If your command is long running and you would like to be notified when it "
            "finishes — use `run_in_background`. No sleep needed.\n"
            "   - Do not retry failing commands in a sleep loop — diagnose the root cause.\n"
            "   - If waiting for a background task you started with `run_in_background`, you will "
            "be notified when it completes — do not poll.\n"
            "   - If you must poll an external process, use a check command (e.g. `gh run view`) "
            "rather than sleeping first.\n"
            "   - If you must sleep, keep the duration short (1-5 seconds) to avoid blocking the user."
        )

    def is_concurrency_safe(self, input_data: BaseModel) -> bool:
        return False

    def is_read_only(self, input_data: BaseModel) -> bool:
        return False

    async def call(self, input_data: BaseModel) -> str:
        data = input_data  # type: BashToolInput

        # Security check
        self._check_dangerous_command(data.command)

        # Clamp timeout
        timeout_ms = min(data.timeout or DEFAULT_TIMEOUT_MS, 600_000)
        timeout_sec = timeout_ms / 1000.0

        if data.run_in_background:
            return await self._run_background(data.command)

        return await self._run_foreground(data.command, timeout_sec)

    def _check_dangerous_command(self, command: str) -> None:
        """Block obviously dangerous commands."""
        for pattern in DANGEROUS_PATTERNS:
            if pattern.search(command):
                raise ToolError(
                    "Blocked: command matches a dangerous pattern. "
                    "If you truly need to run this, please confirm with the user first."
                )

    async def _run_foreground(self, command: str, timeout_sec: float) -> str:
        """Run a command in the foreground with timeout."""
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ToolError(
                f"Command timed out after {timeout_sec:.0f}s: {command[:100]}"
            )

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")

        # Truncate large output
        if len(stdout) > MAX_OUTPUT_BYTES:
            stdout = stdout[:MAX_OUTPUT_BYTES] + "\n... (output truncated)"

        parts: list[str] = []
        if stdout.strip():
            parts.append(stdout.rstrip())
        if stderr.strip():
            parts.append(f"stderr:\n{stderr.rstrip()}")
        if proc.returncode != 0:
            parts.append(f"(exit code: {proc.returncode})")

        return "\n".join(parts) if parts else "(no output)"

    async def _run_background(self, command: str) -> str:
        """Start a command in the background."""
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        return (
            f"Background task started (PID: {proc.pid}). "
            f"Command: {command[:100]}"
        )
