"""API error types for retry and fallback logic."""

from __future__ import annotations


class RetryableError(Exception):
    """Base class for errors that can be retried."""

    def __init__(self, message: str, *, original_error: Exception | None = None) -> None:
        super().__init__(message)
        self.original_error = original_error


class FallbackTriggeredError(Exception):
    """Raised when model fallback is triggered after repeated 529 overload errors."""

    REPEATED_529_MESSAGE = (
        "Claude is experiencing heavy traffic. "
        "Please try again in a few minutes."
    )

    def __init__(self, original_model: str, fallback_model: str) -> None:
        self.original_model = original_model
        self.fallback_model = fallback_model
        super().__init__(
            f"Model fallback triggered: {original_model} -> {fallback_model}"
        )


class ContextOverflowError(RetryableError):
    """Raised when input + max_tokens exceeds the model context window."""

    def __init__(
        self,
        message: str,
        *,
        input_tokens: int = 0,
        max_tokens: int = 0,
        context_limit: int = 0,
        available_tokens: int = 0,
    ) -> None:
        super().__init__(message)
        self.input_tokens = input_tokens
        self.max_tokens = max_tokens
        self.context_limit = context_limit
        self.available_tokens = available_tokens


class AuthenticationError(RetryableError):
    """Raised on 401/403 authentication failures."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(RetryableError):
    """Raised on 429 rate limit errors."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after = retry_after
