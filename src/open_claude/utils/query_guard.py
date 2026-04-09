"""Synchronous query lifecycle guard for single-active-turn execution."""

from __future__ import annotations

from collections.abc import Callable


class QueryGuard:
    """Guard a query lifecycle with idle/dispatching/running states."""

    def __init__(self) -> None:
        self._status = "idle"
        self._generation = 0
        self._subscribers: set[Callable[[], None]] = set()

    def reserve(self) -> bool:
        if self._status != "idle":
            return False
        self._status = "dispatching"
        self._notify()
        return True

    def cancel_reservation(self) -> None:
        if self._status != "dispatching":
            return
        self._status = "idle"
        self._notify()

    def try_start(self) -> int | None:
        if self._status == "running":
            return None
        self._status = "running"
        self._generation += 1
        self._notify()
        return self._generation

    def end(self, generation: int) -> bool:
        if self._generation != generation or self._status != "running":
            return False
        self._status = "idle"
        self._notify()
        return True

    def force_end(self) -> None:
        if self._status == "idle":
            return
        self._status = "idle"
        self._generation += 1
        self._notify()

    @property
    def is_active(self) -> bool:
        return self._status != "idle"

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def status(self) -> str:
        return self._status

    def subscribe(self, callback: Callable[[], None]) -> Callable[[], None]:
        self._subscribers.add(callback)

        def _unsubscribe() -> None:
            self._subscribers.discard(callback)

        return _unsubscribe

    def get_snapshot(self) -> bool:
        return self.is_active

    def _notify(self) -> None:
        for callback in tuple(self._subscribers):
            callback()
