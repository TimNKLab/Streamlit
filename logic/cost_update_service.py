"""Service for updating product cost (standard_price) based on vendor bill analysis."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from odoo.connection import OdooIntegrationError, connection_manager


class CostUpdateService:
    """Analyze vendor bills and update standard_price (cost) on product.product."""

    TAX_MULTIPLIERS = {
        "PPN Termasuk": 1.0,
        "PPN Blm Termasuk": 1.11,
        "Non PKP": 1.0,
        "PPN Dikecualikan": 1.0,
    }

    def __init__(self):
        self.conn = connection_manager

    # ── Bill listing ─────────────────────────────────────────────────────

    def get_recent_bills(self) -> List[Dict[str, Any]]:
        try:
            return self.conn.search_read(
                model_name="account.move",
                domain=[("move_type", "=", "in_invoice"), ("state", "=", "posted")],
                fields=["id", "name", "ref", "invoice_date", "partner_id"],
                order="invoice_date desc",
                limit=20,
            )
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch recent bills.") from exc

    def get_bills_by_date_range(self, date_from: date, date_to: date) -> List[Dict[str, Any]]:
        try:
            return self.conn.search_read(
                model_name="account.move",
                domain=[
                    ("move_type", "=", "in_invoice"),
                    ("state", "=", "posted"),
                    ("invoice_date", ">=", date_from.isoformat()),
                    ("invoice_date", "<=", date_to.isoformat()),
                ],
                fields=["id", "name", "ref", "invoice_date", "partner_id"],
                order="invoice_date desc",
            )
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch bills by date range.") from exc

    # ── Tax multiplier ───────────────────────────────────────────────────

    def _get_tax_multiplier(self, tax_ids: List) -> float:
        """Determine tax multiplier from tax_ids list (id or [id, name] tuples)."""
        if not tax_ids:
            return 1.0
        for tax in tax_ids:
            if isinstance(tax, (list, tuple)) and len(tax) >= 2:
                name = str(tax[1])
                for key, mult in self.TAX_MULTIPLIERS.items():
                    if key in name:
                        return mult
            elif isinstance(tax, int):
                try:
                    taxes = self.conn.search_read(
                        "account.tax", domain=[("id", "=", tax)], fields=["id", "name"]
                    )
                    for t in taxes:
                        name = str(t.get("name", ""))
                        for key, mult in self.TAX_MULTIPLIERS.items():
                            if key in name:
                                return mult
                except Exception:
                    pass
        return 1.0

    # ── Core analysis ────────────────────────────────────────────────────

    def analyze_bill_for_cost(self, bill_id: int) -> List[Dict[str, Any]]:
        """Analyze vendor bill for cost updates.

        Steps:
          1. Fetch all invoice lines (product_id != False)
          2. Positive lines: price_unit > 0
             Discount lines: price_unit < 0 (skip 0)
          3. subtotal = sum(unit_price × qty) for positive lines
          4. discount_pct = abs(sum(unit_price × qty) for discount lines) / subtotal
          5. For each product:
             real_unit_price = unit_price × (1 - discount_pct) × tax_multiplier
          6. Fetch current standard_price from product.product
          7. Filter |real_unit_price - standard_price_lama| > 500
        """
        try:
            lines = self.conn.search_read(
                model_name="account.move.line",
                domain=[("move_id", "=", bill_id), ("product_id", "!=", False)],
                fields=["product_id", "price_unit", "quantity", "tax_ids",
                        "price_subtotal", "name", "discount"],
            )
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch bill lines.") from exc

        positive = [l for l in lines if float(l.get("price_unit", 0)) > 0]
        discount_lines = [l for l in lines if float(l.get("price_unit", 0)) < 0]

        if not positive:
            return []

        # Step 3: subtotal = sum(unit_price × qty) for positive lines
        subtotal = sum(
            float(l.get("price_unit", 0)) * float(l.get("quantity", 1))
            for l in positive
        )

        # Step 4: discount_pct
        if subtotal == 0:
            return []

        discount_total = sum(
            abs(float(l.get("price_unit", 0)) * float(l.get("quantity", 1)))
            for l in discount_lines
        )
        discount_pct = discount_total / subtotal

        # Collect variant IDs
        variant_ids: List[int] = []
        line_map: Dict[int, Dict[str, Any]] = {}
        for line in positive:
            pid = line.get("product_id", [])
            if isinstance(pid, (list, tuple)) and len(pid) >= 1:
                vid = int(pid[0])
                variant_ids.append(vid)
                line_map[vid] = line

        if not variant_ids:
            return []

        # Fetch product variants (barcode, template_id, current standard_price)
        try:
            variants = self.conn.search_read(
                "product.product",
                domain=[("id", "in", variant_ids)],
                fields=["id", "barcode", "product_tmpl_id", "standard_price"],
            )
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch product variants.") from exc

        pid_info: Dict[int, Dict[str, Any]] = {}
        std_price_map: Dict[int, float] = {}
        template_ids: set = set()
        for v in variants:
            tmpl = v.get("product_tmpl_id") or []
            tmpl_id = tmpl[0] if isinstance(tmpl, (list, tuple)) and tmpl else None
            pid_info[v["id"]] = {
                "barcode": str(v.get("barcode") or "").strip(),
                "template_id": tmpl_id,
            }
            sp = v.get("standard_price")
            std_price_map[v["id"]] = float(sp) if sp else 0.0
            if tmpl_id:
                template_ids.add(tmpl_id)

        # Fetch templates for name + list_price
        tmpl_map: Dict[int, Dict[str, Any]] = {}
        if template_ids:
            try:
                tmpl_data = self.conn.search_read(
                    "product.template",
                    domain=[("id", "in", list(template_ids))],
                    fields=["id", "name", "list_price"],
                )
                for t in tmpl_data:
                    tmpl_map[t["id"]] = t
            except Exception as exc:
                raise OdooIntegrationError("Failed to fetch product templates.") from exc

        # Step 5: compute real_unit_price per product
        rows = []
        for vid in variant_ids:
            info = pid_info.get(vid)
            if not info:
                continue
            barcode = info["barcode"]
            if not barcode:
                continue
            tid = info["template_id"]
            if not tid or tid not in tmpl_map:
                continue

            line = line_map[vid]
            tmpl = tmpl_map[tid]

            price_unit = float(line.get("price_unit", 0))
            discount_pct_line = float(line.get("discount", 0) or 0) / 100
            tax_ids = line.get("tax_ids", [])
            tax_mult = self._get_tax_multiplier(tax_ids)

            # Apply per-line discount, then global discount, then tax
            price_after_line_discount = price_unit * (1 - discount_pct_line)
            real_unit_price = round(price_after_line_discount * (1 - discount_pct) * tax_mult)

            std_price_lama = std_price_map.get(vid, 0.0)
            cost_diff = real_unit_price - std_price_lama

            if abs(cost_diff) <= 500:
                continue

            rows.append({
                "product_id": vid,
                "template_id": tid,
                "barcode": barcode,
                "name": str(tmpl.get("name") or line.get("name") or "").strip(),
                "list_price": float(tmpl.get("list_price") or 0),
                "modal_baru": real_unit_price,
                "standard_price_lama": std_price_lama,
                "standard_price_baru": real_unit_price,
                "cost_diff": cost_diff,
            })

        return rows

    # ── Write Operations ─────────────────────────────────────────────────

    def update_product_cost(self, variant_id: int, standard_price: float) -> bool:
        try:
            return bool(self.conn.write(
                model_name="product.product",
                ids=[variant_id],
                values={"standard_price": standard_price},
            ))
        except Exception as exc:
            raise OdooIntegrationError(f"Failed to update standard_price for product {variant_id}.") from exc

    def update_selected(
        self, rows: List[Dict[str, Any]], selected_indices: List[int]
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {"success": 0, "failed": 0, "errors": []}
        for idx in selected_indices:
            row = rows[idx]
            try:
                new_cost = float(row.get("standard_price_baru", row["modal_baru"]))
                self.update_product_cost(row["product_id"], new_cost)
                result["success"] += 1
            except OdooIntegrationError as e:
                result["failed"] += 1
                result["errors"].append((row["barcode"], str(e)))
        return result
