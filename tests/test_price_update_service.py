"""Tests for price tracking via mail.tracking.value + loyalty promos."""

from datetime import date

import pytest
from logic.price_update_service import PriceUpdateService


def _make_row() -> dict:
    """One invoice line for get_bill_lines."""
    return {"product_id": [1, "Test"], "price_unit": 10000, "quantity": 1,
            "tax_ids": [], "price_subtotal": 10000}


def _init_seqs() -> list:
    """search_read results needed for PriceUpdateService.__init__().

    _init_tax_map queries account.tax.
    _init_price_field_id queries ir.model.fields.
    """
    return [[], [{"id": 3080}]]


def _analyze_seqs(with_tracking: bool) -> list:
    """search_read results for analyze_bill flow.

    Sequence (in analyze_bill order):
      0. get_bill_lines -> account.move.line: positive invoice lines
      1. product.product -> barcode + template_id
      2. product.template -> name + list_price + write_date
      3. loyalty.program -> active programs
      4. pricelist items -> fixed price rules
      5. mail.message -> change history for templates
      6. mail.tracking.value -> price_change timestamp (only if msg_ids exist)
      7. prev bill lines -> account.move.line with historical prices
    """
    result = [
        # 0. get_bill_lines
        [_make_row()],
        # 1. product.product
        [{"id": 1, "barcode": "TEST123", "product_tmpl_id": [10, "Tmpl"]}],
        # 2. product.template
        [{"id": 10, "name": "Test", "list_price": 15000,
          "write_date": "2026-06-26 03:00:00"}],
        # 3. loyalty.program
        [],
        # 4. pricelist items
        [],
        # 5. mail.message
        [],
    ]
    if with_tracking:
        result[5] = [{"id": 1, "res_id": 10, "model": "product.template",
                      "date": "2026-06-25 14:30:00"}]
        result.append(
            # 6. mail.tracking.value
            [{"create_date": "2026-06-25 14:30:00", "mail_message_id": [1, "msg"]}]
        )
    else:
        result[5] = []
    # last: prev bill lines
    result.append(
        [{"product_id": [1, "Test"], "price_unit": 9000, "tax_ids": [],
          "price_subtotal": 9000, "move_id": [999, "B-999"]}]
    )
    return result


@pytest.fixture
def service_with_mock(mocker):
    """PriceUpdateService with search_read mocked through init + method.

    All init search_read calls return empty. The caller appends their
    own select_side_effect for the specific test.
    """
    service = PriceUpdateService()
    mock = mocker.patch.object(service.conn, 'search_read')
    mock.side_effect = _init_seqs()
    return service, mock


def test_analyze_bill_uses_price_tracking(service_with_mock):
    """Test analyze_bill uses mail.tracking.value date over write_date."""
    service, mock = service_with_mock
    mock.side_effect = _analyze_seqs(with_tracking=True)
    result = service.analyze_bill(bill_id=100)
    assert len(result) > 0
    assert result[0]["price_last_updated"] == "2026-06-25 14:30:00"


def test_analyze_bill_returns_none_when_no_tracking_data(service_with_mock):
    """Test price_last_updated is None when no tracking data (no write_date fallback)."""
    service, mock = service_with_mock
    mock.side_effect = _analyze_seqs(with_tracking=False)
    result = service.analyze_bill(bill_id=100)
    assert len(result) > 0
    assert result[0]["price_last_updated"] is None


def test_loyalty_promo_detected(service_with_mock):
    """Test loyalty program promo detected on matching variant."""
    service, mock = service_with_mock
    seq = _analyze_seqs(with_tracking=False)
    # loyalty.program = index 3 in analyze_seqs
    seq[3] = [{"id": 100, "name": "B1G1 Test", "date_from": "2026-06-01",
               "date_to": "2026-06-30", "trigger_product_ids": [1]}]
    mock.side_effect = seq
    result = service.analyze_bill(bill_id=100)
    assert len(result) > 0
    assert result[0]["has_promo"] is True


def test_no_promo_with_no_loyalty(service_with_mock):
    """Test has_promo=False when no loyalty program matches."""
    service, mock = service_with_mock
    mock.side_effect = _analyze_seqs(with_tracking=False)
    result = service.analyze_bill(bill_id=100)
    assert len(result) > 0
    assert result[0]["has_promo"] is False
