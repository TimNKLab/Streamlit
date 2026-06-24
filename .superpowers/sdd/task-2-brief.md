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
