"""Service for updating product cost (standard_price) based on vendor bill analysis."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

from odoo.connection import OdooIntegrationError, connection_manager
from logic.price_update_service import PriceUpdateService


class CostUpdateService:
    """Analyze vendor bills and update standard_price (cost) on product.product."""

    def __init__(self):
        self.conn = connection_manager
        self._price_svc = PriceUpdateService()

    # ── Reuse bill listing from PriceUpdateService ─────────────────────────

    def get_recent_bills(self) -> List[Dict[str, Any]]:
        return self._price_svc.get_recent_bills()

    def get_bills_by_date(self, target_date: date) -> List[Dict[str, Any]]:
        return self._price_svc.get_bills_by_date(target_date)

    def get_bills_by_date_range(self, date_from: date, date_to: date) -> List[Dict[str, Any]]:
        return self._price_svc.get_bills_by_date_range(date_from, date_to)

    # ── Cost-specific analysis ────────────────────────────────────────────

    def analyze_bill_for_cost(self, bill_id: int) -> List[Dict[str, Any]]:
        """Analyze vendor bill for cost updates.

        Takes invoice lines, applies discount (negative price_unit lines)
        distributed evenly per-unit across positive lines, then applies
        tax multiplier to get modal_baru. Returns each product with its
        current standard_price from Odoo.

        Returns rows where |modal_baru - standard_price_lama| > 500.
        """
        lines = self._price_svc.get_bill_lines(bill_id)
        positive = lines["positive"]
        negative = lines["negative"]
        if not positive:
            return []

        discount_per_unit = self._price_svc.compute_discount_per_unit(negative, positive)

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

        # Fetch product.product for barcode + template_id
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
        for v in variants:
            tmpl = v.get("product_tmpl_id") or []
            tmpl_id = tmpl[0] if isinstance(tmpl, (list, tuple)) and tmpl else None
            pid_info[v["id"]] = {
                "barcode": str(v.get("barcode") or "").strip(),
                "template_id": tmpl_id,
            }
            sp = v.get("standard_price")
            std_price_map[v["id"]] = float(sp) if sp else 0.0

        # Fetch template for name + list_price
        template_ids = list(set(
            info["template_id"] for info in pid_info.values()
            if info["template_id"] and info["barcode"]
        ))
        tmpl_map: Dict[int, Dict[str, Any]] = {}
        if template_ids:
            try:
                tmpl_data = self.conn.search_read(
                    "product.template",
                    domain=[("id", "in", template_ids)],
                    fields=["id", "name", "list_price"],
                )
                for t in tmpl_data:
                    tmpl_map[t["id"]] = t
            except Exception as exc:
                raise OdooIntegrationError("Failed to fetch product templates.") from exc

        # Compute per line
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
            effective_price = price_unit - discount_per_unit
            if effective_price < 0:
                effective_price = 0

            tax_ids = line.get("tax_ids", [])
            modal_baru = round(effective_price * self._price_svc.get_tax_multiplier(tax_ids))

            std_price_lama = std_price_map.get(vid, 0.0)
            cost_diff = modal_baru - std_price_lama

            if abs(cost_diff) <= 500:
                continue

            rows.append({
                "product_id": vid,
                "template_id": tid,
                "barcode": barcode,
                "name": str(tmpl.get("name") or line.get("name") or "").strip(),
                "list_price": float(tmpl.get("list_price") or 0),
                "modal_baru": modal_baru,
                "standard_price_lama": std_price_lama,
                "standard_price_baru": modal_baru,
                "cost_diff": cost_diff,
            })

        return rows

    # ── Write Operations ──────────────────────────────────────────────────

    def update_product_cost(self, variant_id: int, standard_price: float) -> bool:
        """Update standard_price on product.product. Returns True on success."""
        try:
            result = self.conn.write(
                model_name="product.product",
                ids=[variant_id],
                values={"standard_price": standard_price},
            )
            return bool(result)
        except OdooIntegrationError:
            raise
        except Exception as exc:
            raise OdooIntegrationError(f"Failed to update standard_price for product {variant_id}.") from exc

    def update_selected(
        self,
        rows: List[Dict[str, Any]],
        selected_indices: List[int],
    ) -> Dict[str, Any]:
        """Update multiple selected products' standard_price to Odoo.

        Returns:
            {"success": int, "failed": int, "errors": [(barcode, msg), ...]}
        """
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
