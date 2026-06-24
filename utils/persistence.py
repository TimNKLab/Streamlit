"""Server-side file persistence for session data (reliable alternative to localStorage)."""

import json
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
import streamlit as st
from pathlib import Path

# Project root for file storage
PROJECT_ROOT = Path(__file__).parent.parent
SESSION_DIR = PROJECT_ROOT / "session_data"

# Ensure session directory exists
SESSION_DIR.mkdir(exist_ok=True)

# Storage keys
PRICE_TAG_FILE = SESSION_DIR / "price_tag_session.json"
ACTIVE_TAB_FILE = SESSION_DIR / "active_tab.txt"
TAB_NAMES = ["dashboard", "ba_sales", "stock_control", "dsi_report", "stock_card", "price_tag", "update_harga"]

def _get_session_id() -> str:
    """Get a unique session identifier."""
    # Use a combination of session_id and a stored identifier
    if '_session_id' not in st.session_state:
        import uuid
        st.session_state._session_id = str(uuid.uuid4())[:8]
    return st.session_state._session_id

def _get_user_file(suffix: str = "") -> Path:
    """Get a user-specific file path."""
    # Use a generic file for now (single user mode)
    # Could be extended to per-user files based on auth
    if suffix:
        return SESSION_DIR / f"user_{suffix}.json"
    return PRICE_TAG_FILE

def save_session(items: List[Dict[str, Any]]) -> bool:
    """Save price tag items to server-side file."""
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
            if clean_item['barcode'].strip():
                clean_items.append(clean_item)
        
        payload = {
            'items': clean_items,
            'saved_at': datetime.now().isoformat(),
            'version': 1
        }
        
        # Write to file
        file_path = _get_user_file("price_tag")
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        
        print(f"[PERSISTENCE] Saved {len(clean_items)} items to {file_path}")
        return True
        
    except Exception as e:
        print(f"[PERSISTENCE] Save failed: {e}")
        return False

def restore_session() -> Optional[List[Dict[str, Any]]]:
    """Restore price tag items from server-side file."""
    try:
        file_path = _get_user_file("price_tag")
        
        if not file_path.exists():
            return None
            
        with open(file_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        
        # Validate version and data structure
        if not isinstance(payload, dict):
            return None
            
        if payload.get('version') != 1:
            return None
            
        items = payload.get('items', [])
        if not isinstance(items, list):
            return None
        
        # Add missing fields required by the UI
        from datetime import datetime
        for idx, item in enumerate(items):
            if 'key_prefix' not in item:
                item['key_prefix'] = f"row_{idx}_{datetime.now().strftime('%H%M%S%f')}"
            if '_last_lookup' not in item:
                item['_last_lookup'] = None
        
        saved_at = payload.get('saved_at', 'unknown')
        print(f"[PERSISTENCE] Restored {len(items)} items from {saved_at}")
        
        return items
        
    except json.JSONDecodeError:
        print("[PERSISTENCE] Invalid JSON in stored data")
        return None
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"[PERSISTENCE] Restore failed: {e}")
        return None

def clear_session() -> bool:
    """Clear persisted session data from server-side file."""
    try:
        file_path = _get_user_file("price_tag")
        if file_path.exists():
            file_path.unlink()
        print("[PERSISTENCE] Session cleared")
        return True
    except Exception as e:
        print(f"[PERSISTENCE] Clear failed: {e}")
        return False

def has_saved_session() -> bool:
    """Check if there's a saved session in server-side file."""
    try:
        file_path = _get_user_file("price_tag")
        return file_path.exists() and file_path.stat().st_size > 0
    except Exception:
        return False

def save_active_tab(tab_name: str) -> bool:
    """Save current active tab to server-side file."""
    try:
        file_path = _get_user_file("active_tab")
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(tab_name)
        return True
    except Exception as e:
        print(f"[PERSISTENCE] Save tab failed: {e}")
        return False

def restore_active_tab() -> str:
    """Restore active tab from server-side file. Returns tab name or 'dashboard' as default."""
    try:
        file_path = _get_user_file("active_tab")
        if not file_path.exists():
            return "dashboard"
            
        tab_name = file_path.read_text(encoding='utf-8').strip()
        if tab_name and tab_name in TAB_NAMES:
            return tab_name
        return "dashboard"
    except Exception as e:
        print(f"[PERSISTENCE] Restore tab failed: {e}")
        return "dashboard"

def has_saved_barcodes() -> bool:
    """Check if price tag has saved barcodes - use to prioritize price_tag tab."""
    try:
        file_path = _get_user_file("price_tag")
        if not file_path.exists():
            return False
            
        with open(file_path, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        items = payload.get('items', [])
        return len(items) > 0
    except Exception:
        return False
