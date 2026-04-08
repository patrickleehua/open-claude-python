"""Token usage tracking for API calls."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TokenUsage:
    """Tracks cumulative token usage across API calls."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def get_total_tokens(self) -> int:
        """Return the total tokens used (input + output)."""
        return self.input_tokens + self.output_tokens

    def get_total_cache_tokens(self) -> int:
        """Return total cache-related tokens."""
        return self.cache_creation_input_tokens + self.cache_read_input_tokens

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return accumulate_usage(self, other)


def update_usage(current: TokenUsage, response_usage: dict) -> None:
    """Update current usage from an API response usage dict.

    Only updates fields that have non-zero values in the response,
    supporting cumulative tracking where the API returns deltas.
    """
    if not response_usage:
        return

    input_tokens = response_usage.get("input_tokens", 0) or 0
    output_tokens = response_usage.get("output_tokens", 0) or 0
    cache_creation = response_usage.get("cache_creation_input_tokens", 0) or 0
    cache_read = response_usage.get("cache_read_input_tokens", 0) or 0

    if input_tokens:
        current.input_tokens += input_tokens
    if output_tokens:
        current.output_tokens += output_tokens
    if cache_creation:
        current.cache_creation_input_tokens += cache_creation
    if cache_read:
        current.cache_read_input_tokens += cache_read


def accumulate_usage(usage_a: TokenUsage, usage_b: TokenUsage) -> TokenUsage:
    """Sum two TokenUsage instances into a new one."""
    return TokenUsage(
        input_tokens=usage_a.input_tokens + usage_b.input_tokens,
        output_tokens=usage_a.output_tokens + usage_b.output_tokens,
        cache_creation_input_tokens=(
            usage_a.cache_creation_input_tokens
            + usage_b.cache_creation_input_tokens
        ),
        cache_read_input_tokens=(
            usage_a.cache_read_input_tokens
            + usage_b.cache_read_input_tokens
        ),
    )
