"""Permission context factory for the permission hook system.

Ported from Claude-Code-rev src/hooks/toolPermission/PermissionContext.ts.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from open_claude.schemas.permissions import (
    PermissionAllowDecision,
    PermissionAskDecision,
    PermissionDecision,
    PermissionDenyDecision,
    PermissionUpdate,
    ToolPermissionContext,
)
from open_claude.utils.permissions.update import (
    apply_permission_updates,
    persist_permission_updates,
    supports_persistence,
)

logger = logging.getLogger(__name__)


class ResolveOnce:
    """Atomic promise resolution helper to prevent race conditions."""

    def __init__(self, resolve_func):
        self._resolve_func = resolve_func
        self._claimed = False
        self._delivered = False

    def resolve(self, value):
        if self._delivered:
            return
        self._delivered = True
        self._claimed = True
        self._resolve_func(value)

    def is_resolved(self) -> bool:
        return self._claimed

    def claim(self) -> bool:
        if self._claimed:
            return False
        self._claimed = True
        return True


class PermissionContext:
    """Coordinates permission checks between the pipeline and the UI.

    Provides methods to log decisions, persist permission changes,
    manage the permission prompt queue, and build allow/deny decisions.
    """

    def __init__(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        tool_use_id: str,
        permission_context: ToolPermissionContext,
        set_permission_context: Any = None,
        abort_signal: asyncio.Event | None = None,
    ):
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.tool_use_id = tool_use_id
        self._permission_context = permission_context
        self._set_permission_context = set_permission_context
        self._abort_signal = abort_signal

    @property
    def context(self) -> ToolPermissionContext:
        return self._permission_context

    def log_decision(self, decision_type: str, **kwargs):
        """Log a permission decision."""
        logger.debug("Permission %s for tool %s", decision_type, self.tool_name)

    def log_cancelled(self):
        """Log that the permission request was cancelled."""
        logger.debug("Permission cancelled for tool %s", self.tool_name)

    async def persist_permissions(self, updates: list[PermissionUpdate]) -> bool:
        """Persist permission updates and apply to context.

        Returns True if any update was persisted to disk.
        """
        if not updates:
            return False
        persist_permission_updates(updates)
        if self._set_permission_context is not None:
            updated_ctx = apply_permission_updates(self._permission_context, updates)
            self._permission_context = updated_ctx
            self._set_permission_context(updated_ctx)
        return any(
            supports_persistence(getattr(u, "destination", None))
            for u in updates
        )

    def resolve_if_aborted(self, resolve_func) -> bool:
        """Check if aborted and resolve with a cancel decision."""
        if self._abort_signal and self._abort_signal.is_set():
            self.log_cancelled()
            resolve_func(self.build_ask("Request cancelled"))
            return True
        return False

    def cancel_and_abort(self, feedback: str | None = None) -> PermissionDecision:
        """Build a cancel decision and optionally abort."""
        message = feedback or f"Request cancelled: {self.tool_name}"
        if self._abort_signal:
            self._abort_signal.set()
        return self.build_ask(message)

    def build_allow(
        self,
        updated_input: dict[str, Any],
        *,
        user_modified: bool = False,
        decision_reason: Any = None,
        accept_feedback: str | None = None,
    ) -> PermissionAllowDecision:
        """Build an allow decision."""
        return PermissionAllowDecision(
            updated_input=updated_input,
            user_modified=user_modified,
            decision_reason=decision_reason,
            accept_feedback=accept_feedback,
        )

    def build_deny(
        self,
        message: str,
        decision_reason: Any = None,
    ) -> PermissionDenyDecision:
        """Build a deny decision."""
        return PermissionDenyDecision(
            message=message,
            decision_reason=decision_reason,
        )

    def build_ask(self, message: str) -> PermissionAskDecision:
        """Build an ask decision."""
        return PermissionAskDecision(message=message)

    async def handle_user_allow(
        self,
        updated_input: dict[str, Any],
        permission_updates: list[PermissionUpdate],
        feedback: str | None = None,
        decision_reason: Any = None,
    ) -> PermissionAllowDecision:
        """Handle a user approval — persist permissions and build allow."""
        accepted_permanent = await self.persist_permissions(permission_updates)
        self.log_decision("accept", permanent=accepted_permanent)
        user_modified = updated_input != self.tool_input
        return self.build_allow(
            updated_input,
            user_modified=user_modified,
            decision_reason=decision_reason,
            accept_feedback=feedback.strip() if feedback else None,
        )


def create_permission_context(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_use_id: str,
    permission_context: ToolPermissionContext,
    set_permission_context: Any = None,
    abort_signal: asyncio.Event | None = None,
) -> PermissionContext:
    """Factory function to create a PermissionContext."""
    return PermissionContext(
        tool_name=tool_name,
        tool_input=tool_input,
        tool_use_id=tool_use_id,
        permission_context=permission_context,
        set_permission_context=set_permission_context,
        abort_signal=abort_signal,
    )
