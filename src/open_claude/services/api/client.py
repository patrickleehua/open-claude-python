"""Multi-provider Anthropic API client factory."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field

from anthropic import AsyncAnthropic

from open_claude.constants import APP_NAME, APP_VERSION


@dataclass
class ClientConfig:
    """Configuration for creating an Anthropic API client."""

    api_key: str | None = None
    use_bedrock: bool = False
    use_vertex: bool = False
    api_url: str | None = None
    custom_headers: dict[str, str] = field(default_factory=dict)


def _get_user_agent() -> str:
    """Build the User-Agent string."""
    return f"{APP_NAME}/{APP_VERSION}"


def _get_session_id() -> str:
    """Generate or retrieve a session ID."""
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if session_id:
        return session_id
    session_id = str(uuid.uuid4())
    os.environ["CLAUDE_CODE_SESSION_ID"] = session_id
    return session_id


def _parse_custom_headers(env_value: str) -> dict[str, str]:
    """Parse ANTHROPIC_CUSTOM_HEADERS env var (newline-separated 'Name: Value' pairs)."""
    headers: dict[str, str] = {}
    for line in env_value.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if not line:
            continue
        colon_idx = line.find(":")
        if colon_idx == -1:
            continue
        name = line[:colon_idx].strip()
        value = line[colon_idx + 1 :].strip()
        if name:
            headers[name] = value
    return headers


def _build_default_headers(config: ClientConfig) -> dict[str, str]:
    """Build the default headers sent with every request."""
    headers: dict[str, str] = {
        "x-app": "cli",
        "User-Agent": _get_user_agent(),
        "X-Claude-Code-Session-Id": _get_session_id(),
    }

    # Merge environment-based custom headers
    env_headers_str = os.environ.get("ANTHROPIC_CUSTOM_HEADERS")
    if env_headers_str:
        headers.update(_parse_custom_headers(env_headers_str))

    # Merge config-level custom headers (highest priority)
    headers.update(config.custom_headers)

    # Container / remote session identification
    container_id = os.environ.get("CLAUDE_CODE_CONTAINER_ID")
    if container_id:
        headers["x-claude-remote-container-id"] = container_id
    remote_session_id = os.environ.get("CLAUDE_CODE_REMOTE_SESSION_ID")
    if remote_session_id:
        headers["x-claude-remote-session-id"] = remote_session_id

    return headers


def _detect_provider(config: ClientConfig) -> str:
    """Detect the API provider from config and environment.

    Priority: Bedrock > Vertex > Direct
    """
    if config.use_bedrock or os.environ.get("CLAUDE_CODE_USE_BEDROCK"):
        return "bedrock"
    if config.use_vertex or os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        return "vertex"
    return "direct"


def _create_bedrock_client(config: ClientConfig, headers: dict[str, str]) -> AsyncAnthropic:
    """Create an AsyncAnthropic client configured for AWS Bedrock."""
    region = os.environ.get("AWS_REGION") or os.environ.get(
        "AWS_DEFAULT_REGION", "us-east-1"
    )

    client_kwargs: dict = {
        "default_headers": headers,
        "max_retries": 0,
        "timeout": int(os.environ.get("API_TIMEOUT_MS", 600_000)),
    }

    # Use the Anthropic Bedrock base URL pattern
    base_url = f"https://bedrock-runtime.{region}.amazonaws.com"

    # Bearer token auth for Bedrock
    bearer_token = os.environ.get("AWS_BEARER_TOKEN_BEDROCK")
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    client_kwargs["base_url"] = config.api_url or base_url
    client_kwargs["api_key"] = config.api_key or ""

    return AsyncAnthropic(**client_kwargs)


def _create_vertex_client(config: ClientConfig, headers: dict[str, str]) -> AsyncAnthropic:
    """Create an AsyncAnthropic client configured for Google Vertex AI."""
    region = (
        os.environ.get("CLOUD_ML_REGION")
        or os.environ.get("VERTEX_REGION")
        or "us-east5"
    )
    project_id = os.environ.get("ANTHROPIC_VERTEX_PROJECT_ID", "")

    base_url = f"https://{region}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{region}/publishers/anthropic"

    client_kwargs: dict = {
        "default_headers": headers,
        "max_retries": 0,
        "timeout": int(os.environ.get("API_TIMEOUT_MS", 600_000)),
        "base_url": config.api_url or base_url,
        "api_key": config.api_key or "",
    }

    return AsyncAnthropic(**client_kwargs)


def _create_direct_client(config: ClientConfig, headers: dict[str, str]) -> AsyncAnthropic:
    """Create a standard AsyncAnthropic client."""
    api_key = (
        config.api_key
        or os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )
    base_url = config.api_url or os.environ.get("ANTHROPIC_BASE_URL")

    client_kwargs: dict = {
        "api_key": api_key,
        "default_headers": headers,
        "max_retries": 0,
        "timeout": int(os.environ.get("API_TIMEOUT_MS", 600_000)),
    }

    if base_url:
        client_kwargs["base_url"] = base_url

    return AsyncAnthropic(**client_kwargs)


# Module-level singleton — ensures sub-agents reuse the parent's client.
_cached_client: AsyncAnthropic | None = None


def get_client(config: ClientConfig | None = None) -> AsyncAnthropic:
    """Create (or return cached) AsyncAnthropic client based on the detected provider.

    The first call with an explicit ``config`` creates and caches the client.
    Subsequent calls (with or without config) return the same instance, so
    sub-agents spawned by AgentTool automatically reuse the parent's credentials.

    Supports three providers:
    - Direct Anthropic API (default)
    - AWS Bedrock (CLAUDE_CODE_USE_BEDROCK)
    - Google Vertex AI (CLAUDE_CODE_USE_VERTEX)

    Provider detection priority: Bedrock > Vertex > Direct.
    """
    global _cached_client

    # Return cached client when caller doesn't supply a custom config
    if config is None:
        if _cached_client is not None:
            return _cached_client
        config = ClientConfig()

    headers = _build_default_headers(config)
    provider = _detect_provider(config)

    if provider == "bedrock":
        client = _create_bedrock_client(config, headers)
    elif provider == "vertex":
        client = _create_vertex_client(config, headers)
    else:
        client = _create_direct_client(config, headers)

    _cached_client = client
    return client
