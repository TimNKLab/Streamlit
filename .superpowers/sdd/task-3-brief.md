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
                sp = float(row.get("sales_price_baru", row["list_price"]))
                self.update_product_price(row["template_id"], sp)
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

- [ ] **Step 6: Commit**

```bash
git add logic/price_update_service.py
git commit -m "feat: add price update and pricelist write operations"
```
