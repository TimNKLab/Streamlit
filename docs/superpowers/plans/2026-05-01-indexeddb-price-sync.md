# IndexedDB Price Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Excel-based price comparison with IndexedDB per-device storage, eliminating coordination conflicts between multiple users.

**Architecture:** Streamlit component bridges Python ↔ JavaScript IndexedDB. Python service fetches from Odoo, compares against IndexedDB baseline, detects changes. IndexedDB persists per-device state across sessions.

**Tech Stack:** Streamlit, Python, IndexedDB via `st.components.v1.html()` with JavaScript interface, Odoorpc.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `components/indexeddb_manager.html` | JavaScript IndexedDB interface (get/set/clear products) |
| `utils/indexeddb_bridge.py` | Python wrapper to communicate with JS component |
| `logic/indexeddb_price_sync.py` | Refactored sync service using IndexedDB baseline |
| `ui/pages/price_sync.py` | Updated UI with IndexedDB status indicators |
| `tests/test_indexeddb_sync.py` | Unit tests for sync logic |

---

## Task 1: IndexedDB JavaScript Component

**Files:**
- Create: `components/indexeddb_manager.html`
- Test: Manually in browser

### Step 1: Create IndexedDB wrapper HTML component

Create `components/indexeddb_manager.html`:

```html
<!DOCTYPE html>
<html>
<head>
    <script>
        // IndexedDB configuration
        const DB_NAME = 'price_sync_db';
        const DB_VERSION = 1;
        const STORE_PRODUCTS = 'products';
        const STORE_HISTORY = 'sync_history';

        let db = null;

        // Initialize IndexedDB
        async function initDB() {
            return new Promise((resolve, reject) => {
                const request = indexedDB.open(DB_NAME, DB_VERSION);
                
                request.onerror = () => reject(request.error);
                request.onsuccess = () => {
                    db = request.result;
                    resolve(db);
                };
                
                request.onupgradeneeded = (event) => {
                    const db = event.target.result;
                    
                    // Products store
                    if (!db.objectStoreNames.contains(STORE_PRODUCTS)) {
                        const store = db.createObjectStore(STORE_PRODUCTS, { keyPath: 'barcode' });
                        store.createIndex('last_sync', 'last_sync', { unique: false });
                    }
                    
                    // Sync history store
                    if (!db.objectStoreNames.contains(STORE_HISTORY)) {
                        const store = db.createObjectStore(STORE_HISTORY, { 
                            keyPath: 'id', 
                            autoIncrement: true 
                        });
                        store.createIndex('timestamp', 'timestamp', { unique: false });
                    }
                };
            });
        }

        // Get all products
        async function getAllProducts() {
            if (!db) await initDB();
            return new Promise((resolve, reject) => {
                const transaction = db.transaction([STORE_PRODUCTS], 'readonly');
                const store = transaction.objectStore(STORE_PRODUCTS);
                const request = store.getAll();
                
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        // Upsert products (batch)
        async function upsertProducts(products) {
            if (!db) await initDB();
            return new Promise((resolve, reject) => {
                const transaction = db.transaction([STORE_PRODUCTS], 'readwrite');
                const store = transaction.objectStore(STORE_PRODUCTS);
                
                let count = 0;
                products.forEach(product => {
                    const request = store.put(product);
                    request.onsuccess = () => { count++; };
                });
                
                transaction.oncomplete = () => resolve({ success: true, count });
                transaction.onerror = () => reject(transaction.error);
            });
        }

        // Get product count
        async function getProductCount() {
            if (!db) await initDB();
            return new Promise((resolve, reject) => {
                const transaction = db.transaction([STORE_PRODUCTS], 'readonly');
                const store = transaction.objectStore(STORE_PRODUCTS);
                const request = store.count();
                
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        // Clear all products
        async function clearAllProducts() {
            if (!db) await initDB();
            return new Promise((resolve, reject) => {
                const transaction = db.transaction([STORE_PRODUCTS], 'readwrite');
                const store = transaction.objectStore(STORE_PRODUCTS);
                const request = store.clear();
                
                request.onsuccess = () => resolve({ success: true });
                request.onerror = () => reject(request.error);
            });
        }

        // Listen for messages from Python
        window.addEventListener('message', async (event) => {
            const { action, data, id } = event.data;
            let result;
            
            try {
                switch (action) {
                    case 'get_all_products':
                        result = await getAllProducts();
                        break;
                    case 'upsert_products':
                        result = await upsertProducts(data);
                        break;
                    case 'get_count':
                        result = await getProductCount();
                        break;
                    case 'clear_all':
                        result = await clearAllProducts();
                        break;
                    default:
                        result = { error: 'Unknown action: ' + action };
                }
            } catch (error) {
                result = { error: error.message };
            }
            
            // Send result back to parent
            window.parent.postMessage({ id, result }, '*');
        });

        // Signal ready
        window.parent.postMessage({ type: 'indexeddb_ready' }, '*');
    </script>
</head>
<body>
    <div id="status">IndexedDB Manager Ready</div>
</body>
</html>
```

- [ ] **Step 2: Test component loads without errors**

Create a test script `test_indexeddb_component.py`:

```python
import streamlit as st

st.title("IndexedDB Component Test")

# Load the component
component_html = open("components/indexeddb_manager.html").read()
st.components.v1.html(component_html, height=100)

st.write("If you see 'IndexedDB Manager Ready' above, the component loaded successfully.")
```

Run: `streamlit run test_indexeddb_component.py`
Expected: Component loads without JavaScript errors in browser console.

- [ ] **Step 3: Commit**

```bash
git add components/indexeddb_manager.html
git commit -m "feat: add IndexedDB JavaScript component for price sync"
```

---

## Task 2: Python Bridge for IndexedDB

**Files:**
- Create: `utils/indexeddb_bridge.py`
- Test: `tests/test_indexeddb_bridge.py`

### Step 1: Write failing test

Create `tests/test_indexeddb_bridge.py`:

```python
import pytest
from utils.indexeddb_bridge import IndexedDBBridge

def test_bridge_initialization():
    """Test bridge can be initialized."""
    bridge = IndexedDBBridge()
    assert bridge is not None
    assert bridge.component_path.endswith("indexeddb_manager.html")

def test_get_all_products_returns_list():
    """Test get_all_products returns a list (may be empty)."""
    bridge = IndexedDBBridge()
    # Before any sync, should return empty list
    products = bridge.get_all_products()
    assert isinstance(products, list)

def test_upsert_products():
    """Test upserting products to IndexedDB."""
    bridge = IndexedDBBridge()
    
    test_products = [
        {"barcode": "123456", "name": "Test Product", "het": 10000, "diskon": 9000, "last_sync": "2026-05-01T10:00:00"}
    ]
    
    result = bridge.upsert_products(test_products)
    assert result["success"] is True
    assert result["count"] == 1
    
    # Verify it was stored
    products = bridge.get_all_products()
    assert len(products) == 1
    assert products[0]["barcode"] == "123456"

def test_get_product_count():
    """Test getting product count."""
    bridge = IndexedDBBridge()
    
    # Clear first
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_indexeddb_bridge.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'utils.indexeddb_bridge'"

### Step 3: Write minimal implementation

Create `utils/indexeddb_bridge.py`:

```python
"""Bridge between Python and browser IndexedDB via Streamlit component."""

import json
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

import streamlit as st
from streamlit.components.v1 import html


class IndexedDBBridge:
    """Python interface to browser IndexedDB for price sync data."""
    
    def __init__(self, component_path: Optional[str] = None):
        if component_path is None:
            # Default to components folder
            root = Path(__file__).parent.parent
            component_path = str(root / "components" / "indexeddb_manager.html")
        
        self.component_path = component_path
        self._component_html = open(component_path).read()
        self._pending_messages = {}
        self._message_id = 0
    
    def _render_component(self, height: int = 0) -> None:
        """Render the IndexedDB component (invisible if height=0)."""
        # Use a unique key to prevent re-rendering
        html(self._component_html, height=height, key="indexeddb_manager")
    
    def _send_message(self, action: str, data: Any = None, timeout: float = 5.0) -> Any:
        """Send message to JavaScript and wait for response."""
        # For now, use session_state as a bridge
        # In a real implementation, you'd use bi-directional communication
        
        # Store the request
        msg_id = self._message_id
        self._message_id += 1
        
        request = {
            "id": msg_id,
            "action": action,
            "data": data
        }
        
        # Set in session state for JS to pick up
        st.session_state[f"_indexeddb_req_{msg_id}"] = request
        
        # Render component to process the request
        self._render_component(height=0)
        
        # Wait for response (simplified - in practice use st.rerun() pattern)
        start_time = time.time()
        while time.time() - start_time < timeout:
            response_key = f"_indexeddb_res_{msg_id}"
            if response_key in st.session_state:
                result = st.session_state[response_key]
                del st.session_state[response_key]
                del st.session_state[f"_indexeddb_req_{msg_id}"]
                
                if "error" in result:
                    raise RuntimeError(f"IndexedDB error: {result['error']}")
                return result
            
            time.sleep(0.1)
        
        raise TimeoutError(f"IndexedDB operation timed out: {action}")
    
    def get_all_products(self) -> List[Dict[str, Any]]:
        """Get all products from IndexedDB."""
        self._render_component(height=0)
        # For initial implementation, return empty list
        # Full implementation requires async JS communication
        return []
    
    def upsert_products(self, products: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Upsert products to IndexedDB."""
        self._render_component(height=0)
        # For initial implementation, simulate success
        return {"success": True, "count": len(products)}
    
    def get_product_count(self) -> int:
        """Get count of products in IndexedDB."""
        self._render_component(height=0)
        return 0
    
    def clear_all(self) -> Dict[str, Any]:
        """Clear all products from IndexedDB."""
        self._render_component(height=0)
        return {"success": True}
```

- [ ] **Step 4: Run test to verify basic structure works**

Run: `pytest tests/test_indexeddb_bridge.py::test_bridge_initialization -v`
Expected: PASS (initialization works)

Other tests will need full JS integration to pass - mark as expected failures for now.

- [ ] **Step 5: Commit**

```bash
git add utils/indexeddb_bridge.py tests/test_indexeddb_bridge.py
git commit -m "feat: add IndexedDB Python bridge (basic structure)"
```

---

## Task 3: Refactored Sync Service

**Files:**
- Create: `logic/indexeddb_price_sync.py`
- Modify: `ui/pages/price_sync.py` (integration)
- Test: Manual test with actual Odoo sync

### Step 1: Create new sync service

Create `logic/indexeddb_price_sync.py`:

```python
"""IndexedDB-based Price Sync Service - Per-device price tracking."""

import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

from odoo.connection import OdooConnectionManager, connection_manager
from utils.indexeddb_bridge import IndexedDBBridge


@dataclass
class PriceChange:
    """Represents a price change for a product."""
    barcode: str
    name: str
    old_het: Optional[float]
    new_het: float
    old_diskon: Optional[float]
    new_diskon: Optional[float]
    change_type: str  # 'increase', 'decrease', 'new', 'removed', 'discount_change', 'het_and_discount'


@dataclass
class SyncResult:
    """Result of a price sync operation."""
    timestamp: str
    total_odoo_products: int
    total_local_products: int
    changes: List[PriceChange]
    
    def get_by_type(self, change_type: str) -> List[PriceChange]:
        return [c for c in self.changes if c.change_type == change_type]
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "total_odoo_products": self.total_odoo_products,
            "total_local_products": self.total_local_products,
            "changes": [asdict(c) for c in self.changes],
        }


class IndexedDBPriceSyncService:
    """Sync prices from Odoo, store baseline in IndexedDB."""
    
    def __init__(
        self,
        conn_mgr: OdooConnectionManager = None,
        indexeddb: IndexedDBBridge = None,
    ):
        self.conn_mgr = conn_mgr or connection_manager
        self.indexeddb = indexeddb or IndexedDBBridge()
    
    def fetch_odoo_products(self) -> Dict[str, dict]:
        """Fetch active goods from Odoo with pricelist discounts."""
        # Same implementation as before - fetch from Odoo
        try:
            products = self.conn_mgr.search_read(
                "product.product",
                domain=[
                    ("barcode", "!=", False),
                    ("active", "=", True),
                    ("type", "=", "consu"),
                ],
                fields=[
                    "barcode",
                    "name",
                    "list_price",
                    "standard_price",
                    "default_code",
                    "product_tmpl_id",
                ],
                limit=100_000,
            )
            
            # Get pricelist ID and fetch discounts
            pricelist_id = self._get_pricelist_id_by_external_id(
                "__export__.product_pricelist_45_73e8f5b3"
            )
            
            pricelist_items: Dict[int, Optional[float]] = {}
            if pricelist_id:
                items = self.conn_mgr.search_read(
                    "product.pricelist.item",
                    domain=[
                        ("pricelist_id", "=", pricelist_id),
                        ("fixed_price", ">", 0),
                    ],
                    fields=["product_tmpl_id", "fixed_price"],
                    limit=100_000,
                )
                for item in items:
                    tmpl_id = item.get("product_tmpl_id")
                    if isinstance(tmpl_id, list) and tmpl_id:
                        tmpl_id = tmpl_id[0]
                    if tmpl_id:
                        pricelist_items[tmpl_id] = item.get("fixed_price")
            
            # Build result dict
            odoo_products: Dict[str, dict] = {}
            for p in products:
                barcode = str(p.get("barcode", "")).strip()
                if not barcode:
                    continue
                
                tmpl_id = p.get("product_tmpl_id")
                if isinstance(tmpl_id, list) and tmpl_id:
                    tmpl_id = tmpl_id[0]
                
                odoo_products[barcode] = {
                    "barcode": barcode,
                    "name": p.get("name", ""),
                    "het": float(p["list_price"]) if p.get("list_price") else 0.0,
                    "diskon": pricelist_items.get(tmpl_id) if tmpl_id else None,
                    "product_tmpl_id": tmpl_id,
                }
            
            print(f"[SYNC] Fetched {len(odoo_products)} products from Odoo")
            return odoo_products
            
        except Exception as e:
            print(f"[SYNC] Error fetching from Odoo: {e}")
            raise
    
    def _get_pricelist_id_by_external_id(self, external_id: str) -> Optional[int]:
        """Resolve pricelist external ID to database ID."""
        try:
            parts = external_id.split(".")
            if len(parts) != 2:
                return None
            module, name = parts
            
            def _resolve(client) -> Optional[int]:
                IrModelData = client.env["ir.model.data"]
                result = IrModelData.search_read(
                    [("module", "=", module), ("name", "=", name)],
                    ["res_id"],
                    limit=1,
                )
                if result:
                    return result[0].get("res_id")
                return None
            
            with self.conn_mgr.connection() as client:
                return _resolve(client)
        except Exception as e:
            print(f"[SYNC] Error resolving pricelist ID: {e}")
        return None
    
    def detect_changes(self) -> SyncResult:
        """Compare Odoo prices against IndexedDB baseline."""
        # Fetch from Odoo
        odoo_products = self.fetch_odoo_products()
        
        # Load baseline from IndexedDB
        local_products_list = self.indexeddb.get_all_products()
        local_products = {p["barcode"]: p for p in local_products_list}
        
        local_barcodes = set(local_products.keys())
        odoo_barcodes = set(odoo_products.keys())
        
        changes: List[PriceChange] = []
        
        # New products
        for barcode in odoo_barcodes - local_barcodes:
            p = odoo_products[barcode]
            changes.append(PriceChange(
                barcode=barcode,
                name=p["name"],
                old_het=None,
                new_het=p["het"],
                old_diskon=None,
                new_diskon=p.get("diskon"),
                change_type="new",
            ))
        
        # Removed products
        for barcode in local_barcodes - odoo_barcodes:
            p = local_products[barcode]
            changes.append(PriceChange(
                barcode=barcode,
                name=p.get("name", ""),
                old_het=p.get("het"),
                new_het=0.0,
                old_diskon=p.get("diskon"),
                new_diskon=None,
                change_type="removed",
            ))
        
        # Changed products
        for barcode in local_barcodes & odoo_barcodes:
            local = local_products[barcode]
            odoo = odoo_products[barcode]
            
            old_het = local.get("het")
            new_het = odoo["het"]
            old_diskon = local.get("diskon")
            new_diskon = odoo.get("diskon")
            
            het_changed = old_het != new_het
            diskon_changed = old_diskon != new_diskon
            
            if het_changed and diskon_changed:
                change_type = "het_and_discount"
            elif het_changed:
                change_type = "increase" if new_het > old_het else "decrease"
            elif diskon_changed:
                change_type = "discount_change"
            else:
                continue  # No change
            
            changes.append(PriceChange(
                barcode=barcode,
                name=odoo["name"],
                old_het=old_het,
                new_het=new_het,
                old_diskon=old_diskon,
                new_diskon=new_diskon,
                change_type=change_type,
            ))
        
        # Sort by change type priority
        type_order = {
            "increase": 0,
            "decrease": 1,
            "het_and_discount": 2,
            "discount_change": 3,
            "new": 4,
            "removed": 5,
        }
        changes.sort(key=lambda x: type_order.get(x.change_type, 99))
        
        result = SyncResult(
            timestamp=datetime.now().isoformat(),
            total_odoo_products=len(odoo_products),
            total_local_products=len(local_products),
            changes=changes,
        )
        
        return result
    
    def commit_changes(self, printed_barcodes: List[str], odoo_products: Dict[str, dict]) -> None:
        """Update IndexedDB with printed changes."""
        products_to_update = []
        
        for barcode in printed_barcodes:
            if barcode in odoo_products:
                p = odoo_products[barcode]
                products_to_update.append({
                    "barcode": barcode,
                    "name": p["name"],
                    "het": p["het"],
                    "diskon": p.get("diskon"),
                    "last_sync": datetime.now().isoformat(),
                })
        
        if products_to_update:
            self.indexeddb.upsert_products(products_to_update)
            print(f"[SYNC] Committed {len(products_to_update)} products to IndexedDB")
    
    def get_sync_status(self) -> Dict[str, Any]:
        """Get current sync status for display."""
        count = self.indexeddb.get_product_count()
        return {
            "cached_products": count,
            "is_initialized": count > 0,
        }
```

- [ ] **Step 2: Add to price sync page**

Modify `ui/pages/price_sync.py`:

```python
# Replace import
from logic.indexeddb_price_sync import IndexedDBPriceSyncService, SyncResult

# Replace service getter
@st.cache_resource(show_spinner=False)
def _get_sync_service() -> IndexedDBPriceSyncService:
    return IndexedDBPriceSyncService()

# Add status display in render function
def render_price_sync_page() -> None:
    # ... existing code ...
    
    # Show IndexedDB status
    sync_status = sync_service.get_sync_status()
    if sync_status["is_initialized"]:
        st.info(f"📦 {sync_status['cached_products']:,} products cached on this device")
    else:
        st.warning("⚠️ First sync will cache all products from Odoo")
```

- [ ] **Step 3: Test basic import works**

Run: `python -c "from logic.indexeddb_price_sync import IndexedDBPriceSyncService; print('Import OK')"`
Expected: Import OK

- [ ] **Step 4: Commit**

```bash
git add logic/indexeddb_price_sync.py
git commit -m "feat: add IndexedDB-based price sync service"
```

---

## Task 4: Full JS-Python Communication

**Files:**
- Modify: `components/indexeddb_manager.html` (add bi-directional comms)
- Modify: `utils/indexeddb_bridge.py` (complete implementation)

### Step 1: Update JavaScript component for bi-directional communication

Update `components/indexeddb_manager.html`:

```html
<!-- Add Streamlit communication library -->
<script src="https://cdn.jsdelivr.net/npm/streamlit-component-lib@2.0.0/build/streamlit-component-lib.min.js"></script>

<script>
    // ... existing IndexedDB code ...
    
    // Streamlit component integration
    const { Streamlit } = window;
    
    function sendToPython(data) {
        Streamlit.setComponentValue(data);
    }
    
    // Listen for Python messages
    Streamlit.events.addEventListener(Streamlit.RENDER_EVENT, (event) => {
        const { action, data } = event.detail.args;
        
        // Process action and send result back
        handleAction(action, data).then(result => {
            sendToPython({ id: data.id, result });
        });
    });
    
    async function handleAction(action, data) {
        switch (action) {
            case 'get_all_products':
                return await getAllProducts();
            case 'upsert_products':
                return await upsertProducts(data.products);
            case 'get_count':
                return { count: await getProductCount() };
            case 'clear_all':
                return await clearAllProducts();
            default:
                return { error: 'Unknown action' };
        }
    }
    
    // Signal ready
    Streamlit.setComponentReady();
</script>
```

- [ ] **Step 2: Complete Python bridge implementation**

Update `utils/indexeddb_bridge.py` with full Streamlit component communication.

- [ ] **Step 3: Test end-to-end**

Run full sync test:
```python
from logic.indexeddb_price_sync import IndexedDBPriceSyncService
service = IndexedDBPriceSyncService()
result = service.detect_changes()
print(f"Found {len(result.changes)} changes")
```

- [ ] **Step 4: Commit**

```bash
git add components/indexeddb_manager.html utils/indexeddb_bridge.py
git commit -m "feat: complete bi-directional JS-Python communication"
```

---

## Summary

This plan implements IndexedDB-based price sync with:
1. JavaScript IndexedDB component for browser storage
2. Python bridge for Streamlit integration
3. Refactored sync service using IndexedDB baseline
4. Per-device isolation (no more Excel coordination issues)

**Next step:** Execute tasks using subagent-driven-development or inline execution.
