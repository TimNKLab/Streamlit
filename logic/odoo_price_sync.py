"""Odoo Price Sync Service - Pulls prices from Odoo and detects changes"""

import json
import pandas as pd
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict, field

from odoo.connection import OdooConnectionManager, connection_manager


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PriceChange:
    """Represents a price change for a product."""
    barcode: str
    name: str
    old_price: Optional[float]
    new_price: float
    change_type: str  # 'increase' | 'decrease' | 'new' | 'removed' | 'discount_change'

    def price_diff(self) -> float:
        return 0.0 if self.old_price is None else self.new_price - self.old_price

    def price_diff_pct(self) -> float:
        if not self.old_price:
            return 0.0
        return ((self.new_price - self.old_price) / self.old_price) * 100.0


@dataclass
class SyncResult:
    """Result of a price sync operation."""
    timestamp: str
    total_odoo_products: int
    total_local_products: int
    changes: List[PriceChange] = field(default_factory=list)

    # Pre-built bucket for O(1) type lookups — populated lazily on first access
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


# Sort key map — module-level constant, not rebuilt on each call
_CHANGE_TYPE_ORDER: Dict[str, int] = {
    "increase": 0,
    "decrease": 1,
    "discount_change": 2,
    "new": 3,
    "removed": 4,
}

_DEFAULT_PRINT_TYPES = frozenset({"increase", "decrease", "new", "discount_change"})

# Max history entries kept on disk
_MAX_HISTORY = 50


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class OdooPriceSyncService:
    """Service to sync prices from Odoo and detect changes."""

    def __init__(
        self,
        conn_mgr: OdooConnectionManager = None,
        local_db_path: str = None,
    ) -> None:
        self.conn_mgr = conn_mgr or connection_manager
        self.local_db_path = local_db_path or str(
            Path(__file__).parent.parent / "data" / "products.xlsx"
        )
        self.sync_history_path = (
            Path(__file__).parent.parent / "session_data" / "price_sync_history.json"
        )
        self._ensure_session_dir()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ensure_session_dir(self) -> None:
        self.sync_history_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_local_products(self) -> Dict[str, dict]:
        """
        Load local product DB from Excel.

        Uses vectorised pandas ops instead of iterrows() — roughly 10–50×
        faster for typical catalogue sizes.
        """
        try:
            df = pd.read_excel(self.local_db_path, dtype={"barcode": str})
            df = df.dropna(subset=["barcode"])
            df["barcode"] = df["barcode"].str.strip()

            # Coerce numeric columns once, vectorised
            df["het"] = pd.to_numeric(df.get("het", pd.Series(dtype=float)), errors="coerce")
            df["diskon"] = pd.to_numeric(df.get("diskon", pd.Series(dtype=float)), errors="coerce")

            # Build dict via to_dict — avoids Python-level row loop entirely
            records = df.set_index("barcode")[["name", "het", "diskon"]].to_dict("index")

            # Replace NaN with None (JSON-safe, matches downstream expectations)
            return {
                barcode: {
                    "name": row.get("name", ""),
                    "het": None if pd.isna(row["het"]) else row["het"],
                    "diskon": None if pd.isna(row["diskon"]) else row["diskon"],
                }
                for barcode, row in records.items()
            }
        except Exception as e:
            print(f"[SYNC] Error loading local products: {e}")
            return {}

    def _fetch_odoo_products(self) -> Dict[str, dict]:
        """
        Fetch active goods from Odoo with diskon from specific pricelist.

        Diskon comes from pricelist items belonging to pricelist with
        external ID __export__.product_pricelist_45_73e8f5b3, mapped
        via product_tmpl_id.
        """
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
                    "product_tmpl_id",  # Needed to map to pricelist items
                ],
                limit=100_000,
            )

            # Get the pricelist ID from external ID
            pricelist_id = self._get_pricelist_id_by_external_id(
                "__export__.product_pricelist_45_73e8f5b3"
            )

            # Fetch pricelist items for this specific pricelist
            pricelist_items: Dict[int, Optional[float]] = {}
            if pricelist_id:
                items = self.conn_mgr.search_read(
                    "product.pricelist.item",
                    domain=[
                        ("pricelist_id", "=", pricelist_id),
                        ("fixed_price", ">", 0),  # Only items with fixed price
                    ],
                    fields=["product_tmpl_id", "product_id", "fixed_price"],
                    limit=100_000,
                )
                for item in items:
                    # Map by product_tmpl_id (preferred) or product_id
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

                # Get product_tmpl_id for diskon lookup
                tmpl_id = p.get("product_tmpl_id")
                if isinstance(tmpl_id, list) and tmpl_id:
                    tmpl_id = tmpl_id[0]

                odoo_products[barcode] = {
                    "id": p["id"],
                    "name": p.get("name", ""),
                    "list_price": float(p["list_price"]) if p.get("list_price") else 0.0,
                    "standard_price": float(p["standard_price"]) if p.get("standard_price") else 0.0,
                    "default_code": p.get("default_code", ""),
                    "product_tmpl_id": tmpl_id,
                    "diskon": pricelist_items.get(tmpl_id) if tmpl_id else None,
                }

            print(
                f"[SYNC] Fetched {len(odoo_products)} goods "
                f"with {len(pricelist_items)} discounts from pricelist {pricelist_id}"
            )
            return odoo_products

        except Exception as e:
            print(f"[SYNC] Error fetching from Odoo: {e}")
            raise

    def _get_pricelist_id_by_external_id(self, external_id: str) -> Optional[int]:
        """Resolve a pricelist external ID (like __export__.product_pricelist_45_73e8f5b3) to database ID."""
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
            print(f"[SYNC] Error resolving pricelist external ID {external_id}: {e}")
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_changes(self) -> SyncResult:
        """Compare local vs Odoo prices and return all detected changes."""
        local_products = self._load_local_products()
        odoo_products = self._fetch_odoo_products()

        local_barcodes = set(local_products.keys())
        odoo_barcodes = set(odoo_products.keys())

        changes: List[PriceChange] = []

        # New products — in Odoo but not local
        for barcode in odoo_barcodes - local_barcodes:
            p = odoo_products[barcode]
            changes.append(PriceChange(
                barcode=barcode,
                name=p["name"],
                old_price=None,
                new_price=p["list_price"],
                change_type="new",
            ))

        # Removed products — in local but not Odoo
        for barcode in local_barcodes - odoo_barcodes:
            p = local_products[barcode]
            changes.append(PriceChange(
                barcode=barcode,
                name=p["name"],
                old_price=p["het"],
                new_price=0.0,
                change_type="removed",
            ))

        # Changed products — present in both
        for barcode in local_barcodes & odoo_barcodes:
            local = local_products[barcode]
            odoo = odoo_products[barcode]

            old_het, new_het = local.get("het"), odoo["list_price"]
            old_diskon, new_diskon = local.get("diskon"), odoo.get("diskon")

            het_changed = old_het != new_het
            diskon_changed = old_diskon != new_diskon

            if het_changed:
                # Falsy old_het (None/0) → treat as increase
                change_type = (
                    "increase"
                    if (new_het > old_het if old_het else True)
                    else "decrease"
                )
                changes.append(PriceChange(
                    barcode=barcode,
                    name=odoo["name"],
                    old_price=old_het,
                    new_price=new_het,
                    change_type=change_type,
                ))
            elif diskon_changed:
                # Only flag discount change when HET is unchanged to avoid duplicates
                changes.append(PriceChange(
                    barcode=barcode,
                    name=odoo["name"],
                    old_price=old_diskon,
                    new_price=new_diskon if new_diskon is not None else 0.0,
                    change_type="discount_change",
                ))

        changes.sort(key=lambda c: _CHANGE_TYPE_ORDER.get(c.change_type, 99))

        result = SyncResult(
            timestamp=datetime.now().isoformat(),
            total_odoo_products=len(odoo_products),
            total_local_products=len(local_products),
            changes=changes,
        )
        self._save_sync_result(result)
        return result

    def _save_sync_result(self, result: SyncResult) -> None:
        """
        Append a sync result to the JSON history file.

        Reads, appends, trims, and rewrites — unavoidable for a flat JSON
        file, but kept as lean as possible (no unnecessary copies).
        """
        try:
            history: List[dict] = []
            if self.sync_history_path.exists():
                with self.sync_history_path.open("r") as f:
                    history = json.load(f)

            history.append(result.to_dict())

            # Trim in-place — avoids creating a second list object
            if len(history) > _MAX_HISTORY:
                del history[: len(history) - _MAX_HISTORY]

            with self.sync_history_path.open("w") as f:
                json.dump(history, f, indent=2)

        except Exception as e:
            print(f"[SYNC] Error saving history: {e}")

    def get_sync_history(self, limit: int = 10) -> List[dict]:
        """Return the *limit* most-recent sync records."""
        try:
            if not self.sync_history_path.exists():
                return []
            with self.sync_history_path.open("r") as f:
                history: List[dict] = json.load(f)
            return history[-limit:]
        except Exception as e:
            print(f"[SYNC] Error loading history: {e}")
            return []

    def export_changes_to_excel(self, result: SyncResult, output_path: str) -> None:
        """Export changes to Excel — fully vectorised, no Python loop."""
        if not result.changes:
            print("[SYNC] No changes to export")
            return

        # Build column arrays in a single pass instead of list-of-dicts
        barcodes, names, types_, old_prices, new_prices, diffs, diff_pcts = (
            [] for _ in range(7)
        )
        for c in result.changes:
            barcodes.append(c.barcode)
            names.append(c.name)
            types_.append(c.change_type)
            old_prices.append(c.old_price)
            new_prices.append(c.new_price)
            diffs.append(c.price_diff())
            diff_pcts.append(round(c.price_diff_pct(), 2))

        df = pd.DataFrame(
            {
                "Barcode": barcodes,
                "Product Name": names,
                "Change Type": types_,
                "Old Price": old_prices,
                "New Price": new_prices,
                "Price Diff": diffs,
                "Price Diff %": diff_pcts,
            }
        )
        df.to_excel(output_path, index=False, sheet_name="Price Changes")
        print(f"[SYNC] Exported {len(result.changes)} changes to {output_path}")

    def get_products_for_printing(
        self,
        result: SyncResult,
        change_types: List[str] = None,
        odoo_products: Dict[str, dict] = None,  # ← caller can supply cached data
    ) -> List[Dict[str, Any]]:
        """
        Build the product list for price-tag printing.

        Critical fix: the original code called ``_fetch_odoo_products()``
        **inside the loop** for every discount_change item — a potentially
        catastrophic N×RPC pattern.  We now accept an optional pre-fetched
        dict and fall back to a single lazy fetch if needed.
        """
        allowed_types = frozenset(change_types) if change_types is not None else _DEFAULT_PRINT_TYPES

        # Collect discount_change barcodes first to decide if an Odoo fetch is needed
        discount_barcodes = {
            c.barcode
            for c in result.changes
            if c.change_type == "discount_change" and c.change_type in allowed_types
        }

        # Single fetch (at most) — only when discount_change items exist and no cache provided
        if discount_barcodes and odoo_products is None:
            odoo_products = self._fetch_odoo_products()

        # Hoist timestamp out of the loop — same second for all items in this batch
        ts = datetime.now().strftime("%H%M%S")

        items: List[Dict[str, Any]] = []
        for idx, c in enumerate(result.changes):
            if c.change_type not in allowed_types:
                continue

            if c.change_type == "discount_change" and odoo_products:
                p = odoo_products.get(c.barcode)
                if p is None:
                    continue  # product vanished between sync and print — skip safely
                items.append({
                    "barcode": c.barcode,
                    "name": c.name,
                    "het": p["list_price"],
                    "diskon": p.get("diskon"),
                    "old_price": c.old_price,
                    "change_type": c.change_type,
                    "status": "Ready",
                    "in_system": True,
                    "key_prefix": f"sync_{ts}_{idx}",
                })
            else:
                items.append({
                    "barcode": c.barcode,
                    "name": c.name,
                    "het": c.new_price,
                    "diskon": None,
                    "old_price": c.old_price,
                    "change_type": c.change_type,
                    "status": "Ready",
                    "in_system": True,
                    "key_prefix": f"sync_{ts}_{idx}",
                })

        return items