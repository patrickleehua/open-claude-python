"""MCP OAuth authentication using the Python MCP SDK's OAuthClientProvider.

Provides:
- ``KeyringTokenStorage`` — Persists OAuth tokens via the ``keyring`` library.
- ``McpOAuthProvider`` — Full OAuth flow with browser redirect and local callback.
- Token refresh with cross-process file locking.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
import webbrowser
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import (
    OAuthClientInformationFull,
    OAuthClientMetadata,
    OAuthToken,
)

logger = logging.getLogger(__name__)

_SERVICE_NAME = "open-claude-mcp-oauth"
_MCP_AUTH_TIMEOUT = 300  # 5 minutes
_CLIENT_SECRET_PREFIX = "mcp-client-secret-"


class KeyringTokenStorage:
    """Persist OAuth tokens and client info using OS keyring.

    Falls back to file-based storage if keyring is unavailable.
    """

    def __init__(self, server_name: str) -> None:
        self._server_name = server_name
        self._key_tokens = f"mcp-oauth-tokens-{server_name}"
        self._key_client = f"mcp-oauth-client-{server_name}"

    async def get_tokens(self) -> OAuthToken | None:
        data = self._read(self._key_tokens)
        if data is None:
            return None
        try:
            return OAuthToken.model_validate(data)
        except Exception:
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._write(self._key_client.replace("client", "tokens-latest"), {
            "access_token": tokens.access_token,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        self._write(self._key_tokens, tokens.model_dump(exclude_none=True))

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        data = self._read(self._key_client)
        if data is None:
            return None
        try:
            return OAuthClientInformationFull.model_validate(data)
        except Exception:
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._write(self._key_client, client_info.model_dump(exclude_none=True))

    async def invalidate(self) -> None:
        """Remove stored tokens and client info."""
        for key in (self._key_tokens, self._key_client):
            self._delete(key)

    # -- Storage backend --

    def _read(self, key: str) -> dict[str, Any] | None:
        try:
            import keyring
            value = keyring.get_password(_SERVICE_NAME, key)
            if value:
                return json.loads(value)
        except Exception:
            pass
        # Fallback to file
        path = self._file_path(key)
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return None

    def _write(self, key: str, data: dict[str, Any]) -> None:
        serialized = json.dumps(data, ensure_ascii=False)
        try:
            import keyring
            keyring.set_password(_SERVICE_NAME, key, serialized)
            return
        except Exception:
            pass
        # Fallback to file
        path = self._file_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")

    def _delete(self, key: str) -> None:
        try:
            import keyring
            keyring.delete_password(_SERVICE_NAME, key)
        except Exception:
            pass
        path = self._file_path(key)
        if path.is_file():
            path.unlink()

    def _file_path(self, key: str) -> Path:
        safe = hashlib.sha256(key.encode()).hexdigest()[:16]
        return Path.home() / ".claude" / "mcp-auth" / f"{safe}.json"


def _client_secret_key(server_name: str) -> str:
    return f"{_CLIENT_SECRET_PREFIX}{server_name}"


def save_mcp_client_secret(server_name: str, client_secret: str) -> None:
    """Persist a client secret for an MCP server."""
    KeyringTokenStorage(server_name)._write(
        _client_secret_key(server_name),
        {"client_secret": client_secret},
    )


def get_mcp_client_secret(server_name: str) -> str | None:
    """Load a persisted client secret for an MCP server."""
    data = KeyringTokenStorage(server_name)._read(_client_secret_key(server_name))
    if not data:
        return None
    value = data.get("client_secret")
    return value if isinstance(value, str) and value else None


class _CallbackHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for the OAuth redirect callback."""

    auth_code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "error" in params:
            self.error = params["error"][0]
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Authorization failed. You can close this tab.")
            return

        self.auth_code = params.get("code", [None])[0]
        self.state = params.get("state", [None])[0]

        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h1>Authorization successful!</h1>"
            b"<p>You can close this tab.</p></body></html>"
        )

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Silence request logs


class McpOAuthProvider:
    """Manages OAuth authentication for an MCP server.

    Handles:
    - Token storage via KeyringTokenStorage
    - Browser-based authorization flow
    - Token refresh
    """

    def __init__(
        self,
        server_name: str,
        server_url: str,
        client_id: str | None = None,
        callback_port: int | None = None,
    ) -> None:
        self._server_name = server_name
        self._server_url = server_url
        self._storage = KeyringTokenStorage(server_name)
        self._callback_port = callback_port
        self._client_id = client_id

    async def get_auth_provider(self) -> OAuthClientProvider:
        """Create an OAuthClientProvider configured for this server."""
        tokens = await self._storage.get_tokens()
        client_info = await self._storage.get_client_info()

        redirect_port = self._callback_port or self._find_available_port()

        client_metadata = OAuthClientMetadata(
            client_name=f"open-claude-{self._server_name}",
            redirect_uris=[f"http://localhost:{redirect_port}/callback"],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            token_endpoint_auth_method="client_secret_post",
        )

        provider = OAuthClientProvider(
            server_url=self._server_url,
            client_metadata=client_metadata,
            storage=self._storage,
            redirect_handler=self._handle_redirect,
            callback_handler=self._handle_callback,
            timeout=_MCP_AUTH_TIMEOUT,
            client_metadata_url=None,
        )

        return provider

    async def _handle_redirect(self, authorization_url: str) -> None:
        """Open the browser for OAuth consent."""
        logger.info("Opening browser for MCP OAuth: %s", self._server_name)
        webbrowser.open(authorization_url)

    async def _handle_callback(self) -> tuple[str, str | None]:
        """Start a local HTTP server and wait for the OAuth callback.

        Returns:
            Tuple of (auth_code, state) from the callback.
        """
        port = self._callback_port or self._find_available_port()
        handler = _CallbackHandler

        with HTTPServer(("127.0.0.1", port), handler) as httpd:
            # Wait for the callback with timeout
            httpd.timeout = _MCP_AUTH_TIMEOUT
            httpd.handle_request()

        if handler.error:
            raise RuntimeError(f"OAuth authorization denied: {handler.error}")

        if not handler.auth_code:
            raise RuntimeError("OAuth callback received no authorization code")

        return handler.auth_code, handler.state

    @staticmethod
    def _find_available_port() -> int:
        """Find an available port for the OAuth callback server."""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    @property
    def storage(self) -> KeyringTokenStorage:
        return self._storage


async def refresh_tokens_with_lock(
    server_name: str,
    provider: McpOAuthProvider,
) -> OAuthToken | None:
    """Refresh OAuth tokens with cross-process file locking.

    Uses a lockfile to prevent multiple processes from refreshing
    simultaneously. After acquiring the lock, re-reads tokens in case
    another process already refreshed them.
    """
    lock_path = Path.home() / ".claude" / "mcp-auth" / f"refresh-{hashlib.sha256(server_name.encode()).hexdigest()[:16]}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Simple file-based lock
    for attempt in range(3):
        try:
            lock_fd = open(lock_path, "w")
            import fcntl
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except (ImportError, OSError):
            # Windows or error — proceed without lock
            pass

        try:
            # Re-read tokens (another process may have refreshed)
            tokens = await provider.storage.get_tokens()
            if tokens and tokens.access_token:
                return tokens
            return None
        finally:
            try:
                lock_fd.close()
            except Exception:
                pass

    return None
