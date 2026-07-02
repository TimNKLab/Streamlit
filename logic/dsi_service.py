"""DSI (Days Sales of Inventory) calculation service."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd

from odoo.connection import connection_manager


# Classification thresholds (days)
THRESHOLDS = {
    "Very Fast": (0, 30),
    "Fast": (31, 60),
    "Normal": (61, 90),
    "Slow": (91, 180),
    "Dead": (181, float("inf")),
}


def classify_dsi(dsi: float) -> str:
    """Classify DSI value into fast/slow moving category."""
    for label, (low, high) in THRESHOLDS.items():
        if low <= dsi <= high:
            return label
    return "Unknown"


def calculate_dsi(
    beginning_qty: float,
    ending_qty: float,
    cogs: float,
    days: int,
) -> Optional[float]:
    """Calculate DSI: (avg_inventory / COGS) * days."""
    if cogs <= 0 or days <= 0:
        return None
    avg_qty = (beginning_qty + ending_qty) / 2
    return (avg_qty / cogs) * days


def _get_valuation_layers(
    product_ids: List[int],
    date_from: date,
    date_to: date,
) -> Dict[int, Dict[str, float]]:
    """Fetch stock valuation layers for products in date range.

    Note: remaining_qty reflects current unconsumed qty, not a date-bound
    historical snapshot — inventory at date may be approximate for products
    with post-period movement.
    ponytail: for accurate at-date inventory, use stock.quant.history when available.

    Returns: {product_id: {"qty": float, "value": float}}
    """
    domain = [
        ("create_date", ">=", date_from.isoformat()),
        ("create_date", "<=", date_to.isoformat()),
    ]
    if product_ids:
        domain.insert(0, ("product_id", "in", product_ids))

    rows = connection_manager.search_read(
        model_name="stock.valuation.layer",
        domain=domain,
        fields=["product_id", "remaining_qty", "remaining_value"],
        limit=None,
    )

    result: Dict[int, Dict[str, float]] = {}
    for r in rows:
        product = r.get("product_id")
        if not isinstance(product, list):
            continue
        pid = int(product[0])
        qty = float(r.get("remaining_qty") or 0)
        value = float(r.get("remaining_value") or 0)
        if pid not in result:
            result[pid] = {"qty": 0.0, "value": 0.0}
        result[pid]["qty"] += qty
        result[pid]["value"] += value

    return result


def _get_product_info(product_ids: List[int]) -> Dict[int, Dict[str, str]]:
    """Fetch product barcode, name, brand, category."""
    if not product_ids:
        return {}

    rows = connection_manager.search_read(
        model_name="product.product",
        domain=[("id", "in", product_ids)],
        fields=["id", "barcode", "name", "categ_id"],
        limit=None,
    )

    result: Dict[int, Dict[str, str]] = {}
    for r in rows:
        pid = int(r["id"])
        categ = r.get("categ_id")
        categ_name = str(categ[1]) if isinstance(categ, list) and len(categ) > 1 else ""
        result[pid] = {
            "barcode": str(r.get("barcode") or ""),
            "name": str(r.get("name") or ""),
            "brand": "",
            "categ": categ_name,
        }

    return result


def compute_dsi_report(
    date_from: date,
    date_to: date,
) -> pd.DataFrame:
    """Compute DSI report for all products with valuation data."""
    days = (date_to - date_from).days
    if days <= 0:
        return pd.DataFrame()

    beginning = _get_valuation_layers([], date_from, date_from)
    ending = _get_valuation_layers([], date_to, date_to)

    all_product_ids = list(set(list(beginning.keys()) + list(ending.keys())))

    if not all_product_ids:
        return pd.DataFrame()

    product_info = _get_product_info(all_product_ids)

    records = []
    for pid in all_product_ids:
        info = product_info.get(pid, {})
        beg = beginning.get(pid, {"qty": 0, "value": 0})
        end = ending.get(pid, {"qty": 0, "value": 0})

        avg_qty = (beg["qty"] + end["qty"]) / 2
        cogs = end["value"]  # ponytail: end["value"] as COGS proxy; real COGS needs stock move analysis

        dsi = calculate_dsi(beg["qty"], end["qty"], cogs, days)
        classification = classify_dsi(dsi) if dsi is not None else "Unknown"

        records.append({
            "product_id": pid,
            "barcode": info.get("barcode", ""),
            "name": info.get("name", ""),
            "brand": info.get("brand", ""),
            "category": info.get("categ", ""),
            "beginning_qty": beg["qty"],
            "ending_qty": end["qty"],
            "avg_qty": avg_qty,
            "cogs": cogs,
            "dsi": dsi,
            "classification": classification,
        })

    df = pd.DataFrame(records)

    df = df.sort_values("dsi", ascending=True, na_position="last")
    df = df.reset_index(drop=True)

    return df
