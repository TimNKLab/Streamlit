"""IndexedDB-based Price Sync Service - Per-device price tracking."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field

import pandas as pd

from odoo.connection import OdooConnectionManager, connection_manager
from utils.indexeddb_bridge import IndexedDBBridge


# Sort key map — module-level constant
_CHANGE_TYPE_ORDER: Dict[str, int] = {
    "increase": 0,
    "decrease": 1,
    "het_and_discount": 2,
    "discount_change": 3,
    "new": 4,
    "removed": 5,
}

_DEFAULT_PRINT_TYPES = frozenset({"increase", "decrease", "new", "discount_change", "het_and_discount"})


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
    
    def price_diff(self) -> float:
        """Calculate price difference for display."""
        if self.change_type == 'discount_change':
            old = self.old_diskon or 0
            new = self.new_diskon or 0
        else:
            old = self.old_het or 0
            new = self.new_het
        return new - old
    
    def price_diff_pct(self) -> float:
        """Calculate percentage change."""
        if self.change_type == 'discount_change':
            old = self.old_diskon
            new = self.new_diskon
        else:
            old = self.old_het
            new = self.new_het
        
        if not old or old == 0:
            return 0.0
        return ((new - old) / old) * 100.0


@dataclass
class SyncResult:
    """Result of a price sync operation."""
    timestamp: str
    total_odoo_products: int
    total_local_products: int
    changes: List[PriceChange] = field(default_factory=list)
    
    # Pre-built bucket for O(1) type lookups
    _buckets: Dict[str, List[PriceChange]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )
    
    def _ensure_buckets(self) -> None:
        if self._buckets:
            return
        buckets: Dict[str, List[PriceChange]] = {}
        for c in self.changes:
            buckets.setdefault(c.change_type, []).append(c)
        self._buckets = buckets
    
    def get_by_type(self, change_type: str) -> List[PriceChange]:
        self._ensure_buckets()
        return self._buckets.get(change_type, [])
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "total_odoo_products": self.total_odoo_products,
            "total_local_products": self.total_local_products,
            "changes": [asdict(c) for c in self.changes],
        }


class IndexedDBPriceSyncService:
    """Sync prices from Odoo, store baseline in IndexedDB (with Excel fallback)."""
    
    def __init__(
        self,
        conn_mgr: OdooConnectionManager = None,
        indexeddb: IndexedDBBridge = None,
        excel_path: str = None,
    ):
        self.conn_mgr = conn_mgr or connection_manager
        self.indexeddb = indexeddb or IndexedDBBridge()
        self.excel_path = excel_path or str(Path(__file__).parent.parent / "data" / "products.xlsx")
    
    def fetch_odoo_products(self) -> Dict[str, dict]:
        """Fetch active goods from Odoo with pricelist discounts."""
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
    
    def _load_excel_baseline(self) -> Dict[str, dict]:
        """Load baseline from Excel file (fallback for first-time users)."""
        try:
            df = pd.read_excel(self.excel_path, dtype={"barcode": str})
            df = df.dropna(subset=["barcode"])
            df["barcode"] = df["barcode"].astype(str).str.strip()
            
            # Coerce numeric columns
            df["het"] = pd.to_numeric(df.get("het", pd.Series(dtype=float)), errors="coerce")
            df["diskon"] = pd.to_numeric(df.get("diskon", pd.Series(dtype=float)), errors="coerce")
            
            products = {}
            for _, row in df.iterrows():
                barcode = str(row["barcode"]).strip()
                products[barcode] = {
                    "barcode": barcode,
                    "name": row.get("name", ""),
                    "het": None if pd.isna(row["het"]) else float(row["het"]),
                    "diskon": None if pd.isna(row["diskon"]) else float(row["diskon"]),
                    "last_sync": "1970-01-01T00:00:00",  # Mark as legacy data
                }
            
            print(f"[SYNC] Loaded {len(products)} products from Excel as initial baseline")
            return products
        except Exception as e:
            print(f"[SYNC] Error loading Excel fallback: {e}")
            return {}
    
    def detect_changes(self) -> SyncResult:
        """Compare Odoo prices against IndexedDB baseline (with Excel fallback)."""
        # Fetch from Odoo
        odoo_products = self.fetch_odoo_products()
        
        # Load baseline from IndexedDB
        local_products_list = self.indexeddb.get_all_products()
        
        # If IndexedDB is empty, try Excel as fallback (first-time use)
        if not local_products_list:
            print("[SYNC] IndexedDB empty, loading Excel as fallback baseline...")
            local_products = self._load_excel_baseline()
            # Save Excel data to IndexedDB for next time
            if local_products:
                self.indexeddb.upsert_products(list(local_products.values()))
                print(f"[SYNC] Saved {len(local_products)} Excel products to IndexedDB")
        else:
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
        changes.sort(key=lambda x: _CHANGE_TYPE_ORDER.get(x.change_type, 99))
        
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
    
    def get_sync_history(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent sync history from session state or return empty list."""
        import streamlit as st
        
        # Get history from session state if available
        history = st.session_state.get("price_sync_history", [])
        
        if not history:
            return []
        
        # Return most recent entries up to limit
        return history[-limit:]
    
    def add_sync_to_history(self, result: SyncResult) -> None:
        """Add a sync result to the history."""
        import streamlit as st
        from datetime import datetime
        
        if "price_sync_history" not in st.session_state:
            st.session_state.price_sync_history = []
        
        history_entry = {
            "timestamp": datetime.now().isoformat(),
            "total_changes": len(result.changes),
            "total_odoo_products": result.total_odoo_products,
            "total_local_products": getattr(result, 'total_local_products', 0),
            "change_summary": result.summary,
        }
        
        st.session_state.price_sync_history.append(history_entry)
        
        # Keep only last 20 entries to prevent memory bloat
        if len(st.session_state.price_sync_history) > 20:
            st.session_state.price_sync_history = st.session_state.price_sync_history[-20:]
    
    def export_changes_to_excel(self, result: SyncResult, output_path: str) -> None:
        """Export changes to Excel for review."""
        import pandas as pd
        
        if not result.changes:
            print("[SYNC] No changes to export")
            return
        
        # Build column arrays
        barcodes, names, types_, old_het, new_het, old_diskon, new_diskon, diffs, diff_pcts = (
            [] for _ in range(9)
        )
        
        for c in result.changes:
            barcodes.append(c.barcode)
            names.append(c.name)
            types_.append(c.change_type)
            old_het.append(c.old_het)
            new_het.append(c.new_het)
            old_diskon.append(c.old_diskon)
            new_diskon.append(c.new_diskon)
            diffs.append(c.price_diff())
            diff_pcts.append(round(c.price_diff_pct(), 2))
        
        df = pd.DataFrame({
            "Barcode": barcodes,
            "Product Name": names,
            "Change Type": types_,
            "Old HET": old_het,
            "New HET": new_het,
            "Old Diskon": old_diskon,
            "New Diskon": new_diskon,
            "Price Diff": diffs,
            "Diff %": diff_pcts,
        })
        
        df.to_excel(output_path, index=False, sheet_name="Price Changes")
        print(f"[SYNC] Exported {len(result.changes)} changes to {output_path}")
    
    def get_products_for_printing(
        self,
        result: SyncResult,
        change_types: List[str] = None,
        odoo_products: Dict[str, dict] = None,
    ) -> List[Dict[str, Any]]:
        """Get product list ready for price tag printing."""
        allowed_types = frozenset(change_types) if change_types is not None else _DEFAULT_PRINT_TYPES
        
        # Fetch odoo products if not provided
        if odoo_products is None:
            odoo_products = self.fetch_odoo_products()
        
        items: List[Dict[str, Any]] = []
        ts = datetime.now().strftime("%H%M%S")
        
        for idx, c in enumerate(result.changes):
            if c.change_type not in allowed_types:
                continue
            
            # Get full product data from odoo_products
            p = odoo_products.get(c.barcode)
            if p is None and c.change_type != "removed":
                continue
            
            if c.change_type == "removed":
                # For removed products, use local data
                items.append({
                    "barcode": c.barcode,
                    "name": c.name,
                    "het": c.old_het or 0,
                    "diskon": c.old_diskon,
                    "old_price": c.old_het,
                    "change_type": c.change_type,
                    "status": "Removed",
                    "in_system": False,
                    "key_prefix": f"sync_{ts}_{idx}",
                })
            else:
                items.append({
                    "barcode": c.barcode,
                    "name": c.name,
                    "het": p["het"],
                    "diskon": p.get("diskon"),
                    "old_price": c.old_het if c.change_type in ['increase', 'decrease'] else c.old_diskon,
                    "change_type": c.change_type,
                    "status": "Ready",
                    "in_system": True,
                    "key_prefix": f"sync_{ts}_{idx}",
                })
        
        return items
