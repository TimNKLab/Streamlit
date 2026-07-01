"""Tests for OdooPriceSyncService.detect_changes_since()."""

import pytest
from datetime import date, datetime
from logic.odoo_price_sync import OdooPriceSyncService, PriceChange, SyncResult


@pytest.fixture
def service(tmp_path):
    """Service that uses temp dir for local db path."""
    return OdooPriceSyncService()


def test_detect_changes_since_success(service, mocker):
    """Mock Odoo and parquet data, verify changes detected correctly."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=True)
    mock_parquet_df = mocker.patch("logic.odoo_price_sync.pd.read_parquet")

    # Build a fake parquet DataFrame with proper shape
    import pandas as pd
    fake_df = pd.DataFrame([
        {"barcode": "8991001010049", "het": 3500.0, "diskon": None},
    ])
    mock_parquet_df.return_value = fake_df

    # Mock field_id lookup
    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # 1. ir.model.fields
        [                # 2. mail.tracking.value
            {"create_date": "2026-06-28 10:00:00", "mail_message_id": [100],
             "new_value_float": 3800.0},
        ],
        [                # 3. mail.message
            {"id": 100, "res_id": 1, "model": "product.product"},
        ],
        [                # 4. product.product by id
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3800.0, "product_tmpl_id": [10]},
        ],
        [                # 5. all products (for "new" detection)
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3800.0, "product_tmpl_id": [10]},
        ],
    ]

    result = service.detect_changes_since(start_date=date(2026, 6, 1))

    assert isinstance(result, SyncResult)

    # Check at least one change detected (increase)
    inc = [c for c in result.changes if c.change_type == "increase"]
    assert len(inc) >= 1
    assert inc[0].barcode == "8991001010049"
    assert inc[0].old_price == 3500.0
    assert inc[0].new_price == 3800.0
    assert inc[0].changed_at == "2026-06-28 10:00:00"


def test_detect_changes_since_new_product(service, mocker):
    """Product in Odoo but not in parquet → 'new'."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=True)
    import pandas as pd
    empty_df = pd.DataFrame(columns=["barcode", "het", "diskon"])
    mocker.patch("logic.odoo_price_sync.pd.read_parquet", return_value=empty_df)

    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # field_id
        [],             # mail.tracking (empty)
        [],             # write_date fallback (empty)
        [               # all products
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3500.0, "product_tmpl_id": [10]},
        ],
    ]

    result = service.detect_changes_since(start_date=date(2026, 6, 1))

    assert len(result.changes) >= 1
    new = [c for c in result.changes if c.change_type == "new"]
    assert len(new) >= 1
    assert new[0].barcode == "8991001010049"


def test_detect_changes_since_no_parquet(service, mocker):
    """No parquet file (exists=False) → all Odoo products are 'new'."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=False)

    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # 1. field_id
        [],             # 2. mail.tracking (empty)
        [],             # 3. write_date fallback (empty)
        [                # 4. all products
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
        [{"id": 123}],  # field_id
        [],             # mail.tracking (empty)
        [],             # write_date fallback (empty)
        [],             # all products (empty — no qty > 0 in range)
    ]

    result = service.detect_changes_since(start_date=date(2026, 6, 1))

    assert len(result.changes) == 0


def test_detect_changes_since_write_date_fallback(service, mocker):
    """When mail.tracking returns empty, fallback to write_date."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=True)
    import pandas as pd
    empty_df = pd.DataFrame(columns=["barcode", "het", "diskon"])
    mocker.patch("logic.odoo_price_sync.pd.read_parquet", return_value=empty_df)

    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # field_id
        [],             # mail.tracking (empty)
        [                # write_date fallback
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3800.0, "product_tmpl_id": [10]},
        ],
    ]

    result = service.detect_changes_since(start_date=date(2026, 6, 1))

    assert len(result.changes) >= 1
