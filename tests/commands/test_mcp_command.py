from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from open_claude.commands.mcp import McpCommand
from open_claude.schemas.permissions import PermissionMode, ToolPermissionContext


@dataclass
class _DummyContext:
    messages: list[dict] = field(default_factory=list)
    model_name: str = "claude-sonnet-4-20250514"
    token_usage: object | None = None
    permission_context: ToolPermissionContext = field(default_factory=ToolPermissionContext)
    refreshed: int = 0

    def clear_conversation(self) -> None:
        self.messages.clear()

    def compact_conversation(self, instructions: str = ""):
        return None

    def load_settings(self) -> dict:
        return {}

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_context.mode = mode

    async def refresh_tools(self) -> None:
        self.refreshed += 1


@pytest.mark.asyncio
async def test_mcp_command_add_list_remove_round_trip(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("HOME", str(home_dir))

    async def _noop() -> None:
        return None

    monkeypatch.setattr("open_claude.commands.mcp.connect_mcp_servers", _noop)
    monkeypatch.setattr("open_claude.commands.mcp.disconnect_mcp_servers", _noop)

    command = McpCommand()
    ctx = _DummyContext()

    add_result = await command.execute(
        "add filesystem python -m demo.server --flag",
        ctx,
    )
    assert "Added MCP server 'filesystem'" in add_result.value
    assert ctx.refreshed == 1
    assert '"filesystem"' in (project_dir / ".mcp.json").read_text(encoding="utf-8")

    list_result = await command.execute("list", ctx)
    assert "filesystem" in list_result.value
    assert "python" in list_result.value

    remove_result = await command.execute("remove filesystem", ctx)
    assert "Removed MCP server 'filesystem'" in remove_result.value
    assert ctx.refreshed == 2
    assert "filesystem" not in (project_dir / ".mcp.json").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_mcp_command_add_json_and_get(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("HOME", str(home_dir))

    async def _noop() -> None:
        return None

    monkeypatch.setattr("open_claude.commands.mcp.connect_mcp_servers", _noop)
    monkeypatch.setattr("open_claude.commands.mcp.disconnect_mcp_servers", _noop)

    command = McpCommand()
    ctx = _DummyContext()

    add_result = await command.execute(
        """add-json docs '{"type":"http","url":"https://example.com/mcp","headers":{"Authorization":"Bearer token"},"oauth":{"client_id":"abc","callback_port":8123}}' --client-secret secret-value""",
        ctx,
    )
    assert "Added MCP server 'docs' from JSON" in add_result.value

    get_result = command._get_server(["docs"])
    assert "URL: https://example.com/mcp" in get_result.value
    assert "Authorization: Bearer token" in get_result.value
    assert "client_id configured" in get_result.value
    assert "client_secret configured" in get_result.value


@pytest.mark.asyncio
async def test_mcp_command_disable_enable_and_reset_choices(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("HOME", str(home_dir))

    async def _noop() -> None:
        return None

    monkeypatch.setattr("open_claude.commands.mcp.connect_mcp_servers", _noop)
    monkeypatch.setattr("open_claude.commands.mcp.disconnect_mcp_servers", _noop)

    command = McpCommand()
    ctx = _DummyContext()

    await command.execute("add demo python -m server", ctx)

    disabled_result = await command.execute("disable demo", ctx)
    assert "Disabled MCP server 'demo'" in disabled_result.value
    settings_text = (home_dir / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert '"disabledMcpjsonServers"' in settings_text
    assert '"demo"' in settings_text

    enabled_result = await command.execute("enable demo", ctx)
    assert "Enabled MCP server 'demo'" in enabled_result.value
    settings_text = (home_dir / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert '"disabledMcpjsonServers"' not in settings_text or '"demo"' not in settings_text

    reset_result = await command.execute("reset-project-choices", ctx)
    assert "Reset all project-scoped MCP approval and rejection choices." in reset_result.value
    settings_text = (home_dir / ".claude" / "settings.json").read_text(encoding="utf-8")
    assert '"disabledMcpjsonServers": []' in settings_text


@pytest.mark.asyncio
async def test_mcp_command_add_from_claude_desktop(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("HOME", str(home_dir))

    async def _noop() -> None:
        return None

    monkeypatch.setattr("open_claude.commands.mcp.connect_mcp_servers", _noop)
    monkeypatch.setattr("open_claude.commands.mcp.disconnect_mcp_servers", _noop)
    monkeypatch.setattr(
        "open_claude.commands.mcp.find_claude_desktop_config_path",
        lambda: home_dir / "AppData" / "Roaming" / "Claude" / "claude_desktop_config.json",
    )
    monkeypatch.setattr(
        "open_claude.commands.mcp.import_claude_desktop_mcp_servers",
        lambda scope: {"desktop-demo": object()},
    )

    command = McpCommand()
    ctx = _DummyContext()

    result = await command.execute("add-from-claude-desktop", ctx)
    assert "Imported 1 MCP server(s) from Claude Desktop." in result.value
