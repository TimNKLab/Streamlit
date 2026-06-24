"""Service for updating sales prices based on vendor bill analysis."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from odoo.connection import OdooIntegrationError, connection_manager

class PriceUpdateService:
    """Fetch vendor bills, compute margins, and update prices to Odoo."""

    def __init__(self):
        self.conn = connection_manager

    def get_recent_bills(self) -> List[Dict[str, Any]]:
        """Return 20 most recent vendor bills (in_invoice)."""
        try:
            return self.conn.search_read(
                model_name="account.move",
                domain=[("move_type", "=", "in_invoice")],
                fields=["id", "name", "ref", "invoice_date", "partner_id"],
                order="invoice_date desc",
                limit=20,
            )
        except OdooIntegrationError:
            raise
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch recent bills.") from exc

    def get_bill_lines(self, bill_id: int) -> Dict[str, Any]:
        """Get invoice lines for a bill, split into positive (products) and negative (discounts).

        Returns:
            {
                "positive": [{"product_id": [id, name], "price_unit": float, "quantity": float,
                              "tax_ids": [[id, name]], "price_subtotal": float, "name": str}, ...],
                "negative": [same fields with price_subtotal < 0, ...],
            }
        """
        try:
            lines = self.conn.search_read(
                model_name="account.move.line",
                domain=[("move_id", "=", bill_id), ("product_id", "!=", False)],
                fields=["product_id", "price_unit", "quantity", "tax_ids",
                        "price_subtotal", "name"],
            )
        except OdooIntegrationError:
            raise
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch bill lines.") from exc

        positive = [l for l in lines if l.get("price_subtotal", 0) > 0]
        negative = [l for l in lines if l.get("price_subtotal", 0) < 0]

        return {"positive": positive, "negative": negative}

    def get_product_template(self, product_id: int) -> Optional[Dict[str, Any]]:
        """Get product.template with pricelist rules for a product variant."""
        try:
            templates = self.conn.search_read(
                model_name="product.template",
                domain=[("product_variant_ids", "in", [product_id])],
                fields=[
                    "id", "barcode", "name", "list_price", "standard_price",
                    "x_studio_pricelist_rules_ids/id",
                    "x_studio_pricelist_rules_ids/pricelist_id/id",
                    "x_studio_pricelist_rules_ids/pricelist_id/name",
                    "x_studio_pricelist_rules_ids/applied_on",
                    "x_studio_pricelist_rules_ids/date_start",
                    "x_studio_pricelist_rules_ids/date_end",
                    "x_studio_pricelist_rules_ids/fixed_price",
                ],
                limit=1,
            )
            return templates[0] if templates else None
        except OdooIntegrationError:
            raise
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch product template.") from exc

    def get_previous_bill_line(
        self, product_id: int, current_bill_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get the most recent vendor bill line for a product (excluding current bill)."""
        try:
            lines = self.conn.search_read(
                model_name="account.move.line",
                domain=[
                    ("product_id", "=", product_id),
                    ("move_id.move_type", "=", "in_invoice"),
                    ("move_id.id", "!=", current_bill_id),
                    ("price_unit", ">", 0),
                ],
                fields=["price_unit", "quantity", "tax_ids", "price_subtotal", "move_id"],
                order="move_id.invoice_date desc",
                limit=1,
            )
            return lines[0] if lines else None
        except OdooIntegrationError:
            raise
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch previous bill line.") from exc

    # ── Discount, Tax, Margin, Promo Logic ──────────────────────────────

    TAX_MULTIPLIERS = {
        "11% PPN Termasuk": 1.0,
        "11% PPN Blm Termasuk": 1.11,
        "0% Non PKP/FP": 1.0,
        "0% PPN Dikecualikan": 1.0,
    }

    def compute_discount_prorata(
        self, positive: List[Dict[str, Any]], negative: List[Dict[str, Any]]
    ) -> float:
        """Compute discount percentage from negative lines prorated across positive lines.

        Returns discount_pct (0.0 if no negative lines).
        """
        if not negative:
            return 0.0

        sum_base = sum(
            l.get("price_unit", 0) * l.get("quantity", 0) for l in positive
        )
        if sum_base <= 0:
            return 0.0

        total_discount = abs(sum(l.get("price_subtotal", 0) for l in negative))
        pct = total_discount / sum_base
        # Guard: discount > 100% is suspicious, treat as 0
        if pct > 1.0:
            return 0.0
        return pct

    def get_tax_multiplier(self, tax_ids: List) -> float:
        """Determine tax multiplier from tax_ids list.

        tax_ids comes from Odoo as [[id, name], ...] or [].
        If any tax name matches '11% PPN Blm Termasuk', return 1.11.
        Otherwise return 1.0.
        """
        if not tax_ids:
            return 1.0

        for tax in tax_ids:
            if isinstance(tax, (list, tuple)) and len(tax) >= 2:
                name = str(tax[1])
                for key, mult in self.TAX_MULTIPLIERS.items():
                    if key in name:
                        return mult
        return 1.0

    def compute_modal_baru(
        self, price_unit: float, discount_pct: float, tax_multiplier: float
    ) -> float:
        """Calculate final modal price after discount and tax adjustment."""
        after_discount = price_unit * (1 - discount_pct)
        return round(after_discount * tax_multiplier)

    def compute_margins(
        self,
        list_price: float,
        modal_lama: Optional[float],
        modal_baru: float,
    ) -> Dict[str, Any]:
        """Calculate margins before and after price change.

        Returns:
            {"margin_before": float | None, "margin_after": float | None,
             "margin_diff_amount": float}
        """
        margin_before = None
        if modal_lama and modal_lama > 0:
            margin_before = (list_price / modal_lama) - 1

        margin_after = None
        if modal_baru > 0:
            margin_after = (list_price / modal_baru) - 1

        margin_diff_amount = abs(modal_baru - (modal_lama or 0))

        return {
            "margin_before": margin_before,
            "margin_after": margin_after,
            "margin_diff_amount": margin_diff_amount,
        }

    def has_active_promo(self, pricelist_rules: List[Dict[str, Any]]) -> bool:
        """Check if any pricelist rule is an active promo (date range + discount)."""
        return self._get_active_promo_rule(pricelist_rules) is not None

    def analyze_bill(self, bill_id: int) -> List[Dict[str, Any]]:
        """Full analysis of a vendor bill: products with margins and promo.

        Returns list of product rows ready for display, filtered by |diff| > 500.
        Each row:
            product_id, template_id, barcode, name,
            modal_lama, modal_baru, list_price,
            margin_before, margin_after, margin_diff_amount,
            has_promo, promo_period_str, promo_price,
            pricelist_rules (raw for updates)
        """
        lines = self.get_bill_lines(bill_id)
        positive = lines["positive"]
        negative = lines["negative"]

        if not positive:
            return []

        discount_pct = self.compute_discount_prorata(positive, negative)
        today = date.today()
        rows = []

        for line in positive:
            pid_raw = line.get("product_id", [])
            if not (isinstance(pid_raw, (list, tuple)) and len(pid_raw) >= 1):
                continue
            product_id = int(pid_raw[0])

            tmpl = self.get_product_template(product_id)
            if not tmpl:
                continue

            template_id = int(tmpl["id"])
            barcode = str(tmpl.get("barcode") or "").strip()
            if not barcode:
                continue

            name = str(tmpl.get("name") or line.get("name") or "").strip()
            list_price = float(tmpl.get("list_price") or 0)

            price_unit = float(line.get("price_unit", 0))
            tax_ids = line.get("tax_ids", [])
            tax_mult = self.get_tax_multiplier(tax_ids)
            modal_baru = self.compute_modal_baru(price_unit, discount_pct, tax_mult)

            prev = self.get_previous_bill_line(product_id, bill_id)
            modal_lama = None
            if prev:
                prev_tax_mult = self.get_tax_multiplier(prev.get("tax_ids", []))
                modal_lama = self.compute_modal_baru(
                    float(prev.get("price_unit", 0)),
                    discount_pct,
                    prev_tax_mult,
                )

            margins = self.compute_margins(list_price, modal_lama, modal_baru)

            if margins["margin_diff_amount"] <= 500:
                continue

            pricelist_rules = self._extract_pricelist_rules(tmpl)
            has_promo = self.has_active_promo(pricelist_rules)
            promo_period_str = "-"
            promo_price = None
            if has_promo and pricelist_rules:
                active = self._get_active_promo_rule(pricelist_rules)
                if active:
                    ds = str(active.get("date_start", ""))[:10]
                    de = str(active.get("date_end", ""))[:10] if active.get("date_end") else ""
                    if de:
                        promo_period_str = f"{ds} s.d {de}"
                    else:
                        promo_period_str = f"mulai {ds}"
                    promo_price = active.get("fixed_price")

            rows.append({
                "product_id": product_id,
                "template_id": template_id,
                "barcode": barcode,
                "name": name,
                "modal_lama": modal_lama,
                "modal_baru": modal_baru,
                "list_price": list_price,
                "margin_before": margins["margin_before"],
                "margin_after": margins["margin_after"],
                "margin_diff_amount": margins["margin_diff_amount"],
                "has_promo": has_promo,
                "promo_period_str": promo_period_str,
                "promo_price": promo_price,
                "pricelist_rules": pricelist_rules,
                "sales_price_baru": list_price,
                "fixed_price_baru": promo_price or list_price,
            })

        return rows

    def _extract_pricelist_rules(
        self, tmpl: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Extract pricelist rules from flat Odoo search_read response.

        x_studio_pricelist_rules_ids returns flat arrays like:
          [rule_id_1, pricelist_id_1, pricelist_name_1, applied_on_1,
           date_start_1, date_end_1, fixed_price_1,
           rule_id_2, pricelist_id_2, ...]
        """
        rules = []
        raw_id = tmpl.get("x_studio_pricelist_rules_ids/id") or []
        raw_pricelist_id = tmpl.get("x_studio_pricelist_rules_ids/pricelist_id/id") or []
        raw_pricelist_name = tmpl.get("x_studio_pricelist_rules_ids/pricelist_id/name") or []
        raw_applied_on = tmpl.get("x_studio_pricelist_rules_ids/applied_on") or []
        raw_date_start = tmpl.get("x_studio_pricelist_rules_ids/date_start") or []
        raw_date_end = tmpl.get("x_studio_pricelist_rules_ids/date_end") or []
        raw_fixed_price = tmpl.get("x_studio_pricelist_rules_ids/fixed_price") or []

        length = len(raw_id)
        for i in range(length):
            rules.append({
                "id": raw_id[i] if i < len(raw_id) else None,
                "pricelist_id": raw_pricelist_id[i] if i < len(raw_pricelist_id) else None,
                "pricelist_name": raw_pricelist_name[i] if i < len(raw_pricelist_name) else "",
                "applied_on": raw_applied_on[i] if i < len(raw_applied_on) else "",
                "date_start": raw_date_start[i] if i < len(raw_date_start) else None,
                "date_end": raw_date_end[i] if i < len(raw_date_end) else None,
                "fixed_price": raw_fixed_price[i] if i < len(raw_fixed_price) else None,
            })
        return rules

    def _get_active_promo_rule(
        self, rules: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Return the first active promo rule (date range + discount)."""
        today = date.today()
        for rule in rules:
            ds_str = rule.get("date_start")
            if not ds_str:
                continue
            try:
                ds = datetime.strptime(str(ds_str)[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            de = None
            if rule.get("date_end"):
                try:
                    de = datetime.strptime(str(rule["date_end"])[:10], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    pass
            fp = rule.get("fixed_price")
            if fp and ds <= today and (de is None or de >= today) and float(fp) > 0:
                return rule
        return None

    # ── Write Operations ────────────────────────────────────────────────

    def validate_no_active_promo(
        self, row: Dict[str, Any], force: bool = False
    ) -> Tuple[bool, str]:
        """Check if product has active promo blocking update.

        Returns (is_valid, warning_message).
        """
        if force:
            return True, ""
        if row.get("has_promo", False):
            return False, "Produk memiliki promo aktif. Gunakan Force untuk override."
        return True, ""

    def update_product_price(self, template_id: int, sales_price: float) -> bool:
        """Update list_price on product.template. Returns True on success."""
        try:
            result = self.conn.write(
                model_name="product.template",
                ids=[template_id],
                values={"list_price": sales_price},
            )
            return bool(result)
        except OdooIntegrationError:
            raise
        except Exception as exc:
            raise OdooIntegrationError(f"Failed to update list_price for template {template_id}.") from exc

    def update_pricelist_fixed_price(
        self, row: Dict[str, Any], fixed_price: float
    ) -> bool:
        """Update or create pricelist item fixed_price. Returns True on success."""
        rules = row.get("pricelist_rules", [])
        active_rule = self._get_active_promo_rule(rules)

        # If an active promo exists, update its fixed_price
        if active_rule and active_rule.get("id"):
            try:
                return bool(self.conn.write(
                    model_name="product.pricelist.item",
                    ids=[int(active_rule["id"])],
                    values={"fixed_price": fixed_price},
                ))
            except OdooIntegrationError:
                raise
            except Exception as exc:
                raise OdooIntegrationError("Failed to update pricelist item.") from exc

        # Try to find any existing pricelist rule for this product
        existing_rule_id = None
        for rule in rules:
            if rule.get("id"):
                existing_rule_id = int(rule["id"])
                break

        if existing_rule_id:
            try:
                return bool(self.conn.write(
                    model_name="product.pricelist.item",
                    ids=[existing_rule_id],
                    values={"fixed_price": fixed_price},
                ))
            except OdooIntegrationError:
                raise
            except Exception as exc:
                raise OdooIntegrationError("Failed to update pricelist item.") from exc

        # No existing rule — create one
        pricelist_id = None
        for rule in rules:
            if rule.get("pricelist_id"):
                pricelist_id = int(rule["pricelist_id"])
                break

        if not pricelist_id:
            return False

        try:
            new_id = self.conn.create(
                model_name="product.pricelist.item",
                values={
                    "pricelist_id": pricelist_id,
                    "product_tmpl_id": row["template_id"],
                    "applied_on": "0_product_variant",
                    "fixed_price": fixed_price,
                },
            )
            return new_id > 0
        except OdooIntegrationError:
            raise
        except Exception as exc:
            raise OdooIntegrationError("Failed to create pricelist item.") from exc

    def update_selected(
        self,
        rows: List[Dict[str, Any]],
        selected_indices: List[int],
        force_map: Dict[int, bool],
    ) -> Dict[str, Any]:
        """Update multiple selected products to Odoo.

        Args:
            rows: Full row data from analyze_bill
            selected_indices: List of row indices to update
            force_map: {row_index: force_bool} for promo override

        Returns:
            {"success": int, "failed": int, "errors": [(barcode, msg), ...]}
        """
        result = {"success": 0, "failed": 0, "errors": []}

        for idx in selected_indices:
            row = rows[idx]
            force = force_map.get(idx, False)

            # Validate promo
            valid, msg = self.validate_no_active_promo(row, force)
            if not valid:
                result["failed"] += 1
                result["errors"].append((row["barcode"], msg))
                continue

            try:
                sp = float(row.get("sales_price_baru", row["list_price"]))
                self.update_product_price(row["template_id"], sp)
                fp = float(row.get("fixed_price_baru", sp))
                self.update_pricelist_fixed_price(row, fp)
                result["success"] += 1
            except OdooIntegrationError as e:
                result["failed"] += 1
                result["errors"].append((row["barcode"], str(e)))

        return result
