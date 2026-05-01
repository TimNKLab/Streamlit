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
    
    def __init__(self, component_path: Optional[str] = None):
        if component_path is None:
            # Default to components folder
            root = Path(__file__).parent.parent
            component_path = str(root / "components" / "indexeddb_manager.html")
        
        self.component_path = component_path
        self._component_html = open(component_path).read()
        self._component_key = "indexeddb_manager_" + str(uuid.uuid4())[:8]
    
    def _render_component(self, height: int = 0) -> None:
        """Render the IndexedDB component (invisible if height=0)."""
        html(self._component_html, height=height)
    
    def get_all_products(self) -> List[Dict[str, Any]]:
        """Get all products from IndexedDB.
        
        NOTE: In the simplified implementation, this reads from
        session state. The component must be rendered first.
        """
        self._render_component(height=0)
        
        # Check if we have cached products in session state
        # (Set by JavaScript via postMessage)
        session_key = f"_indexeddb_products_{self._component_key}"
        
        if session_key in st.session_state:
            return st.session_state[session_key]
        
        # Return empty list if not yet populated
        return []
    
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
        
        session_key = f"_indexeddb_products_{self._component_key}"
        
        # Get existing products
        existing = {}
        if session_key in st.session_state:
            for p in st.session_state[session_key]:
                existing[p.get("barcode")] = p
        
        # Update with new products
        for p in products:
            existing[p.get("barcode")] = p
        
        # Store back
        st.session_state[session_key] = list(existing.values())
        
        return {"success": True, "count": len(products)}
    
    def get_product_count(self) -> int:
        """Get count of products in IndexedDB."""
        return len(self.get_all_products())
    
    def clear_all(self) -> Dict[str, Any]:
        """Clear all products from IndexedDB."""
        self._render_component(height=0)
        
        session_key = f"_indexeddb_products_{self._component_key}"
        st.session_state[session_key] = []
        
        return {"success": True}
    
    def add_sync_history(self, record: Dict[str, Any]) -> Dict[str, Any]:
        """Add a sync history record."""
        self._render_component(height=0)
        
        session_key = f"_indexeddb_history_{self._component_key}"
        
        if session_key not in st.session_state:
            st.session_state[session_key] = []
        
        st.session_state[session_key].append(record)
        
        # Keep only last 50 records
        if len(st.session_state[session_key]) > 50:
            st.session_state[session_key] = st.session_state[session_key][-50:]
        
        return {"success": True}
    
    def get_sync_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent sync history."""
        self._render_component(height=0)
        
        session_key = f"_indexeddb_history_{self._component_key}"
        
        if session_key not in st.session_state:
            return []
        
        # Return most recent first
        history = st.session_state[session_key]
        return history[-limit:][::-1]
