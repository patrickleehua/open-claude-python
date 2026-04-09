from __future__ import annotations

from open_claude.utils.query_guard import QueryGuard


def test_query_guard_transitions_and_generation() -> None:
    guard = QueryGuard()

    assert guard.status == "idle"
    assert guard.is_active is False

    assert guard.reserve() is True
    assert guard.status == "dispatching"
    assert guard.is_active is True

    generation = guard.try_start()
    assert generation == 1
    assert guard.status == "running"
    assert guard.is_active is True

    assert guard.end(generation) is True
    assert guard.status == "idle"
    assert guard.is_active is False


def test_query_guard_force_end_invalidates_stale_cleanup() -> None:
    guard = QueryGuard()

    generation = guard.try_start()
    assert generation == 1

    guard.force_end()

    assert guard.status == "idle"
    assert guard.generation == 2
    assert guard.end(generation) is False
