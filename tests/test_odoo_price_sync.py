"""Tests for OdooPriceSyncService.detect_changes_since()."""

import pytest
from datetime import date, datetime
from logic.odoo_price_sync import OdooPriceSyncService, PriceChange, SyncResult


@pytest.fixture
def service(tmp_path):
    """Service that uses temp dir for local db path."""
    return OdooPriceSyncService()


def test_detect_changes_since_increase(service, mocker):
    """Mail tracking has old_value=3500, current list_price=3800 → increase."""
    mock_conn = mocker.patch.object(service, "conn_mgr")

    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # 1. ir.model.fields product.product.list_price
        [{"id": 456}],  # 2. ir.model.fields product.template.list_price
        [                # 3. mail.tracking.value (with old_value_float!)
            {"create_date": "2026-06-28 10:00:00", "mail_message_id": [100],
             "new_value_float": 3800.0, "old_value_float": 3500.0},
        ],
        [                # 4. mail.message
            {"id": 100, "res_id": 1, "model": "product.product"},
        ],
        [                # 5. product.product by id
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3800.0, "product_tmpl_id": [10]},
        ],
        [                # 6. all products (for "new" detection)
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3800.0, "product_tmpl_id": [10]},
        ],
    ]

    result = service.detect_changes_since(start_date=date(2026, 6, 1))

    inc = [c for c in result.changes if c.change_type == "increase"]
    assert len(inc) == 1
    assert inc[0].barcode == "8991001010049"
    assert inc[0].old_price == 3500.0  # from tracking, not parquet!
    assert inc[0].new_price == 3800.0
    assert inc[0].changed_at == "2026-06-28 10:00:00"


def test_detect_changes_since_decrease(service, mocker):
    """old_value_float > current → decrease."""
    mock_conn = mocker.patch.object(service, "conn_mgr")

    mock_conn.search_read.side_effect = [
        [{"id": 123}],
        [{"id": 456}],
        [                # tracking with old higher than current
            {"create_date": "2026-06-28 10:00:00", "mail_message_id": [100],
             "new_value_float": 3200.0, "old_value_float": 3800.0},
        ],
        [{"id": 100, "res_id": 1, "model": "product.product"}],
        [
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3200.0, "product_tmpl_id": [10]},
        ],
        [
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3200.0, "product_tmpl_id": [10]},
        ],
    ]

    result = service.detect_changes_since(start_date=date(2026, 6, 1))

    dec = [c for c in result.changes if c.change_type == "decrease"]
    assert len(dec) == 1
    assert dec[0].old_price == 3800.0
    assert dec[0].new_price == 3200.0


def test_detect_changes_since_new_product(service, mocker):
    """Product in Odoo but not in parquet → 'new'."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    import pandas as pd
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=True)
    empty_df = pd.DataFrame(columns=["barcode", "het", "diskon"])
    mocker.patch("logic.odoo_price_sync.pd.read_parquet", return_value=empty_df)

    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # 1. ir.model.fields product.product.list_price
        [{"id": 456}],  # 2. ir.model.fields product.template.list_price
        [],              # 3. mail.tracking.value — empty
        [                # 4. _detect_new_products_since: create_date query
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3500.0, "product_tmpl_id": [10]},
        ],
    ]

    result = service.detect_changes_since(start_date=date(2026, 6, 1))

    new = [c for c in result.changes if c.change_type == "new"]
    assert len(new) == 1
    assert new[0].barcode == "8991001010049"


def test_detect_changes_since_no_parquet(service, mocker):
    """No parquet file → all Odoo products are 'new'."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=False)

    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # 1. ir.model.fields product.product.list_price
        [{"id": 456}],  # 2. ir.model.fields product.template.list_price
        [],              # 3. mail.tracking.value — empty
        [                # 4. _detect_new_products_since: create_date query
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3500.0, "product_tmpl_id": [10]},
        ],
    ]

    result = service.detect_changes_since(start_date=date(2026, 6, 1))

    assert len(result.changes) == 1
    assert result.changes[0].change_type == "new"


def test_detect_changes_since_empty_range(service, mocker):
    """No products changed in range → empty result."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=True)
    import pandas as pd
    empty_df = pd.DataFrame(columns=["barcode", "het", "diskon"])
    mocker.patch("logic.odoo_price_sync.pd.read_parquet", return_value=empty_df)

    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # 1. ir.model.fields product.product
        [{"id": 456}],  # 2. ir.model.fields product.template
        [],              # 3. mail.tracking empty
        [],              # 4. _detect_new_products_since — empty
    ]

    result = service.detect_changes_since(start_date=date(2026, 6, 1))

    assert len(result.changes) == 0


def test_detect_changes_since_new_via_create_date(service, mocker):
    """Product created in range, not in parquet → detected as 'new'."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=True)
    import pandas as pd
    empty_df = pd.DataFrame(columns=["barcode", "het", "diskon"])
    mocker.patch("logic.odoo_price_sync.pd.read_parquet", return_value=empty_df)

    mock_conn.search_read.side_effect = [
        [{"id": 123}],          # 1. ir.model.fields product.product
        [{"id": 456}],          # 2. ir.model.fields product.template
        [],                      # 3. mail.tracking — empty
        [                        # 4. _detect_new_products_since hits
            {"id": 99, "barcode": "8889990001111", "name": "New Product",
             "list_price": 5000.0, "product_tmpl_id": [50]},
        ],
    ]

    result = service.detect_changes_since(start_date=date(2026, 6, 1))

    new = [c for c in result.changes if c.change_type == "new"]
    assert len(new) == 1
    assert new[0].barcode == "8889990001111"
    assert new[0].new_price == 5000.0
    assert new[0].old_price is None
