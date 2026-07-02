"""Tests for DSI service calculation logic."""

from datetime import date
from unittest.mock import patch

import pandas as pd

from logic.dsi_service import classify_dsi, calculate_dsi, compute_dsi_report


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


def test_compute_dsi_report_with_mock_data():
    """Test compute_dsi_report returns correct DataFrame with mocked Odoo data."""
    mock_beginning = [
        {"product_id": [1, "P1"], "remaining_qty": 100.0, "remaining_value": 500.0},
    ]
    mock_ending = [
        {"product_id": [1, "P1"], "remaining_qty": 50.0, "remaining_value": 250.0},
    ]
    mock_products = [
        {"id": 1, "barcode": "123", "name": "Test Product", "categ_id": [10, "Test Cat"]},
    ]

    # search_read called 3 times: beginning valuation, ending valuation, product info
    with patch("logic.dsi_service.connection_manager.search_read") as mock_search:
        mock_search.side_effect = [mock_beginning, mock_ending, mock_products]

        df = compute_dsi_report(date(2026, 1, 1), date(2026, 1, 31))

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["product_id"] == 1
    assert row["barcode"] == "123"
    assert row["name"] == "Test Product"
    assert row["category"] == "Test Cat"
    assert row["beginning_qty"] == 100.0
    assert row["ending_qty"] == 50.0
    assert row["avg_qty"] == 75.0
    assert row["cogs"] == 250.0
    # DSI = (75 / 250) * 30 = 9.0
    assert row["dsi"] == 9.0
    assert row["classification"] == "Very Fast"


def test_compute_dsi_report_empty():
    """Test compute_dsi_report returns empty DataFrame when no data."""
    with patch("logic.dsi_service.connection_manager.search_read") as mock_search:
        mock_search.return_value = []
        df = compute_dsi_report(date(2026, 1, 1), date(2026, 1, 31))
    assert isinstance(df, pd.DataFrame)
    assert df.empty
