"""Service for updating sales prices based on vendor bill analysis."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from odoo.connection import OdooIntegrationError, connection_manager


class PriceUpdateService:
    """Fetch vendor bills, compute margins, and update prices to Odoo."""

    def __init__(self):
        self.conn = connection_manager
        self._tax_map: Dict[int, float] = {}
        self._price_field_id: int | None = None
        self._variant_price_field_id: int | None = None
        self._init_tax_map()
        self._init_price_field_id()

    def _init_tax_map(self) -> None:
        """Query all account.tax records and build id->multiplier map."""
        try:
            taxes = self.conn.search_read(
                "account.tax", domain=[], fields=["id", "name"]
            )
        except Exception:
            self._tax_map = {}
            return
        for t in taxes:
            name = str(t.get("name", ""))
            mult = 1.0
            for key, m in self.TAX_MULTIPLIERS.items():
                if key in name:
                    mult = m
                    break
            self._tax_map[int(t["id"])] = mult

    def _init_price_field_id(self) -> None:
        """Cache ir.model.fields id for product.template.list_price and product.product.list_price.

        Used by analyze_bill to query mail.tracking.value for price-specific
        timestamps. product.template catches UI saves; product.product catches
        mass updates (import xls/csv) that target variant model directly.
        """
        try:
            fields = self.conn.search_read(
                "ir.model.fields",
                domain=[("model", "=", "product.template"), ("name", "=", "list_price")],
                fields=["id"],
                limit=1,
            )
            self._price_field_id = fields[0]["id"] if fields else None
        except Exception:
            self._price_field_id = None

        try:
            fields = self.conn.search_read(
                "ir.model.fields",
                domain=[("model", "=", "product.product"), ("name", "=", "list_price")],
                fields=["id"],
                limit=1,
            )
            self._variant_price_field_id = fields[0]["id"] if fields else None
        except Exception:
            self._variant_price_field_id = None

    def get_recent_bills(self) -> List[Dict[str, Any]]:
        """Return 20 most recent vendor bills (in_invoice)."""
        try:
            return self.conn.search_read(
                model_name="account.move",
                domain=[("move_type", "=", "in_invoice"), ("state", "=", "posted")],
                fields=["id", "name", "ref", "invoice_date", "partner_id"],
                order="invoice_date desc",
                limit=20,
            )
        except OdooIntegrationError:
            raise
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch recent bills.") from exc

    def get_bill_by_number(self, bill_number: str) -> Optional[Dict[str, Any]]:
        """Find a posted vendor bill by name or ref."""
        bill_number = (bill_number or "").strip()
        if not bill_number:
            return None
        try:
            bills = self.conn.search_read(
                "account.move",
                domain=[
                    ("move_type", "=", "in_invoice"),
                    "|",
                    ("name", "=", bill_number),
                    ("ref", "=", bill_number),
                ],
                fields=["id", "name", "ref", "invoice_date", "partner_id"],
                limit=1,
            )
            return bills[0] if bills else None
        except Exception:
            return None

    def get_bills_by_date(self, target_date: date) -> List[Dict[str, Any]]:
        """Return all posted vendor bills for a given date."""
        try:
            return self.conn.search_read(
                model_name="account.move",
                domain=[
                    ("move_type", "=", "in_invoice"),
                    ("state", "=", "posted"),
                    ("invoice_date", "=", target_date.isoformat()),
                ],
                fields=["id", "name", "ref", "invoice_date", "partner_id"],
                order="id desc",
            )
        except OdooIntegrationError:
            raise
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch bills by date.") from exc

    def get_bills_by_date_range(self, date_from: date, date_to: date) -> List[Dict[str, Any]]:
        """Return all posted vendor bills within a date range."""
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
        except OdooIntegrationError:
            raise
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch bills by date range.") from exc

    def get_bill_lines(self, bill_id: int) -> Dict[str, Any]:
        """Get invoice lines for a bill, split into positive (products) and negative (discounts).

        Positive = price_unit > 0. Negative = price_unit < 0 (discount lines).
        """
        try:
            lines = self.conn.search_read(
                model_name="account.move.line",
                domain=[("move_id", "=", bill_id), ("product_id", "!=", False)],
                fields=["product_id", "price_unit", "quantity", "tax_ids",
                        "price_subtotal", "name", "discount"],
            )
        except OdooIntegrationError:
            raise
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch bill lines.") from exc

        positive = [l for l in lines if float(l.get("price_unit", 0)) > 0]
        negative = [l for l in lines if float(l.get("price_unit", 0)) < 0]

        return {"positive": positive, "negative": negative}

    def compute_discount_per_unit(
        self, negative: List[Dict[str, Any]], positive: List[Dict[str, Any]]
    ) -> float:
        """Compute per-unit discount from negative lines.

        Total discount = sum of |price_unit × quantity| for negative lines.
        Divided by sum of quantity across ALL positive lines.
        Result is subtracted from each positive line's price_unit before tax.
        """
        if not negative or not positive:
            return 0.0

        total_discount = sum(
            abs(float(l.get("price_unit", 0)) * float(l.get("quantity", 1)))
            for l in negative
        )
        total_qty = sum(float(l.get("quantity", 1)) for l in positive)
        if total_qty <= 0:
            return 0.0

        return total_discount / total_qty

    # ── Discount, Tax, Margin, Promo Logic ──────────────────────────────

    TAX_MULTIPLIERS = {
        "PPN Termasuk": 1.0,
        "PPN Blm Termasuk": 1.11,
        "Non PKP": 1.0,
        "PPN Dikecualikan": 1.0,
    }

    def get_tax_multiplier(self, tax_ids: List) -> float:
        """Determine tax multiplier from tax_ids list.

        Handles both int IDs ([7]) and name tuples ([[7, "11% (PPN...)"]]).
        Uses cached _tax_map for int IDs.
        """
        if not tax_ids:
            return 1.0
        for tax in tax_ids:
            if isinstance(tax, (list, tuple)) and len(tax) >= 2:
                name = str(tax[1])
                for key, mult in self.TAX_MULTIPLIERS.items():
                    if key in name:
                        return mult
            elif isinstance(tax, int):
                mult = self._tax_map.get(tax)
                if mult is not None and mult != 1.0:
                    return mult
        return 1.0

    def compute_modal(self, price_unit: float, tax_multiplier: float) -> int:
        """Calculate modal = price_unit * tax_mult, rounded."""
        return round(price_unit * tax_multiplier)

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

    # ── Bill Analysis (batch barcode-keyed lookups) ────────────────────

    def analyze_bill(self, bill_id: int) -> List[Dict[str, Any]]:
        """Analyze vendor bill via batch barcode-keyed lookups.

        Step:
          1. Get all invoice lines
          2. Batch query product.product -> barcode + template_id
          3. Batch query product.template -> name + list_price
          4. Batch query product.pricelist.item -> all pricelist rules
          5. Batch query previous bill lines for all variants
          6. Compute per line in-memory

        Returns rows filtered by |diff| > 500.
        """
        lines = self.get_bill_lines(bill_id)
        positive = lines["positive"]
        negative = lines["negative"]
        if not positive:
            return []

        # Get bill's invoice_date for guardrail
        try:
            bill_record = self.conn.search_read(
                "account.move",
                domain=[("id", "=", bill_id)],
                fields=["invoice_date"],
                limit=1,
            )
            invoice_date = str(bill_record[0].get("invoice_date", ""))[:10] if bill_record else ""
        except Exception:
            invoice_date = ""

        # ── 1. Collect variant IDs from invoice lines ────────────────────
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

        # Discount from negative lines: total / sum_qty_positive
        discount_per_unit = self.compute_discount_per_unit(negative, positive)

        # ── 2. Batch: product.product -> barcode + template_id ───────────
        try:
            variants = self.conn.search_read(
                "product.product",
                domain=[("id", "in", variant_ids)],
                fields=["id", "barcode", "product_tmpl_id"],
            )
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch product variants.") from exc

        pid_info: Dict[int, Dict[str, Any]] = {}
        for v in variants:
            tmpl = v.get("product_tmpl_id") or []
            tmpl_id = tmpl[0] if isinstance(tmpl, (list, tuple)) and tmpl else None
            pid_info[v["id"]] = {
                "barcode": str(v.get("barcode") or "").strip(),
                "template_id": tmpl_id,
            }

        # ── 3. Batch: product.template -> name + list_price ───────────────
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
                    fields=["id", "name", "list_price", "write_date"],
                )
                for t in tmpl_data:
                    tmpl_map[t["id"]] = t
            except Exception as exc:
                raise OdooIntegrationError("Failed to fetch product templates.") from exc

        # ── 4. Batch: active loyalty programs for promo detection ────────
        # More reliable than scanning pricelist items for date rules.
        today = date.today()
        promo_map: Dict[int, Dict[str, Any]] = {}
        try:
            active_progs = self.conn.search_read(
                "loyalty.program",
                domain=[
                    ("active", "=", True),
                    ("trigger_product_ids", "in", variant_ids),
                ],
                fields=["id", "name", "date_from", "date_to", "trigger_product_ids"],
            )
            for prog in active_progs:
                df = prog.get("date_from")
                dt = prog.get("date_to")
                try:
                    start_ok = datetime.strptime(str(df)[:10], "%Y-%m-%d").date() <= today if df else True
                    end_ok = datetime.strptime(str(dt)[:10], "%Y-%m-%d").date() >= today if dt else True
                except (ValueError, TypeError):
                    continue
                if not (start_ok and end_ok):
                    continue
                affected = prog.get("trigger_product_ids") or []
                for v in affected:
                    if v in variant_ids and v not in promo_map:
                        promo_map[v] = {
                            "name": prog.get("name"),
                            "date_from": df,
                            "date_to": dt,
                        }
        except Exception:
            # Loyalty optional — promo detection falls through silently
            pass

        # ── 4. Batch: pricelist items for all templates ───────────────────
        pl_map: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        if template_ids:
            try:
                all_items = self.conn.search_read(
                    "product.pricelist.item",
                    domain=[("product_tmpl_id", "in", template_ids)],
                    fields=[
                        "id", "product_tmpl_id", "pricelist_id", "applied_on",
                        "date_start", "date_end", "fixed_price",
                        "min_quantity", "compute_price", "base",
                    ],
                )
                for item in all_items:
                    ptid = item.get("product_tmpl_id")
                    if isinstance(ptid, (list, tuple)):
                        ptid = ptid[0]
                    if ptid:
                        pl_map[ptid].append(item)
            except Exception as exc:
                raise OdooIntegrationError("Failed to fetch pricelist items.") from exc

        # ── 5. Batch: price change timestamps via mail.tracking.value ────
        # Query BOTH product.template (UI saves) and product.product (mass
        # import/csv, which target variant model directly).  Map variant →
        # template via pid_info so one dict per template covers both sources.
        price_updates: Dict[int, str] = {}
        if self._price_field_id and template_ids:
            field_ids = [self._price_field_id]
            if self._variant_price_field_id:
                field_ids.append(self._variant_price_field_id)

            try:
                msgs = self.conn.search_read(
                    "mail.message",
                    domain=[
                        "|",
                        "&", ("model", "=", "product.template"),
                             ("res_id", "in", template_ids),
                        "&", ("model", "=", "product.product"),
                             ("res_id", "in", variant_ids),
                    ],
                    fields=["id", "res_id", "model", "date"],
                    order="date desc",
                )
                msg_ids = [m["id"] for m in msgs]
                msg_info: Dict[int, tuple] = {m["id"]: (m["res_id"], m["model"]) for m in msgs}

                if msg_ids:
                    trackings = self.conn.search_read(
                        "mail.tracking.value",
                        domain=[("mail_message_id", "in", msg_ids),
                                ("field_id", "in", field_ids)],
                        fields=["create_date", "mail_message_id"],
                        order="create_date desc",
                    )
                    seen: set = set()
                    for tv in trackings:
                        mid = tv["mail_message_id"]
                        if isinstance(mid, (list, tuple)):
                            mid = mid[0]
                        info = msg_info.get(mid)
                        if not info:
                            continue
                        res_id, model = info
                        if model == "product.template":
                            tmpl_id = res_id
                        elif model == "product.product":
                            info_v = pid_info.get(res_id)
                            tmpl_id = info_v["template_id"] if info_v else None
                        else:
                            continue
                        if tmpl_id and tmpl_id not in seen:
                            seen.add(tmpl_id)
                            price_updates[tmpl_id] = tv["create_date"]
            except Exception:
                # Tracking data optional — fallback to write_date
                pass

        # ── 6. Batch: previous bill lines for all variants ────────────────
        prev_map: Dict[int, Optional[Dict[str, Any]]] = {}
        try:
            prev_lines = self.conn.search_read(
                "account.move.line",
                domain=[
                    ("product_id", "in", variant_ids),
                    ("move_id.move_type", "=", "in_invoice"),
                    ("move_id.id", "!=", bill_id),
                    ("price_unit", ">", 0),
                ],
                fields=["product_id", "price_unit", "quantity", "tax_ids",
                        "price_subtotal", "move_id", "discount"],
                order="id desc",
            )
        except Exception as exc:
            raise OdooIntegrationError("Failed to fetch previous bill lines.") from exc

        seen_pids: set = set()
        for pl in prev_lines:
            pids = pl.get("product_id")
            if isinstance(pids, (list, tuple)) and pids:
                actual_pid = pids[0]
                if actual_pid not in seen_pids:
                    seen_pids.add(actual_pid)
                    prev_map[actual_pid] = pl

        # ── 6. Compute per line in-memory ────────────────────────────────
        today = date.today()
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

            name = str(tmpl.get("name") or line.get("name") or "").strip()
            list_price = float(tmpl.get("list_price") or 0)

            pricelist_rules = self._extract_pricelist_rules(pl_map.get(tid, []))

            price_unit = float(line.get("price_unit", 0))
            discount_pct = float(line.get("discount", 0) or 0) / 100
            tax_ids = line.get("tax_ids", [])

            # Apply line discount first, then negative-line global discount, then tax
            price_after_line_discount = price_unit * (1 - discount_pct)
            effective_price = price_after_line_discount - discount_per_unit
            if effective_price < 0:
                effective_price = 0  # floor

            modal_baru = self.compute_modal(
                effective_price, self.get_tax_multiplier(tax_ids)
            )

            prev = prev_map.get(vid)
            modal_lama = None
            if prev:
                prev_price_unit = float(prev.get("price_unit", 0))
                prev_discount_pct = float(prev.get("discount", 0) or 0) / 100
                prev_effective = prev_price_unit * (1 - prev_discount_pct)
                modal_lama = self.compute_modal(
                    prev_effective,
                    self.get_tax_multiplier(prev.get("tax_ids", [])),
                )

            margins = self.compute_margins(list_price, modal_lama, modal_baru)
            if margins["margin_diff_amount"] <= 500:
                continue
            if modal_lama is None:
                continue  # skip new products with no history

            has_promo = vid in promo_map
            promo_period_str = "-"
            promo_price = None
            promo = promo_map.get(vid)
            if promo:
                ds = str(promo.get("date_from", ""))[:10] if promo.get("date_from") else ""
                de = str(promo.get("date_to", ""))[:10] if promo.get("date_to") else ""
                promo_period_str = f"{ds} s.d {de}" if ds and de else (f"mulai {ds}" if ds else "-")

            rows.append({
                "product_id": vid,
                "template_id": tid,
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
                "price_last_updated": price_updates.get(tid),
            })

        # Guardrail: filter out products whose price was updated on/after invoice_date
        # Prevents double-increase when user re-runs the same bill after already updating prices.
        if invoice_date:
            before = len(rows)
            rows = [
                r for r in rows
                if not r.get("price_last_updated") or str(r["price_last_updated"])[:10] < invoice_date
            ]
            if before - len(rows):
                print(f"[GUARD] Filtered {before - len(rows)} products already updated on/after {invoice_date}")

        return rows

    def _extract_pricelist_rules(
        self, items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Normalize pricelist items to a uniform dict format.

        Input items come as structured dicts from get_pricelist_items().
        """
        rules = []
        for item in items:
            pricelist = item.get("pricelist_id")
            if isinstance(pricelist, (list, tuple)):
                pricelist_id = pricelist[0]
            else:
                pricelist_id = item.get("pricelist_id")

            rules.append({
                "id": item.get("id"),
                "pricelist_id": pricelist_id,
                "applied_on": item.get("applied_on", ""),
                "date_start": item.get("date_start"),
                "date_end": item.get("date_end"),
                "fixed_price": item.get("fixed_price"),
                "min_quantity": item.get("min_quantity", 0),
                "compute_price": item.get("compute_price", ""),
                "base": item.get("base", ""),
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
        """Update or create pricelist item fixed_price. Returns True on success.

        Returns True if:
        - Pricelist item updated successfully
        - No pricelist rules exist (nothing to update — list_price already set)
        Returns False only if rules exist but update/create failed.
        """
        rules = row.get("pricelist_rules", [])

        # No rules at all — nothing to update, that's fine
        if not rules:
            return True

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
            {"success": int, "failed": int, "warnings": [(barcode, msg), ...],
             "errors": [(barcode, msg), ...]}
        """
        result: Dict[str, Any] = {"success": 0, "failed": 0, "warnings": [], "errors": []}

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
                pricelist_ok = self.update_pricelist_fixed_price(row, fp)
                result["success"] += 1
                if not pricelist_ok:
                    result["warnings"].append(
                        (row["barcode"], "Harga jual terupdate, pricelist tidak (tidak ada rule).")
                    )
            except OdooIntegrationError as e:
                result["failed"] += 1
                result["errors"].append((row["barcode"], str(e)))

        return result
