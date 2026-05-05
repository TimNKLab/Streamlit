"""Tests for IndexedDB bridge"""
import pytest
from utils.indexeddb_bridge import IndexedDBBridge


def test_bridge_initialization():
    """Test bridge can be initialized."""
    bridge = IndexedDBBridge()
    assert bridge is not None
    assert bridge.component_path.endswith("indexeddb_manager.html")


def test_upsert_and_get_products(tmp_path):
    """Test upserting and retrieving products."""
    bridge = IndexedDBBridge(storage_dir=str(tmp_path))
    
    # Clear any existing data
    bridge.clear_all()
    
    test_products = [
        {"barcode": "123456", "name": "Test Product", "het": 10000, "diskon": 9000, "last_sync": "2026-05-01T10:00:00"}
    ]
    
    result = bridge.upsert_products(test_products)
    assert result["success"] is True
    assert result["count"] == 1
    
    products = bridge.get_all_products()
    assert len(products) == 1
    assert products[0]["barcode"] == "123456"


def test_get_product_count(tmp_path):
    """Test getting product count."""
    bridge = IndexedDBBridge(storage_dir=str(tmp_path))
    
    # After clearing, count should be 0
    bridge.clear_all()
    
    count = bridge.get_product_count()
    assert count == 0
    
    # Add product
    bridge.upsert_products([{"barcode": "123", "name": "Test", "het": 1000, "diskon": None, "last_sync": "2026-05-01T10:00:00"}])
    
    count = bridge.get_product_count()
    assert count == 1


def test_clear_all(tmp_path):
    """Test clearing all products."""
    bridge = IndexedDBBridge(storage_dir=str(tmp_path))
    
    # Add then clear
    bridge.upsert_products([{"barcode": "123", "name": "Test", "het": 1000, "diskon": None, "last_sync": "2026-05-01T10:00:00"}])
    result = bridge.clear_all()
    
    assert result["success"] is True
    assert bridge.get_product_count() == 0


def test_sync_history(tmp_path):
    """Test sync history operations."""
    bridge = IndexedDBBridge(storage_dir=str(tmp_path))
    
    # Clear history by overwriting file
    bridge._write_json_file(bridge._history_path, [])
    
    # Add records
    bridge.add_sync_history({"timestamp": "2026-05-01T10:00:00", "changes": 5})
    bridge.add_sync_history({"timestamp": "2026-05-01T11:00:00", "changes": 3})
    
    # Get history
    history = bridge.get_sync_history(limit=10)
    assert len(history) == 2
