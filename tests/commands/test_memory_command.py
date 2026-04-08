from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from open_claude.commands.memory import MemoryCommand
from open_claude.schemas.permissions import PermissionMode, ToolPermissionContext
from open_claude.utils.memory.paths import get_memory_dir


@dataclass
class _DummyContext:
    messages: list[dict] = field(default_factory=list)
    model_name: str = "claude-sonnet-4-20250514"
    token_usage: object | None = None
    permission_context: ToolPermissionContext = field(default_factory=ToolPermissionContext)

    def clear_conversation(self) -> None:
        self.messages.clear()

    def compact_conversation(self, instructions: str = ""):
        return None

    def load_settings(self) -> dict:
        return {}

    def set_permission_mode(self, mode: PermissionMode) -> None:
        self.permission_context.mode = mode

    async def refresh_tools(self) -> None:
        return None


@pytest.mark.asyncio
async def test_memory_command_init_and_show_session(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("HOME", str(home_dir))

    command = MemoryCommand()
    ctx = _DummyContext()

    init_result = await command.execute("init", ctx)
    assert "Initialized memory files." in init_result.value

    show_result = await command.execute("show session", ctx)
    assert "Session Memory" in show_result.value or "session memory file is empty or not initialized" in show_result.value.lower()


@pytest.mark.asyncio
async def test_memory_command_list_and_open(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.chdir(project_dir)
    monkeypatch.setenv("HOME", str(home_dir))

    opened: dict[str, str] = {}

    def fake_open_file_in_editor(path: str) -> str:
        opened["path"] = path
        return "EDITOR"

    monkeypatch.setattr("open_claude.commands.memory.open_file_in_editor", fake_open_file_in_editor)

    command = MemoryCommand()
    ctx = _DummyContext()

    await command.execute("init", ctx)
    custom_file = get_memory_dir() / "note.md"
    custom_file.parent.mkdir(parents=True, exist_ok=True)
    custom_file.write_text("---\ndescription: demo\n---\nbody", encoding="utf-8")

    list_result = await command.execute("", ctx)
    assert "Memory Files" in list_result.value
    assert "3. note.md" in list_result.value

    open_result = await command.execute("open note.md", ctx)
    assert "Opened memory file at" in open_result.value
    assert opened["path"].endswith("note.md")

    open_by_index_result = await command.execute("3", ctx)
    assert "Opened memory file at" in open_by_index_result.value
