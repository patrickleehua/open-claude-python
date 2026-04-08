import asyncio

import pytest

from open_claude.components.ui.chat_app import ChatApp, _PermissionModeDialog


@pytest.mark.asyncio
async def test_show_permission_dialog_like_uses_wait_for_dismiss(monkeypatch: pytest.MonkeyPatch) -> None:
    app = ChatApp()
    dialog = _PermissionModeDialog("default")
    expected = "auto"
    future = asyncio.get_running_loop().create_future()
    future.set_result(expected)
    recorded: dict[str, object] = {}

    def fake_push_screen(screen, callback=None, wait_for_dismiss=False):
        recorded["screen"] = screen
        recorded["callback"] = callback
        recorded["wait_for_dismiss"] = wait_for_dismiss
        return future

    monkeypatch.setattr(app, "push_screen", fake_push_screen)

    result = await app._show_permission_dialog_like(dialog)

    assert result == expected
    assert recorded["screen"] is dialog
    assert recorded["wait_for_dismiss"] is True
    assert recorded["callback"] is None


@pytest.mark.asyncio
async def test_show_permission_dialog_like_falls_back_to_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    app = ChatApp()
    dialog = _PermissionModeDialog("default")
    expected = "plan"
    recorded: dict[str, object] = {}

    def fake_push_screen(screen, callback=None, wait_for_dismiss=False):
        if wait_for_dismiss:
            raise TypeError("wait_for_dismiss unsupported")
        recorded["screen"] = screen
        recorded["callback"] = callback
        callback(expected)
        return None

    monkeypatch.setattr(app, "push_screen", fake_push_screen)

    result = await app._show_permission_dialog_like(dialog)

    assert result == expected
    assert recorded["screen"] is dialog
    assert callable(recorded["callback"])
