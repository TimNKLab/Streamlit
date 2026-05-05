"""Bridge between Python and browser IndexedDB via Streamlit component.

NOTE: This uses a simplified session_state-based communication pattern.
For production use with heavy workloads, consider building a proper
Streamlit custom component with bi-directional communication.
"""

import json
import time
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional

import streamlit as st
from streamlit.components.v1 import html


class IndexedDBBridge:
    """Python interface to browser IndexedDB for price sync data.
    
    This class provides a synchronous-like interface to the IndexedDB
    running in the browser, using Streamlit's session state as a
    communication bridge.
    """
    
    def __init__(self, component_path: Optional[str] = None, storage_dir: Optional[str] = None):
        if component_path is None:
            # Default to components folder
            root = Path(__file__).parent.parent
            component_path = str(root / "components" / "indexeddb_manager.html")
        
        self.component_path = component_path
        self._component_html = open(component_path).read()
        self._component_key = "indexeddb_manager"

        root = Path(__file__).parent.parent
        if storage_dir is None:
            session_dir = root / "session_data"
        else:
            session_dir = Path(storage_dir)
        session_dir.mkdir(exist_ok=True)
        self._products_path = session_dir / "price_sync_products.json"
        self._history_path = session_dir / "price_sync_history.json"

    def _read_json_file(self, path: Path) -> Any:
        try:
            if not path.exists():
                return None
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def _write_json_file(self, path: Path, payload: Any) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    
    def _render_component(self, height: int = 0) -> None:
        """Render the IndexedDB component (invisible if height=0)."""
        html(self._component_html, height=height)
    
    def get_all_products(self) -> List[Dict[str, Any]]:
        """Get all products from IndexedDB.
        
        NOTE: In the simplified implementation, this reads from
        session state. The component must be rendered first.
        """
        self._render_component(height=0)

        payload = self._read_json_file(self._products_path)
        if not payload:
            return []
        if isinstance(payload, dict):
            items = payload.get("products", [])
        else:
            items = payload
        return items if isinstance(items, list) else []
    
    def get_product(self, barcode: str) -> Optional[Dict[str, Any]]:
        """Get a single product by barcode."""
        products = self.get_all_products()
        for p in products:
            if p.get("barcode") == barcode:
                return p
        return None
    
    def upsert_products(self, products: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Upsert products to IndexedDB.
        
        In the simplified implementation, this stores in session state
        and the JavaScript component reads from there.
        """
        self._render_component(height=0)

        existing: Dict[str, Dict[str, Any]] = {}
        for p in self.get_all_products():
            bc = p.get("barcode")
            if bc:
                existing[str(bc)] = p

        for p in products:
            bc = p.get("barcode")
            if bc:
                existing[str(bc)] = p

        self._write_json_file(self._products_path, {"products": list(existing.values())})
        return {"success": True, "count": len(products)}
    
    def get_product_count(self) -> int:
        """Get count of products in IndexedDB."""
        return len(self.get_all_products())
    
    def clear_all(self) -> Dict[str, Any]:
        """Clear all products from IndexedDB."""
        self._render_component(height=0)

        self._write_json_file(self._products_path, {"products": []})
        return {"success": True}
    
    def add_sync_history(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Add a sync history record."""
        self._render_component(height=0)

        history = self._read_json_file(self._history_path)
        if not isinstance(history, list):
            history = []

        history.append(record)
        if len(history) > 50:
            history = history[-50:]

        self._write_json_file(self._history_path, history)
        return {"success": True}
    
    def get_sync_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent sync history."""
        self._render_component(height=0)

        history = self._read_json_file(self._history_path)
        if not isinstance(history, list):
            return []
        return history[-limit:][::-1]
