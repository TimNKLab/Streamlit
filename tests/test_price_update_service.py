"""Tests for price tracking via mail.tracking.value."""

import pytest
from logic.price_update_service import PriceUpdateService


def test_analyze_bill_uses_price_tracking(mocker):
    """Test that analyze_bill uses mail.tracking.value when available.

    _init_tax_map and _init_price_field_id run during __init__ (real Odoo).
    Mock starts after init, side_effect covers only analyze_bill calls.
    """
    service = PriceUpdateService()
    mock_search_read = mocker.patch.object(service.conn, 'search_read')

    mock_search_read.side_effect = [
        # get_bill_lines
        [{"product_id": [1, "Test Product"], "price_unit": 10000, "quantity": 1,
          "tax_ids": [], "price_subtotal": 10000}],
        # product.product
        [{"id": 1, "barcode": "TEST123", "product_tmpl_id": [10, "Template"]}],
        # product.template
        [{"id": 10, "name": "Test Product", "list_price": 15000,
          "write_date": "2026-06-26 03:00:00"}],
        # pricelist items
        [],
        # mail.message
        [{"id": 1, "res_id": 10, "model": "product.template", "date": "2026-06-25 14:30:00"}],
        # mail.tracking.value
        [{"create_date": "2026-06-25 14:30:00", "mail_message_id": [1, "message"]}],
        # previous bill lines
        [{"product_id": [1, "Test"], "price_unit": 9000, "tax_ids": [],
          "price_subtotal": 9000, "move_id": [999, "BILL-999"]}],
    ]

    result = service.analyze_bill(bill_id=100)

    assert len(result) > 0
    assert result[0]["price_last_updated"] == "2026-06-25 14:30:00"
    assert result[0]["price_last_updated"] != result[0].get("write_date")


def test_analyze_bill_falls_back_to_write_date(mocker):
    """Test fallback to write_date when no tracking data."""
    service = PriceUpdateService()
    mock_search_read = mocker.patch.object(service.conn, 'search_read')

    mock_search_read.side_effect = [
        # get_bill_lines
        [{"product_id": [1, "Test Product"], "price_unit": 10000, "quantity": 1,
          "tax_ids": [], "price_subtotal": 10000}],
        # product.product
        [{"id": 1, "barcode": "TEST123", "product_tmpl_id": [10, "Template"]}],
        # product.template
        [{"id": 10, "name": "Test Product", "list_price": 15000,
          "write_date": "2026-06-26 03:00:00"}],
        # pricelist items
        [],
        # mail.message (empty - no tracking history)
        [],
        # previous bill lines
        [{"product_id": [1, "Test"], "price_unit": 9000, "tax_ids": [],
          "price_subtotal": 9000, "move_id": [999, "BILL-999"]}],
    ]

    result = service.analyze_bill(bill_id=100)

    assert len(result) > 0
    assert result[0]["price_last_updated"] == "2026-06-26 03:00:00"
