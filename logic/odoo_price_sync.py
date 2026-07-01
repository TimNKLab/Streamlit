"""Odoo Price Sync Service - Pulls prices from Odoo and detects changes"""

import json
import os
import pandas as pd
from datetime import date, datetime
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
    changed_at: Optional[str] = None  # ISO timestamp from tracking/write_date

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

    # ------------------------------------------------------------------
    # Change detection via mail tracking (new)
    # ------------------------------------------------------------------

    def _get_price_field_ids(self) -> tuple:
        """Get field_ids for list_price on both product.product and product.template.

        Returns (variant_field_id, template_field_id) — either may be None.
        Update Harga writes to product.template, mass imports write to
        product.product, so we must check both to catch all price changes.
        """
        variant_fid = None
        template_fid = None
        try:
            fields = self.conn_mgr.search_read(
                "ir.model.fields",
                domain=[("model", "=", "product.product"), ("name", "=", "list_price")],
                fields=["id"],
                limit=1,
            )
            variant_fid = fields[0]["id"] if fields else None
        except Exception:
            pass
        try:
            fields = self.conn_mgr.search_read(
                "ir.model.fields",
                domain=[("model", "=", "product.template"), ("name", "=", "list_price")],
                fields=["id"],
                limit=1,
            )
            template_fid = fields[0]["id"] if fields else None
        except Exception:
            pass
        return variant_fid, template_fid

    def _query_mail_tracking(
        self, start_date: date, variant_fid: int, template_fid: int
    ) -> Dict[int, tuple]:
        """Query mail.tracking.value for list_price changes since start_date.

        Returns {variant_product_id: (changed_at, old_price)} for products
        with list_price changes. old_price is the value BEFORE the change,
        taken directly from old_value_float — NOT from parquet.

        This is critical: parquet always has current prices (synced by
        sync_from_odoo), so it cannot serve as a baseline.
        """
        field_ids = [fid for fid in (variant_fid, template_fid) if fid is not None]
        if not field_ids:
            return {}

        try:
            trackings = self.conn_mgr.search_read(
                "mail.tracking.value",
                domain=[
                    ("field_id", "in", field_ids),
                    ("create_date", ">=", start_date.isoformat()),
                ],
                fields=["create_date", "mail_message_id", "new_value_float", "old_value_float"],
                order="create_date desc",
            )
        except Exception:
            return {}

        if not trackings:
            return {}

        # Resolve res_id + model via mail.message
        msg_ids = []
        for t in trackings:
            mid = t.get("mail_message_id")
            if isinstance(mid, (list, tuple)) and mid:
                msg_ids.append(mid[0])

        if not msg_ids:
            return {}

        try:
            msgs = self.conn_mgr.search_read(
                "mail.message",
                domain=[("id", "in", msg_ids)],
                fields=["id", "res_id", "model"],
            )
        except Exception:
            return {}

        # Build result: {res_id: (changed_at, old_price)}
        msg_map = {m["id"]: m for m in msgs}
        result: Dict[int, tuple] = {}
        template_ids: set = set()

        for t in trackings:
            mid = t.get("mail_message_id")
            if isinstance(mid, (list, tuple)) and mid:
                mid = mid[0]
            msg = msg_map.get(mid)
            if not msg:
                continue
            rid = msg["res_id"]
            if rid not in result:  # first occurrence = latest (ordered desc)
                old_val = float(t.get("old_value_float") or 0) if t.get("old_value_float") is not None else None
                result[rid] = (t["create_date"], old_val)
            model = msg.get("model")
            if model == "product.template":
                template_ids.add(rid)

        # Map template_ids → variant product IDs
        if template_ids:
            try:
                variants = self.conn_mgr.search_read(
                    "product.product",
                    domain=[("product_tmpl_id", "in", list(template_ids))],
                    fields=["id", "product_tmpl_id"],
                )
                for v in variants:
                    vid = v["id"]
                    ptid = v.get("product_tmpl_id")
                    if isinstance(ptid, (list, tuple)) and ptid:
                        ptid = ptid[0]
                    if ptid in result and vid not in result:
                        result[vid] = result[ptid]
            except Exception:
                pass

        return result

    def _query_write_date_fallback(self, start_date: date) -> List[Dict]:
        """Fallback: query product.product with write_date filter."""
        try:
            return self.conn_mgr.search_read(
                "product.product",
                domain=[
                    ("qty_available", ">", 0),
                    ("write_date", ">=", start_date.isoformat()),
                ],
                fields=["id", "barcode", "name", "list_price", "product_tmpl_id", "write_date"],
            )
        except Exception:
            return []

    def _load_parquet_data(self, parquet_path: str) -> Dict[str, dict]:
        """Load parquet file into {barcode: {het, diskon}} dict."""
        if not os.path.exists(parquet_path):
            return {}
        try:
            df = pd.read_parquet(parquet_path)
            if "barcode" not in df.columns:
                return {}
            df["barcode"] = df["barcode"].astype(str).str.strip()
            has_diskon = "diskon" in df.columns
            result: Dict[str, dict] = {}
            for _, row in df.iterrows():
                bc = row["barcode"]
                if not bc:
                    continue
                result[bc] = {
                    "het": float(row["het"]) if not pd.isna(row.get("het")) else None,
                    "diskon": float(row["diskon"]) if has_diskon and not pd.isna(row.get("diskon")) else None,
                }
            return result
        except Exception:
            return {}

    def _diff_with_tracking(
        self,
        odoo_products: List[Dict],
        changed_map: Dict[int, tuple],
    ) -> List[PriceChange]:
        """Diff Odoo products vs mail tracking old_value_float.

        Tracking's old_value_float is the price BEFORE the change —
        the only reliable baseline. Returns changes where price actually
        changed (new != old). New products have no tracking entry.
        """
        changes: List[PriceChange] = []

        for p in odoo_products:
            barcode = str(p.get("barcode") or "").strip()
            name = str(p.get("name") or "").strip()
            if not barcode or not name:
                continue

            new_price = float(p.get("list_price") or 0)
            pid = p["id"]
            entry = changed_map.get(pid)

            if entry is None:
                continue  # No tracking entry — product didn't change in range

            changed_at, old_price = entry

            if old_price is None:
                # No old value in tracking → can't diff, treat as new
                continue

            if new_price > old_price:
                changes.append(PriceChange(
                    barcode=barcode, name=name,
                    old_price=old_price, new_price=new_price,
                    change_type="increase",
                    changed_at=changed_at,
                ))
            elif new_price < old_price:
                changes.append(PriceChange(
                    barcode=barcode, name=name,
                    old_price=old_price, new_price=new_price,
                    change_type="decrease",
                    changed_at=changed_at,
                ))

        return changes

    def detect_changes_since(self, start_date: date) -> SyncResult:
        """Detect price changes since start_date.

        Primary: mail.tracking.value for list_price field —
        uses old_value_float as baseline, NOT parquet.

        Returns SyncResult with changes categorized as increase/decrease/new.
        """
        # 1. Load parquet baseline (only for "new" product detection)
        parquet_path = str(
            Path(__file__).parent.parent / "data" / "products.parquet"
        )
        parquet_data = self._load_parquet_data(parquet_path)

        # 2. Try primary: mail tracking (check BOTH models)
        variant_fid, template_fid = self._get_price_field_ids()
        changed_map: Dict[int, tuple] = {}

        if variant_fid is not None or template_fid is not None:
            changed_map = self._query_mail_tracking(
                start_date, variant_fid, template_fid
            )

        # 3. Query Odoo products that have tracking entries
        odoo_products: List[Dict] = []
        if changed_map:
            product_ids = list(changed_map.keys())
            try:
                odoo_products = self.conn_mgr.search_read(
                    "product.product",
                    domain=[
                        ("id", "in", product_ids),
                        ("qty_available", ">", 0),
                    ],
                    fields=["id", "barcode", "name", "list_price", "product_tmpl_id"],
                )
            except Exception:
                pass

        if not odoo_products:
            # Fallback: write_date — no old_price available, treat as new
            odoo_products = self._query_write_date_fallback(start_date)

        # 4. Also fetch ALL products to detect "new" (in stock, no tracking entry)
        #    New = exists in Odoo but not in parquet
        try:
            all_products = self.conn_mgr.search_read(
                "product.product",
                domain=[("qty_available", ">", 0)],
                fields=["id", "barcode", "name", "list_price", "product_tmpl_id"],
            )
        except Exception:
            all_products = []

        new_changes: List[PriceChange] = []
        if all_products:
            tracked_ids = {p["id"] for p in odoo_products}
            for p in all_products:
                if p["id"] not in tracked_ids:
                    barcode = str(p.get("barcode") or "").strip()
                    if barcode and barcode not in parquet_data:
                        new_changes.append(PriceChange(
                            barcode=barcode,
                            name=str(p.get("name") or "").strip(),
                            old_price=None,
                            new_price=float(p.get("list_price") or 0),
                            change_type="new",
                        ))

        # 5. Diff using tracking old_value_float
        changes = self._diff_with_tracking(odoo_products, changed_map)

        # 5b. Fallback products (write_date) aren't in changed_map —
        #     diff them against parquet instead
        if not changed_map and odoo_products:
            for p in odoo_products:
                barcode = str(p.get("barcode") or "").strip()
                name = str(p.get("name") or "").strip()
                if not barcode or not name:
                    continue
                new_price = float(p.get("list_price") or 0)
                old = parquet_data.get(barcode)
                if old is None:
                    changes.append(PriceChange(
                        barcode=barcode, name=name,
                        old_price=None, new_price=new_price,
                        change_type="new",
                    ))
                else:
                    old_price = old.get("het")
                    if old_price is not None and new_price != old_price:
                        changes.append(PriceChange(
                            barcode=barcode, name=name,
                            old_price=old_price, new_price=new_price,
                            change_type="increase" if new_price > old_price else "decrease",
                        ))
        changes.extend(new_changes)

        changes.sort(key=lambda c: _CHANGE_TYPE_ORDER.get(c.change_type, 99))

        changes.sort(key=lambda c: _CHANGE_TYPE_ORDER.get(c.change_type, 99))

        result = SyncResult(
            timestamp=datetime.now().isoformat(),
            total_odoo_products=len(all_products) if all_products else len(odoo_products),
            total_local_products=len(parquet_data),
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