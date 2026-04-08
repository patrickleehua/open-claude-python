"""Tests for utils.memory.age — Memory age utilities."""

from __future__ import annotations

import time

import pytest

from open_claude.utils.memory.age import (
    memory_age,
    memory_age_days,
    memory_freshness_note,
    memory_freshness_text,
)


class TestMemoryAgeDays:
    def test_today_is_zero(self):
        now_ms = time.time() * 1000
        assert memory_age_days(now_ms) == 0

    def test_yesterday_is_one(self):
        one_day_ago_ms = (time.time() - 86_400) * 1000
        assert memory_age_days(one_day_ago_ms) == 1

    def test_week_ago(self):
        seven_days_ago_ms = (time.time() - 7 * 86_400) * 1000
        assert memory_age_days(seven_days_ago_ms) == 7

    def test_future_clamps_to_zero(self):
        future_ms = (time.time() + 10_000) * 1000
        assert memory_age_days(future_ms) == 0


class TestMemoryAge:
    def test_today(self):
        now_ms = time.time() * 1000
        assert memory_age(now_ms) == "today"

    def test_yesterday(self):
        one_day_ago_ms = (time.time() - 86_400) * 1000
        assert memory_age(one_day_ago_ms) == "yesterday"

    def test_days_ago(self):
        five_days_ago_ms = (time.time() - 5 * 86_400) * 1000
        assert memory_age(five_days_ago_ms) == "5 days ago"


class TestMemoryFreshnessText:
    def test_today_no_warning(self):
        now_ms = time.time() * 1000
        assert memory_freshness_text(now_ms) == ""

    def test_yesterday_no_warning(self):
        one_day_ago_ms = (time.time() - 86_400) * 1000
        assert memory_freshness_text(one_day_ago_ms) == ""

    def test_old_memory_has_warning(self):
        five_days_ago_ms = (time.time() - 5 * 86_400) * 1000
        text = memory_freshness_text(five_days_ago_ms)
        assert "5 days old" in text
        assert "outdated" in text


class TestMemoryFreshnessNote:
    def test_today_empty(self):
        now_ms = time.time() * 1000
        assert memory_freshness_note(now_ms) == ""

    def test_old_wrapped_in_system_reminder(self):
        five_days_ago_ms = (time.time() - 5 * 86_400) * 1000
        note = memory_freshness_note(five_days_ago_ms)
        assert note.startswith("<system-reminder>")
        assert note.strip().endswith("</system-reminder>")
