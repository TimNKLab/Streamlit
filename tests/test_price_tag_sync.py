"""Tests for PriceTagService.sync_from_odoo()."""

import pytest
import pandas as pd
import os
from logic.price_tag_service import PriceTagService


@pytest.fixture
def service(tmp_path):
    """Build a PriceTagService that writes parquet to tmp_path."""
    parquet_path = str(tmp_path / "products.parquet")
    svc = PriceTagService(
        auto_convert=False,
        use_memory_cache=False,
    )
    svc.parquet_path = parquet_path
    svc._products = {}
    svc._suffix_index = {}
    return svc


def test_sync_from_odoo_success(service, mocker):
    """Mock Odoo responses and verify parquet file is written."""
    mock_conn = mocker.patch("logic.price_tag_service.connection_manager")

    # First RPC: product.product
    product_a = {
        "id": 1, "barcode": "8991001010049", "name": "Indomie Goreng",
        "list_price": 3500.0, "product_tmpl_id": [10, "Template A"],
    }
    product_b = {
        "id": 2, "barcode": "8886388100017", "name": "Mie Sedaap",
        "list_price": 3200.0, "product_tmpl_id": [20, "Template B"],
    }
    mock_conn.search_read.side_effect = [
        [product_a, product_b],        # first call: product.product
        [                              # second call: product.pricelist.item
            {"product_tmpl_id": [10], "fixed_price": 2800.0},
        ],
    ]

    result = service.sync_from_odoo()

    assert result["success"] == 2
    assert result["skipped"] == 0
    assert os.path.exists(service.parquet_path)

    # Verify parquet content
    df = pd.read_parquet(service.parquet_path)
    assert len(df) == 2
    assert df.iloc[0]["barcode"] == "8991001010049"
    assert df.iloc[0]["het"] == 3500.0
    assert df.iloc[0]["diskon"] == 2800.0
    assert df.iloc[1]["barcode"] == "8886388100017"
    assert df.iloc[1]["het"] == 3200.0
    assert pd.isna(df.iloc[1]["diskon"])  # no pricelist item → null


def test_sync_from_odoo_memory_cache_reloaded(service, mocker):
    """After sync, in-memory cache should contain the new products."""
    mock_conn = mocker.patch("logic.price_tag_service.connection_manager")
    mock_conn.search_read.side_effect = [
        [
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3500.0, "product_tmpl_id": [10, "Tpl"]},
        ],
        [],  # no pricelist items
    ]

    service.sync_from_odoo()

    # _load_parquet_to_memory is called → products accessible via lookup
    prod = service.lookup_product("8991001010049")
    assert prod is not None
    assert prod["name"] == "Indomie"
    assert prod["het"] == 3500.0


def test_sync_from_odoo_skips_missing_barcode(service, mocker):
    """Products without barcode are counted as skipped."""
    mock_conn = mocker.patch("logic.price_tag_service.connection_manager")
    mock_conn.search_read.side_effect = [
        [
            {"id": 1, "barcode": "", "name": "No Barcode",
             "list_price": 1000.0, "product_tmpl_id": [10, "Tpl"]},
            {"id": 2, "barcode": "8991001010049", "name": "Valid Product",
             "list_price": 3500.0, "product_tmpl_id": [20, "Tpl"]},
        ],
        [],
    ]

    result = service.sync_from_odoo()
    assert result["success"] == 1
    assert result["skipped"] == 1


def test_sync_from_odoo_empty_stock(service, mocker):
    """No products with qty > 0 → empty parquet, success=0."""
    mock_conn = mocker.patch("logic.price_tag_service.connection_manager")
    mock_conn.search_read.side_effect = [[], []]

    result = service.sync_from_odoo()

    assert result["success"] == 0
    assert result["skipped"] == 0
    assert os.path.exists(service.parquet_path)
    df = pd.read_parquet(service.parquet_path)
    assert len(df) == 0


def test_sync_from_odoo_connection_error(service, mocker):
    """Odoo connection failure → exception raised to caller."""
    from odoo.connection import OdooIntegrationError
    mock_conn = mocker.patch("logic.price_tag_service.connection_manager")
    mock_conn.search_read.side_effect = OdooIntegrationError("Odoo down")

    with pytest.raises(OdooIntegrationError):
        service.sync_from_odoo()
