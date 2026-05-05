"""Service helpers for Odoo stock/internal-move workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from odoo.connection import connection_manager


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OdooUser:
    id: int
    name: str


@dataclass(frozen=True)
class OdooLocation:
    id: int
    complete_name: str


@dataclass(frozen=True)
class StockQuantDiff:
    quant_id: int
    barcode: str
    product_id: int
    product_name: str
    display_location_id: int
    display_location_name: str
    diff_qty: float
    display_qty: float


@dataclass(frozen=True)
class CandidateLocationQty:
    location_id: int
    location_name: str
    qty: float


@dataclass(frozen=True)
class ProductUom:
    product_id: int
    uom_id: int


# ---------------------------------------------------------------------------
# Location helpers
# ---------------------------------------------------------------------------

def list_internal_locations(*, query: str | None = None, limit: int = 200) -> List[OdooLocation]:
    domain: List[Any] = [("usage", "=", "internal")]
    if query:
        domain.append(("complete_name", "ilike", query))

    rows = connection_manager.search_read(
        model_name="stock.location",
        domain=domain,
        fields=["complete_name"],
        order="complete_name asc",
        limit=limit,
    )
    return [
        OdooLocation(id=int(r["id"]), complete_name=str(r.get("complete_name") or ""))
        for r in rows
        if r.get("complete_name")
    ]


def get_location_by_complete_name(complete_name: str) -> Optional[OdooLocation]:
    rows = connection_manager.search_read(
        model_name="stock.location",
        domain=[("complete_name", "=", complete_name)],
        fields=["complete_name"],
        limit=1,
    )
    if not rows:
        return None
    row = rows[0]
    return OdooLocation(
        id=int(row["id"]),
        complete_name=str(row.get("complete_name") or complete_name),
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def list_users(limit: int = 200) -> List[OdooUser]:
    rows = connection_manager.search_read(
        model_name="res.users",
        domain=[("active", "=", True)],
        fields=["name"],
        order="name asc",
        limit=limit,
    )
    return [
        OdooUser(id=int(r["id"]), name=str(r.get("name") or ""))
        for r in rows
        if r.get("name")
    ]


# ---------------------------------------------------------------------------
# Employee → partner resolution
# Optimization: fetch all candidate fields in ONE RPC call, resolve in Python.
# Worst case: 2 RPC (employee lookup + user partner fallback).
# Previous worst case: 4 RPC (3 field-set probes + user lookup).
# ---------------------------------------------------------------------------

def _resolve_partner_from_row(row: Dict[str, Any]) -> Optional[int]:
    """Try to extract a partner_id from an hr.employee row. No RPC."""
    for key in ("work_contact_id", "address_id"):
        val = row.get(key)
        if isinstance(val, list) and val:
            return int(val[0])
    return None


def _resolve_partner_via_user(user_field: Any) -> Optional[int]:
    """One extra RPC only if employee has no direct contact field."""
    if not isinstance(user_field, list) or not user_field:
        return None

    user_rows = connection_manager.search_read(
        model_name="res.users",
        domain=[("id", "=", int(user_field[0]))],
        fields=["partner_id"],
        limit=1,
    )
    if not user_rows:
        return None
    partner = user_rows[0].get("partner_id")
    return int(partner[0]) if isinstance(partner, list) and partner else None


def get_employee_partner_id_by_name(name: str) -> Optional[int]:
    """Resolve hr.employee → res.partner by employee name.

    Single search_read fetches all candidate fields at once.
    Falls back to user.partner_id only if needed (1 extra RPC, not 3).
    """
    rows = connection_manager.search_read(
        model_name="hr.employee",
        domain=[("name", "ilike", name)],
        fields=["work_contact_id", "address_id", "user_id"],
        limit=1,
    )
    if not rows:
        return None

    row = rows[0]

    # Fast path: direct contact field on employee (no extra RPC)
    partner_id = _resolve_partner_from_row(row)
    if partner_id is not None:
        return partner_id

    # Slow path: resolve via linked user (1 extra RPC)
    return _resolve_partner_via_user(row.get("user_id"))


def get_employee_partner_id(employee_id: int) -> Optional[int]:
    """Resolve hr.employee by id → res.partner. Same strategy as by-name variant."""
    rows = connection_manager.search_read(
        model_name="hr.employee",
        domain=[("id", "=", int(employee_id))],
        fields=["work_contact_id", "address_id", "user_id"],
        limit=1,
    )
    if not rows:
        return None

    row = rows[0]
    partner_id = _resolve_partner_from_row(row)
    if partner_id is not None:
        return partner_id

    return _resolve_partner_via_user(row.get("user_id"))


# ---------------------------------------------------------------------------
# Stock quant diffs
# ---------------------------------------------------------------------------

def get_stock_quant_diffs_for_user_at_location(
    *,
    user_id: int,
    location_id: int,
    limit: int = 500,
) -> List[StockQuantDiff]:
    rows = connection_manager.search_read(
        model_name="stock.quant",
        domain=[
            ("user_id", "=", user_id),
            ("location_id", "=", location_id),
            ("inventory_diff_quantity", "!=", 0),
        ],
        fields=["x_barcode", "product_id", "location_id", "inventory_diff_quantity", "quantity"],
        order="id asc",
        limit=limit,
    )

    result: List[StockQuantDiff] = []
    for r in rows:
        product = r.get("product_id")
        location = r.get("location_id")
        if not isinstance(product, list) or not isinstance(location, list):
            continue

        result.append(StockQuantDiff(
            quant_id=int(r["id"]),
            barcode=str(r.get("x_barcode") or "").strip(),
            product_id=int(product[0]),
            product_name=str(product[1]) if len(product) > 1 else str(product[0]),
            display_location_id=int(location[0]),
            display_location_name=str(location[1]) if len(location) > 1 else str(location[0]),
            diff_qty=float(r.get("inventory_diff_quantity") or 0),
            display_qty=float(r.get("quantity") or 0),
        ))

    return result


# ---------------------------------------------------------------------------
# Candidate locations — single product
# Optimization: removed _get_locations_by_ids second RPC.
# stock.quant search_read already returns location_id as [id, complete_name]
# because Odoo's name_get() for stock.location returns the full path.
# ---------------------------------------------------------------------------

def get_candidate_internal_locations_for_product(
    *,
    product_id: int,
    exclude_location_id: int,
    limit: int = 100,
) -> List[CandidateLocationQty]:
    rows = connection_manager.search_read(
        model_name="stock.quant",
        domain=[
            ("product_id", "=", product_id),
            ("location_id", "!=", exclude_location_id),
            ("location_id.usage", "=", "internal"),
            ("quantity", ">", 0),
        ],
        fields=["location_id", "quantity"],
        order="quantity desc",
        limit=limit,
    )

    seen: set[int] = set()
    candidates: List[CandidateLocationQty] = []

    for r in rows:
        loc = r.get("location_id")
        if not isinstance(loc, list) or not loc:
            continue
        loc_id = int(loc[0])
        qty = float(r.get("quantity") or 0)
        if qty <= 0 or loc_id in seen:
            continue
        seen.add(loc_id)
        candidates.append(CandidateLocationQty(
            location_id=loc_id,
            location_name=str(loc[1]) if len(loc) > 1 else str(loc_id),
            qty=qty,
        ))

    return candidates


# ---------------------------------------------------------------------------
# Candidate locations — batch (NEW)
# Replaces N serial calls with 1 RPC for all products at once.
# The main page loop called get_candidate_internal_locations_for_product
# once per SKU. This function covers all SKUs in a single round-trip.
# ---------------------------------------------------------------------------

def get_candidate_locations_for_products(
    *,
    product_ids: Sequence[int],
    exclude_location_id: int,
    limit_per_product: int = 100,
) -> Dict[int, List[CandidateLocationQty]]:
    """Fetch candidate locations for multiple products in one RPC call.

    Returns: {product_id: [CandidateLocationQty, ...]} sorted by qty desc per product.
    Products with no candidates will be absent from the result dict.
    """
    if not product_ids:
        return {}

    unique_ids = list(set(product_ids))

    rows = connection_manager.search_read(
        model_name="stock.quant",
        domain=[
            ("product_id", "in", unique_ids),
            ("location_id", "!=", exclude_location_id),
            ("location_id.usage", "=", "internal"),
            ("quantity", ">", 0),
        ],
        fields=["product_id", "location_id", "quantity"],
        order="product_id asc, quantity desc",
        limit=len(unique_ids) * limit_per_product,
    )

    # Group by product_id, deduplicate locations within each group
    result: Dict[int, List[CandidateLocationQty]] = {}

    for r in rows:
        product = r.get("product_id")
        loc = r.get("location_id")
        if not isinstance(product, list) or not isinstance(loc, list):
            continue

        pid = int(product[0])
        loc_id = int(loc[0])
        qty = float(r.get("quantity") or 0)
        if qty <= 0:
            continue

        bucket = result.setdefault(pid, [])

        # Deduplicate locations per product
        if any(c.location_id == loc_id for c in bucket):
            continue
        if len(bucket) >= limit_per_product:
            continue

        bucket.append(CandidateLocationQty(
            location_id=loc_id,
            location_name=str(loc[1]) if len(loc) > 1 else str(loc_id),
            qty=qty,
        ))

    return result


# ---------------------------------------------------------------------------
# UOM
# ---------------------------------------------------------------------------

def get_products_uom_ids(product_ids: Sequence[int]) -> Dict[int, ProductUom]:
    if not product_ids:
        return {}

    rows = connection_manager.search_read(
        model_name="product.product",
        domain=[("id", "in", list(set(product_ids)))],
        fields=["uom_id"],
        limit=None,
    )

    result: Dict[int, ProductUom] = {}
    for r in rows:
        uom = r.get("uom_id")
        if not isinstance(uom, list) or not uom:
            continue
        result[int(r["id"])] = ProductUom(product_id=int(r["id"]), uom_id=int(uom[0]))

    return result


# ---------------------------------------------------------------------------
# Picking type
# ---------------------------------------------------------------------------

def get_internal_picking_type_id() -> Optional[int]:
    rows = connection_manager.search_read(
        model_name="stock.picking.type",
        domain=[("code", "=", "internal")],
        fields=["name"],
        limit=1,
    )
    return int(rows[0]["id"]) if rows else None