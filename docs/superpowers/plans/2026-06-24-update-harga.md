# Update Harga Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** New page to search vendor bills, display products with margin analysis, and update sales price + pricelist to Odoo.

**Architecture:** New `logic/price_update_service.py` handles all Odoo queries, discount prorata, tax adjustment, margin computation, promo guardrail, and writes. New `ui/pages/update_price.py` handles the Streamlit UI with search/dropdown, editable data_editor table, and update button. `app.py` adds the tab.

**Tech Stack:** Python, Streamlit, OdooRPC, `st.data_editor`

## Global Constraints

- Follow existing pattern: logic/ separated from ui/
- Use `connection_manager` from `odoo.connection` for all Odoo queries
- Use `st.data_editor` not agGrid for editable table
- All prices in IDR (integer rupiah)
- Tax multiplier: 11% PPN Blm Termasuk = 1.11, others = 1.0

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `logic/price_update_service.py` | Create | All Odoo queries, business logic, update operations |
| `ui/pages/update_price.py` | Create | Streamlit UI: bill selector, data_editor, update button |
| `app.py` | Modify | Add `render_update_price_page` import + `"update_harga"` tab |

---

### Task 1: Create Logic Service — Odoo Query Functions

**Files:**
- Create: `logic/price_update_service.py`
- Test: None (runs against real Odoo, manual test)

**Interfaces:**
- Produces: `PriceUpdateService` class with:
  - `get_recent_bills() -> List[Dict]` — 20 most recent `in_invoice` moves
  - `get_bill_lines(bill_id: int) -> Dict` — positive + negative lines separated
  - `get_product_template(product_id: int) -> Dict` — template with pricelist rules
  - `get_previous_bill_line(product_id: int, current_bill_id: int) -> Dict | None`

- [ ] **Step 1: Create service class with get_recent_bills**

```python
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
```

- [ ] **Step 2: Add get_bill_lines (separate positive/negative)**

```python
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
```

- [ ] **Step 3: Add get_product_template**

```python
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
```

- [ ] **Step 4: Add get_previous_bill_line**

```python
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
```

- [ ] **Step 5: Verify import works**

Run: `python -c "from logic.price_update_service import PriceUpdateService; print('OK')"`
Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add logic/price_update_service.py
git commit -m "feat: add PriceUpdateService with Odoo query methods"
```

---

### Task 2: Add Discount, Tax, Margin Computation Logic

**Files:**
- Modify: `logic/price_update_service.py`

**Interfaces:**
- Consumes: `get_bill_lines(bill_id)` → positive/negative lists
- Produces:
  - `compute_discount_prorata(positive: List, negative: List) -> float`
  - `get_tax_multiplier(tax_ids: List) -> float`
  - `compute_modal_baru(price_unit: float, discount_pct: float, tax_multiplier: float) -> float`
  - `compute_margins(list_price: float, modal_lama: Optional[float], modal_baru: float) -> Dict`
  - `has_active_promo(pricelist_rules: List) -> bool`
  - `analyze_bill(bill_id: int) -> List[Dict]` — main orchestrator

- [ ] **Step 1: Add compute_discount_prorata**

```python
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
```

- [ ] **Step 2: Add get_tax_multiplier**

```python
    TAX_MULTIPLIERS = {
        "11% PPN Termasuk": 1.0,
        "11% PPN Blm Termasuk": 1.11,
        "0% Non PKP/FP": 1.0,
        "0% PPN Dikecualikan": 1.0,
    }

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
```

- [ ] **Step 3: Add compute_modal_baru**

```python
    def compute_modal_baru(
        self, price_unit: float, discount_pct: float, tax_multiplier: float
    ) -> float:
        """Calculate final modal price after discount and tax adjustment."""
        after_discount = price_unit * (1 - discount_pct)
        return round(after_discount * tax_multiplier)
```

- [ ] **Step 4: Add compute_margins**

```python
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
```

- [ ] **Step 5: Add has_active_promo**

```python
    def has_active_promo(self, pricelist_rules: List[Dict[str, Any]]) -> bool:
        """Check if any pricelist rule is an active promo (date range + discount)."""
        today = date.today()

        if not pricelist_rules:
            return False

        for rule in pricelist_rules:
            # x_studio_pricelist_rules_ids returns flat values in Odoo search_read
            date_start_str = rule.get("date_start")
            date_end_str = rule.get("date_end")
            fixed_price = rule.get("fixed_price")

            if not date_start_str or not fixed_price:
                continue

            try:
                ds = datetime.strptime(str(date_start_str)[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            de = None
            if date_end_str:
                try:
                    de = datetime.strptime(str(date_end_str)[:10], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    pass

            if ds <= today and (de is None or de >= today) and fixed_price > 0:
                return True

        return False
```

- [ ] **Step 6: Add analyze_bill — the orchestrator**

```python
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

            # Get product template data
            tmpl = self.get_product_template(product_id)
            if not tmpl:
                continue

            template_id = int(tmpl["id"])
            barcode = str(tmpl.get("barcode") or "").strip()
            if not barcode:
                continue

            name = str(tmpl.get("name") or line.get("name") or "").strip()
            list_price = float(tmpl.get("list_price") or 0)

            # Compute modal baru
            price_unit = float(line.get("price_unit", 0))
            tax_ids = line.get("tax_ids", [])
            tax_mult = self.get_tax_multiplier(tax_ids)
            modal_baru = self.compute_modal_baru(price_unit, discount_pct, tax_mult)

            # Get previous bill for modal lama
            prev = self.get_previous_bill_line(product_id, bill_id)
            modal_lama = None
            if prev:
                prev_tax_mult = self.get_tax_multiplier(prev.get("tax_ids", []))
                modal_lama = self.compute_modal_baru(
                    float(prev.get("price_unit", 0)),
                    discount_pct,  # Use same discount pct for consistency
                    prev_tax_mult,
                )

            # Margins
            margins = self.compute_margins(list_price, modal_lama, modal_baru)

            # Only show rows where |diff| > 500
            if margins["margin_diff_amount"] <= 500:
                continue

            # Promo detection
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
                # Pre-filled editable values
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
```

- [ ] **Step 7: Verify import**

Run: `python -c "from logic.price_update_service import PriceUpdateService; s=PriceUpdateService(); print('compute_discount_prorata' in dir(s))"`
Expected: `True`

- [ ] **Step 8: Commit**

```bash
git add logic/price_update_service.py
git commit -m "feat: add discount, tax, margin, promo logic to PriceUpdateService"
```

---

### Task 3: Add Odoo Write Operations (Update Price)

**Files:**
- Modify: `logic/price_update_service.py`

**Interfaces:**
- Consumes: row dicts from analyze_bill
- Produces:
  - `validate_no_active_promo(row: Dict, force: bool) -> Tuple[bool, str]`
  - `update_product_price(template_id: int, sales_price: float) -> bool`
  - `update_pricelist_fixed_price(row: Dict, fixed_price: float) -> bool`
  - `update_selected(rows: List[Dict], selected_indices: List[int], force_map: Dict[int, bool]) -> Dict`

- [ ] **Step 1: Add validate_no_active_promo**

```python
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
```

- [ ] **Step 2: Add update_product_price**

```python
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
```

- [ ] **Step 3: Add update_pricelist_fixed_price**

```python
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
        # Need pricelist_id from first rule (pricelist reference)
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
```

- [ ] **Step 4: Add update_selected (batch update)**

```python
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
                # Update list_price
                sp = float(row.get("sales_price_baru", row["list_price"]))
                self.update_product_price(row["template_id"], sp)

                # Update fixed_price (pricelist)
                fp = float(row.get("fixed_price_baru", sp))
                self.update_pricelist_fixed_price(row, fp)

                result["success"] += 1
            except OdooIntegrationError as e:
                result["failed"] += 1
                result["errors"].append((row["barcode"], str(e)))

        return result
```

- [ ] **Step 5: Verify import**

Run: `python -c "from logic.price_update_service import PriceUpdateService; print(dir(PriceUpdateService))"`
Expected: All method names visible

- [ ] **Step 6: Commit**

```bash
git add logic/price_update_service.py
git commit -m "feat: add price update and pricelist write operations"
```

---

### Task 4: Create UI Page

**Files:**
- Create: `ui/pages/update_price.py`

**Interfaces:**
- Consumes: `PriceUpdateService` from `logic.price_update_service`
- Produces: `render_update_price_page()` function

- [ ] **Step 1: Create page with bill selector and data_editor**

```python
"""Update Harga page — search vendor bills, analyze margins, update Odoo prices."""

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st
import pandas as pd

from logic.price_update_service import PriceUpdateService


def _get_service() -> PriceUpdateService:
    """Get or create cached PriceUpdateService."""
    if "price_update_service" not in st.session_state:
        st.session_state.price_update_service = PriceUpdateService()
    return st.session_state.price_update_service


def _format_rp(value: float | None) -> str:
    if value is None:
        return "-"
    return f"Rp {value:,.0f}"


def _format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def render_update_price_page() -> None:
    """Main render function for Update Harga page."""
    st.title("📈 Update Harga dari Vendor Bill")
    service = _get_service()

    # Step 1: Load recent bills
    if "recent_bills" not in st.session_state:
        with st.spinner("Memuat daftar faktur terbaru..."):
            try:
                bills = service.get_recent_bills()
                st.session_state.recent_bills = bills
            except Exception as e:
                st.error(f"Gagal memuat faktur: {e}")
                st.session_state.recent_bills = []

    bills = st.session_state.recent_bills
    if not bills:
        st.info("Tidak ada faktur vendor ditemukan.")
        return

    # Build dropdown options
    bill_options = {}
    for b in bills:
        label = b.get("name", "?")
        ref = b.get("ref", "")
        date_str = str(b.get("invoice_date", ""))[:10]
        partner = b.get("partner_id")
        partner_name = partner[1] if isinstance(partner, (list, tuple)) and len(partner) >= 2 else ""
        display = f"{label} | {date_str} | {partner_name}"
        if ref:
            display += f" ({ref})"
        bill_options[display] = int(b["id"])

    col1, col2 = st.columns([3, 1])
    with col1:
        selected_label = st.selectbox(
            "Pilih Faktur Vendor",
            options=list(bill_options.keys()),
            key="bill_selector",
        )
    with col2:
        st.markdown("###")
        load_clicked = st.button("🔍 Load", type="primary", use_container_width=True)

    # Step 2: Load and analyze bill
    if load_clicked:
        bill_id = bill_options[selected_label]
        with st.spinner("Menganalisis faktur..."):
            try:
                rows = service.analyze_bill(bill_id)
                st.session_state.analysis_rows = rows
                st.session_state.selected_bill_id = bill_id
                st.session_state.selected_bill_label = selected_label
            except Exception as e:
                st.error(f"Gagal menganalisis faktur: {e}")
                st.session_state.analysis_rows = []

    # Step 3: Display results
    if "analysis_rows" not in st.session_state or not st.session_state.analysis_rows:
        return

    rows = st.session_state.analysis_rows

    # Count promo items for banner
    promo_count = sum(1 for r in rows if r["has_promo"])
    if promo_count > 0:
        st.warning(
            f"⚠️ **{promo_count} produk** memiliki promo aktif. "
            "Centang 'Force?' untuk override guardrail."
        )

    # Build DataFrame for display
    df_data = []
    for idx, r in enumerate(rows):
        df_data.append({
            "No": idx + 1,
            "Barcode": r["barcode"],
            "Nama Produk": r["name"],
            "Harga Modal Lama": _format_rp(r["modal_lama"]),
            "Harga Modal Baru": _format_rp(r["modal_baru"]),
            "Harga Jual": _format_rp(r["list_price"]),
            "Margin Lama": _format_pct(r["margin_before"]),
            "Margin Baru": _format_pct(r["margin_after"]),
            "Promo": "✅ Aktif" if r["has_promo"] else "❌ Tidak",
            "Periode Promo": r["promo_period_str"],
            "Sales Price Baru": r["sales_price_baru"],
            "Fixed Price Baru": r["fixed_price_baru"],
        })

    df = pd.DataFrame(df_data)

    st.markdown("### Hasil Analisis")
    st.caption(
        f"Menampilkan {len(rows)} produk dengan perubahan harga > Rp500. "
        f"{promo_count} produk dengan promo aktif."
    )

    # Checkbox columns for Force? and Pilih
    force_checks = []
    select_checks = []
    for idx, r in enumerate(rows):
        default_force = False
        default_select = not r["has_promo"]
        force_key = f"force_{idx}"
        select_key = f"select_{idx}"

        force_checks.append(st.checkbox(
            "Force?", key=force_key, value=default_force,
            help="Override guardrail promo aktif" if r["has_promo"] else "",
        ))
        select_checks.append(st.checkbox(
            "Pilih", key=select_key, value=default_select,
        ))

    # Display data_editor
    edited_df = st.data_editor(
        df,
        column_config={
            "Sales Price Baru": st.column_config.NumberColumn(
                "Sales Price Baru",
                format="Rp %d",
                min_value=0,
                required=True,
            ),
            "Fixed Price Baru": st.column_config.NumberColumn(
                "Fixed Price Baru",
                format="Rp %d",
                min_value=0,
                required=True,
            ),
            "Harga Modal Lama": st.column_config.TextColumn("Harga Modal Lama", disabled=True),
            "Harga Modal Baru": st.column_config.TextColumn("Harga Modal Baru", disabled=True),
            "Harga Jual": st.column_config.TextColumn("Harga Jual", disabled=True),
            "Margin Lama": st.column_config.TextColumn("Margin Lama", disabled=True),
            "Margin Baru": st.column_config.TextColumn("Margin Baru", disabled=True),
            "Promo": st.column_config.TextColumn("Promo", disabled=True),
            "Periode Promo": st.column_config.TextColumn("Periode Promo", disabled=True),
            "Barcode": st.column_config.TextColumn("Barcode", disabled=True),
            "Nama Produk": st.column_config.TextColumn("Nama Produk", disabled=True),
            "No": st.column_config.NumberColumn("No", disabled=True),
        },
        hide_index=True,
        use_container_width=True,
        disabled=[c for c in df.columns if c not in ["Sales Price Baru", "Fixed Price Baru"]],
        key="analysis_editor",
    )

    # Sync edited values back to session state
    for idx in range(len(rows)):
        rows[idx]["sales_price_baru"] = float(edited_df.iloc[idx]["Sales Price Baru"])
        rows[idx]["fixed_price_baru"] = float(edited_df.iloc[idx]["Fixed Price Baru"])
        rows[idx]["force"] = force_checks[idx]
    st.session_state.analysis_rows = rows

    # Summary
    valid_rows = [r for r in rows if r["margin_before"] is not None and r["margin_after"] is not None]
    if valid_rows:
        avg_margin_lama = sum(r["margin_before"] for r in valid_rows) / len(valid_rows)
        avg_margin_baru = sum(r["margin_after"] for r in valid_rows) / len(valid_rows)
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Produk", len(rows))
        col2.metric("Rata-rata Margin Lama", f"{avg_margin_lama * 100:.1f}%")
        col3.metric("Rata-rata Margin Baru", f"{avg_margin_baru * 100:.1f}%")

    # Step 4: Update button
    selected_indices = [i for i, s in enumerate(select_checks) if s]
    if not selected_indices:
        st.info("Pilih produk yang ingin diupdate, lalu klik 'Update ke Odoo'.")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button(
            f"🚀 Update {len(selected_indices)} Produk ke Odoo",
            type="primary",
            use_container_width=True,
        ):
            force_map = {i: force_checks[i] for i in selected_indices}
            with st.spinner("Mengupdate harga ke Odoo..."):
                try:
                    result = service.update_selected(rows, selected_indices, force_map)
                    if result["failed"] > 0:
                        st.warning(
                            f"{result['success']} berhasil, {result['failed']} gagal."
                        )
                        for barcode, err in result["errors"]:
                            st.error(f"{barcode}: {err}")
                    else:
                        st.success(f"✅ {result['success']} produk berhasil diupdate ke Odoo!")
                except Exception as e:
                    st.error(f"Gagal mengupdate: {e}")
    with col2:
        if st.button("🔄 Reset", use_container_width=True):
            for key in ["analysis_rows", "selected_bill_id", "selected_bill_label"]:
                st.session_state.pop(key, None)
            st.rerun()
```

- [ ] **Step 2: Verify import**

Run: `python -c "from ui.pages.update_price import render_update_price_page; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Add __all__ to ui/__init__.py**

Edit `ui/__init__.py` to add the new page:
```python
from .pages.update_price import render_update_price_page

__all__.append('render_update_price_page')
```

- [ ] **Step 4: Commit**

```bash
git add ui/pages/update_price.py ui/__init__.py
git commit -m "feat: add Update Harga UI page with data_editor"
```

---

### Task 5: Integrate Page into app.py

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add import and tab**

Edit `app.py`:
- Add import: `from ui.pages.update_price import render_update_price_page`
- Add tab entry: `"update_harga": ("Update Harga", render_update_price_page),`
- Update `TAB_NAMES` in `utils/persistence.py` if needed (add "update_harga")

- [ ] **Step 2: Verify app starts**

Run: `streamlit run app.py`
Expected: App starts with "Update Harga" tab visible

- [ ] **Step 3: Commit**

```bash
git add app.py utils/persistence.py
git commit -m "feat: add Update Harga tab to main app"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✅ `get_recent_bills()` — Task 1
- ✅ `get_bill_lines()` split positive/negative — Task 1
- ✅ `get_product_template()` with pricelist rules — Task 1
- ✅ `get_previous_bill_line()` — Task 1
- ✅ `compute_discount_prorata()` — Task 2
- ✅ `get_tax_multiplier()` (4 tax types) — Task 2
- ✅ `compute_modal_baru()` after discount + tax — Task 2
- ✅ `compute_margins()` — Task 2
- ✅ Filter `|diff| > 500` — Task 2
- ✅ `has_active_promo()` with date range — Task 2
- ✅ Promo columns: Promo, Periode Promo — Task 2 + 4
- ✅ `validate_no_active_promo()` — Task 3
- ✅ `update_product_price()` (list_price) — Task 3
- ✅ `update_pricelist_fixed_price()` (create/update pricelist item) — Task 3
- ✅ `update_selected()` batch update with force_map — Task 3
- ✅ UI data_editor with editable Sales Price & Fixed Price — Task 4
- ✅ Force? checkbox + auto-uncheck for promo — Task 4
- ✅ App tab integration — Task 5

**Placeholder scan:** Todos, TBDs, TBCs — none found. All code blocks contain complete implementations.

**Type consistency:** All method signatures match between tasks. `analyze_bill()` returns rows consumed by `update_selected()`. `force_map` type consistent across Task 3 and 4.
