import pytest
from logic.price_update_service import PriceUpdateService


def test_analyze_bill_includes_write_date(mocker):
    """Test that analyze_bill fetches and includes write_date from product.template."""
    service = PriceUpdateService()

    # Mock the connection methods
    mock_search_read = mocker.patch.object(service.conn, 'search_read')

    # Setup mock returns
    mock_search_read.side_effect = [
        # get_bill_lines -> account.move.line
        [{"product_id": [1, "Test Product"], "price_unit": 10000, "quantity": 1,
          "tax_ids": [], "price_subtotal": 10000}],
        # product.product query
        [{"id": 1, "barcode": "TEST123", "product_tmpl_id": [10, "Template"]}],
        # product.template query - SHOULD include write_date
        [{"id": 10, "name": "Test Product", "list_price": 15000,
          "write_date": "2026-06-25 14:30:00"}],
        # pricelist items
        [],
        # previous bill lines
        [{"product_id": [1, "Test"], "price_unit": 9000, "tax_ids": [],
          "price_subtotal": 9000, "move_id": [999, "BILL-999"]}],
    ]

    result = service.analyze_bill(bill_id=100)

    # Verify write_date is in the result
    assert len(result) > 0
    assert "price_last_updated" in result[0]
    assert result[0]["price_last_updated"] == "2026-06-25 14:30:00"
