"""Browser localStorage persistence for session data."""

import json
from datetime import datetime
from typing import Optional, List, Dict, Any
import streamlit as st

# Lazy import to avoid initialization errors
def _get_localstorage():
    from streamlit_ws_localstorage import injectWebsocketCode
    conn = injectWebsocketCode(
        key="localstorage_persistence",
        sockjs_server="ws://localhost:8888",
        origin="http://localhost:8888"
    )
    return conn

# Storage key for price tag data
PRICE_TAG_STORAGE_KEY = "nk_lab_price_tag_session"

def save_session(items: List[Dict[str, Any]]) -> bool:
    """
    Save price tag items to browser localStorage.
    
    Args:
        items: List of item dictionaries with barcode, name, het, diskon
        
    Returns:
        True if saved successfully, False otherwise
    """
    try:
        # Filter out internal fields before saving
        clean_items = []
        for item in items:
            clean_item = {
                'barcode': item.get('barcode', ''),
                'name': item.get('name', ''),
                'het': item.get('het', ''),
                'diskon': item.get('diskon', ''),
                'status': item.get('status', ''),
                'in_system': item.get('in_system', False)
            }
            # Only save items with barcode
            if clean_item['barcode'].strip():
                clean_items.append(clean_item)
        
        # Prepare payload with timestamp
        payload = {
            'items': clean_items,
            'saved_at': datetime.now().isoformat(),
            'version': 1
        }
        
        # Save to localStorage
        conn = _get_localstorage()
        result = conn.setLocalStorageVal(key=PRICE_TAG_STORAGE_KEY, val=json.dumps(payload))
        
        return result is not None
        
    except Exception as e:
        # Silently fail - persistence is best-effort
        print(f"[PERSISTENCE] Save failed: {e}")
        return False

def restore_session() -> Optional[List[Dict[str, Any]]]:
    """
    Restore price tag items from browser localStorage.
    
    Returns:
        List of items if found and valid, None otherwise
    """
    try:
        conn = _get_localstorage()
        data = conn.getLocalStorageVal(key=PRICE_TAG_STORAGE_KEY)
        
        if not data:
            return None
            
        # Parse stored data
        payload = json.loads(data)
        
        # Validate version and data structure
        if not isinstance(payload, dict):
            return None
            
        if payload.get('version') != 1:
            return None
            
        items = payload.get('items', [])
        if not isinstance(items, list):
            return None
            
        # Restore saved timestamp for debugging
        saved_at = payload.get('saved_at', 'unknown')
        print(f"[PERSISTENCE] Restored {len(items)} items from {saved_at}")
        
        return items
        
    except json.JSONDecodeError:
        print("[PERSISTENCE] Invalid JSON in stored data")
        return None
    except Exception as e:
        print(f"[PERSISTENCE] Restore failed: {e}")
        return None

def clear_session() -> bool:
    """
    Clear persisted session data from localStorage.
    
    Returns:
        True if cleared successfully, False otherwise
    """
    try:
        conn = _get_localstorage()
        conn.delLocalStorageVal(key=PRICE_TAG_STORAGE_KEY)
        print("[PERSISTENCE] Session cleared from localStorage")
        return True
        
    except Exception as e:
        print(f"[PERSISTENCE] Clear failed: {e}")
        return False

def has_saved_session() -> bool:
    """
    Check if there's a saved session in localStorage.
    
    Returns:
        True if saved session exists, False otherwise
    """
    try:
        conn = _get_localstorage()
        data = conn.getLocalStorageVal(key=PRICE_TAG_STORAGE_KEY)
        return data is not None and data != ""
        
    except Exception:
        return False


# Storage key for active tab
ACTIVE_TAB_KEY = "nk_lab_active_tab"
TAB_NAMES = ["dashboard", "ba_sales", "stock_control", "dsi_report", "stock_card", "price_tag"]

def save_active_tab(tab_name: str) -> bool:
    """Save current active tab to localStorage."""
    try:
        conn = _get_localstorage()
        conn.setLocalStorageVal(key=ACTIVE_TAB_KEY, val=tab_name)
        return True
    except Exception as e:
        print(f"[PERSISTENCE] Save tab failed: {e}")
        return False

def restore_active_tab() -> str:
    """Restore active tab from localStorage. Returns tab name or 'dashboard' as default."""
    try:
        conn = _get_localstorage()
        tab_name = conn.getLocalStorageVal(key=ACTIVE_TAB_KEY)
        if tab_name and tab_name in TAB_NAMES:
            return tab_name
        return "dashboard"
    except Exception as e:
        print(f"[PERSISTENCE] Restore tab failed: {e}")
        return "dashboard"

def has_saved_barcodes() -> bool:
    """Check if price tag has saved barcodes - use to prioritize price_tag tab."""
    try:
        conn = _get_localstorage()
        data = conn.getLocalStorageVal(key=PRICE_TAG_STORAGE_KEY)
        if not data:
            return False
        payload = json.loads(data)
        items = payload.get('items', [])
        return len(items) > 0
    except Exception:
        return False
