"""Retry with exponential backoff for API calls."""

from __future__ import annotations

import asyncio
import random
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, TypeVar

from anthropic import APIConnectionError, APIStatusError

from open_claude.services.api.errors import (
    AuthenticationError,
    ContextOverflowError,
    FallbackTriggeredError,
    RateLimitError,
    RetryableError,
)

T = TypeVar("T")

# Context overflow parsing regex
_CONTEXT_OVERFLOW_RE = re.compile(
    r"input length and `max_tokens` exceed context limit: (\d+) \+ (\d+) > (\d+)"
)

_MAX_529_RETRIES = 3
_FLOOR_OUTPUT_TOKENS = 3000


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 10
    base_delay_ms: int = 500
    max_delay_ms: int = 32000


def _is_529_overloaded(error: Exception) -> bool:
    """Check if the error is a 529 overloaded error."""
    if isinstance(error, APIStatusError):
        if error.status_code == 529:
            return True
        msg = str(error.message) if error.message else ""
        if "overloaded_error" in msg:
            return True
    return False


def _should_retry(error: Exception) -> bool:
    """Determine if an error is retryable."""
    # Connection errors are always retryable
    if isinstance(error, APIConnectionError):
        return True

    if isinstance(error, APIStatusError):
        status = error.status_code

        # Request timeout
        if status == 408:
            return True
        # Rate limit
        if status == 429:
            return True
        # 529 overloaded
        if _is_529_overloaded(error):
            return True
        # Server errors (5xx)
        if status >= 500:
            return True
        # Context overflow - parseable and retryable
        if _parse_context_overflow(error) is not None:
            return True

    # Our own retryable errors
    if isinstance(error, RetryableError):
        return True

    return False


def _parse_context_overflow(
    error: Exception,
) -> tuple[int, int, int] | None:
    """Parse context overflow error to extract (input_tokens, max_tokens, context_limit).

    Example message: "input length and `max_tokens` exceed context limit: 188059 + 20000 > 200000"
    """
    if not isinstance(error, APIStatusError) or error.status_code != 400:
        return None

    message = str(error.message) if error.message else ""
    match = _CONTEXT_OVERFLOW_RE.search(message)
    if not match:
        return None

    input_tokens = int(match.group(1))
    max_tokens = int(match.group(2))
    context_limit = int(match.group(3))
    return input_tokens, max_tokens, context_limit


def _get_retry_after_ms(error: Exception) -> float | None:
    """Extract retry-after value from error headers, in milliseconds."""
    if isinstance(error, APIStatusError) and error.response:
        retry_after = error.response.headers.get("retry-after")
        if retry_after:
            try:
                return float(retry_after) * 1000
            except (ValueError, TypeError):
                pass
    return None


def _compute_delay(
    attempt: int,
    config: RetryConfig,
    retry_after_ms: float | None = None,
) -> float:
    """Compute the delay before the next retry in milliseconds.

    Uses exponential backoff: min(base * 2^attempt, max_delay) + random jitter.
    Jitter is 0-25% of the base delay.
    """
    if retry_after_ms is not None:
        return retry_after_ms

    base_delay = min(
        config.base_delay_ms * (2 ** (attempt - 1)),
        config.max_delay_ms,
    )
    jitter = random.random() * 0.25 * config.base_delay_ms
    return base_delay + jitter


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    config: RetryConfig | None = None,
    on_retry: Callable[[int, float, Exception], Awaitable[None]] | None = None,
) -> T:
    """Execute an async function with retry and exponential backoff.

    Args:
        fn: Async callable to execute.
        config: Retry configuration. Uses defaults if not provided.
        on_retry: Optional callback invoked before each retry with
                  (attempt, delay_ms, error).

    Returns:
        The result of fn() on success.

    Raises:
        FallbackTriggeredError: After 3 consecutive 529 overload errors.
        ContextOverflowError: When context limit is exceeded and not recoverable.
        AuthenticationError: On non-retryable 401/403 errors.
        The original exception if retries are exhausted.
    """
    if config is None:
        config = RetryConfig()

    consecutive_529 = 0
    last_error: Exception | None = None

    for attempt in range(1, config.max_retries + 2):
        try:
            return await fn()
        except Exception as error:
            last_error = error

            # Track consecutive 529 errors
            if _is_529_overloaded(error):
                consecutive_529 += 1
                if consecutive_529 >= _MAX_529_RETRIES:
                    raise FallbackTriggeredError("unknown", "fallback") from error
            else:
                consecutive_529 = 0

            # Exhausted retries
            if attempt > config.max_retries:
                raise

            # Non-retryable error
            if not _should_retry(error):
                raise

            # Handle context overflow recovery
            overflow = _parse_context_overflow(error)
            if overflow is not None:
                input_tokens, max_tokens, context_limit = overflow
                safety_buffer = 1000
                available = max(0, context_limit - input_tokens - safety_buffer)
                if available < _FLOOR_OUTPUT_TOKENS:
                    raise ContextOverflowError(
                        str(error),
                        input_tokens=input_tokens,
                        max_tokens=max_tokens,
                        context_limit=context_limit,
                        available_tokens=available,
                    ) from error
                # If recoverable, continue retrying (caller should adjust max_tokens)
                continue

            # Handle specific error types
            if isinstance(error, APIStatusError):
                if error.status_code in (401, 403):
                    raise AuthenticationError(
                        str(error), status_code=error.status_code
                    ) from error
                if error.status_code == 429:
                    retry_after = _get_retry_after_ms(error)
                    raise RateLimitError(
                        str(error), retry_after=retry_after
                    ) from error

            # Compute backoff delay
            retry_after_ms = _get_retry_after_ms(error)
            delay_ms = _compute_delay(attempt, config, retry_after_ms)

            # Notify caller before sleeping
            if on_retry is not None:
                await on_retry(attempt, delay_ms, error)

            await asyncio.sleep(delay_ms / 1000.0)

    # Should not reach here, but just in case
    if last_error is not None:
        raise last_error
    raise RuntimeError("retry_with_backoff exited without a result or error")
