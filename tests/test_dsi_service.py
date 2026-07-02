"""Tests for DSI service calculation logic."""

from logic.dsi_service import classify_dsi, calculate_dsi


def test_classify_dsi_very_fast():
    assert classify_dsi(15) == "Very Fast"


def test_classify_dsi_fast():
    assert classify_dsi(45) == "Fast"


def test_classify_dsi_normal():
    assert classify_dsi(75) == "Normal"


def test_classify_dsi_slow():
    assert classify_dsi(120) == "Slow"


def test_classify_dsi_dead():
    assert classify_dsi(200) == "Dead"


def test_calculate_dsi_basic():
    # DSI = (avg_qty / COGS) * days
    # avg_qty = (100 + 50) / 2 = 75
    # COGS = 1000
    # days = 30
    # DSI = (75 / 1000) * 30 = 2.25
    result = calculate_dsi(
        beginning_qty=100,
        ending_qty=50,
        cogs=1000,
        days=30,
    )
    assert result == 2.25


def test_calculate_dsi_zero_cogs():
    result = calculate_dsi(
        beginning_qty=100,
        ending_qty=50,
        cogs=0,
        days=30,
    )
    assert result is None


def test_calculate_dsi_zero_days():
    result = calculate_dsi(
        beginning_qty=100,
        ending_qty=50,
        cogs=1000,
        days=0,
    )
    assert result is None
