"""Utilities for fetching vendor bill data from Odoo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence

from odoo.connection import OdooIntegrationError, connection_manager


Domain = Sequence[Any]


@dataclass(frozen=True)
class VendorBillLine:
    barcode: str
    name: str
    qty: int
    het: float


def _safe_int_qty(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def get_vendor_bill_lines_by_number(bill_number: str) -> List[VendorBillLine]:
    """Fetch vendor bill lines by bill number.

    Looks up `account.move` with `move_type='in_invoice'` by matching either
    the bill `name` or `ref`.

    Returns normalized lines with barcode, name, qty(int-cast), and het.
    """

    bill_number = (bill_number or "").strip()
    if not bill_number:
        return []

    try:
        moves = connection_manager.search_read(
            model_name="account.move",
            domain=[
                ("move_type", "=", "in_invoice"),
                "|",
                ("name", "=", bill_number),
                ("ref", "=", bill_number),
            ],
            fields=["id", "name", "ref", "invoice_line_ids"],
            limit=1,
            order="id desc",
        )
        if not moves:
            return []

        invoice_line_ids = moves[0].get("invoice_line_ids") or []
        if not isinstance(invoice_line_ids, list) or not invoice_line_ids:
            return []

        lines = connection_manager.search_read(
            model_name="account.move.line",
            domain=[
                ("id", "in", invoice_line_ids),
                ("product_id", "!=", False),
                ("quantity", ">", 0),
            ],
            fields=["product_id", "quantity", "name", "x_studio_barcode"],
            limit=len(invoice_line_ids),
        )

        product_ids: List[int] = []
        for line in lines:
            pid = line.get("product_id")
            if isinstance(pid, list) and pid:
                product_ids.append(int(pid[0]))

        if not product_ids:
            return []

        products = connection_manager.search_read(
            model_name="product.product",
            domain=[("id", "in", product_ids)],
            fields=["id", "barcode", "name", "list_price"],
            limit=len(product_ids),
        )
        by_id: Dict[int, Dict[str, Any]] = {int(p["id"]): p for p in products if p.get("id")}

        result: List[VendorBillLine] = []
        for line in lines:
            pid = line.get("product_id")
            if not (isinstance(pid, list) and pid):
                continue
            product = by_id.get(int(pid[0]))
            if not product:
                continue

            # Primary barcode comes from Studio field on the invoice line.
            # Fallback to product barcode if Studio field is missing.
            barcode = str(line.get("x_studio_barcode") or "").strip()
            if not barcode:
                barcode = str(product.get("barcode") or "").strip()
            if not barcode:
                continue

            # Prefer product name; fallback to the line description.
            name = str(product.get("name") or "").strip() or str(line.get("name") or "").strip()
            qty = _safe_int_qty(line.get("quantity"))
            if qty <= 0:
                continue

            het = float(product.get("list_price") or 0.0)

            result.append(VendorBillLine(barcode=barcode, name=name, qty=qty, het=het))

        return result
    except OdooIntegrationError:
        raise
    except Exception as exc:
        raise OdooIntegrationError("Failed to fetch vendor bill lines from Odoo.") from exc
