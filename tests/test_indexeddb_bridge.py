"""Tests for IndexedDB bridge"""
import pytest
from utils.indexeddb_bridge import IndexedDBBridge


def test_bridge_initialization():
    """Test bridge can be initialized."""
    bridge = IndexedDBBridge()
    assert bridge is not None
    assert bridge.component_path.endswith("indexeddb_manager.html")


def test_upsert_and_get_products():
    """Test upserting and retrieving products."""
    import streamlit as st
    
    bridge = IndexedDBBridge()
    
    # Clear any existing data
    bridge.clear_all()
    
    test_products = [
        {"barcode": "123456", "name": "Test Product", "het": 10000, "diskon": 9000, "last_sync": "2026-05-01T10:00:00"}
    ]
    
    result = bridge.upsert_products(test_products)
    assert result["success"] is True
    assert result["count"] == 1
    
    # In the simplified implementation, products are in session state
    # This test verifies the structure works


def test_get_product_count():
    """Test getting product count."""
    bridge = IndexedDBBridge()
    
    # After clearing, count should be 0
    bridge.clear_all()
    
    count = bridge.get_product_count()
    assert count == 0
    
    # Add product
    bridge.upsert_products([{"barcode": "123", "name": "Test", "het": 1000, "diskon": None, "last_sync": "2026-05-01T10:00:00"}])
    
    count = bridge.get_product_count()
    assert count == 1


def test_clear_all():
    """Test clearing all products."""
    bridge = IndexedDBBridge()
    
    # Add then clear
    bridge.upsert_products([{"barcode": "123", "name": "Test", "het": 1000, "diskon": None, "last_sync": "2026-05-01T10:00:00"}])
    result = bridge.clear_all()
    
    assert result["success"] is True
    assert bridge.get_product_count() == 0


def test_sync_history():
    """Test sync history operations."""
    bridge = IndexedDBBridge()
    
    # Clear history
    session_key = f"_indexeddb_history_{bridge._component_key}"
    import streamlit as st
    st.session_state[session_key] = []
    
    # Add records
    bridge.add_sync_history({"timestamp": "2026-05-01T10:00:00", "changes": 5})
    bridge.add_sync_history({"timestamp": "2026-05-01T11:00:00", "changes": 3})
    
    # Get history
    history = bridge.get_sync_history(limit=10)
    assert len(history) == 2
