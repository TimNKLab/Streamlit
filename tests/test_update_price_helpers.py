"""Tests for Update Harga page helper functions."""

import pytest
from ui.pages.update_price import _fmt_datetime


def test_fmt_datetime_with_valid_timestamp():
    """Test formatting valid ISO timestamp to Indonesian format."""
    result = _fmt_datetime("2026-06-25 14:30:00")
    assert result == "25/06/2026 14:30"


def test_fmt_datetime_with_none():
    """Test formatting None returns dash."""
    result = _fmt_datetime(None)
    assert result == "-"


def test_fmt_datetime_with_empty_string():
    """Test formatting empty string returns dash."""
    result = _fmt_datetime("")
    assert result == "-"


def test_fmt_datetime_with_invalid_format():
    """Test formatting invalid timestamp returns dash."""
    result = _fmt_datetime("invalid-date")
    assert result == "-"
