# Task 1: Add write_date to Product Template Query

**Files:**
- Modify: `logic/price_update_service.py:193-200`

**Interfaces:**
- Consumes: Existing `self.conn.search_read()` from `odoo.connection`
- Produces: `tmpl_map` dict entries now include `write_date` field (str, ISO 8601 format: "YYYY-MM-DD HH:MM:SS")

## Steps

### Step 1: Write the failing test

```python
# tests/test_price_update_service.py (create if not exists)
import pytest
from logic.price_update_service import PriceUpdateService

def test_analyze_bill_includes_write_date(mocker):
    """Test that analyze_bill fetches and includes write_date from product.template."""
    service = PriceUpdateService()
    
    # Mock the connection methods
    mock_search_read = mocker.patch.object(service.conn, 'search_read')
    
    # Setup mock returns
    mock_search_read.side_effect = [
        # get_bill_lines -> account.move.line
        [{"product_id": [1, "Test Product"], "price_unit": 10000, "quantity": 1, 
          "tax_ids": [], "price_subtotal": 10000}],
        # product.product query
        [{"id": 1, "barcode": "TEST123", "product_tmpl_id": [10, "Template"]}],
        # product.template query - SHOULD include write_date
        [{"id": 10, "name": "Test Product", "list_price": 15000, 
          "write_date": "2026-06-25 14:30:00"}],
        # pricelist items
        [],
        # previous bill lines
        [{"product_id": [1, "Test"], "price_unit": 9000, "tax_ids": [], 
          "price_subtotal": 9000, "move_id": [999, "BILL-999"]}],
    ]
    
    result = service.analyze_bill(bill_id=100)
    
    # Verify write_date is in the result
    assert len(result) > 0
    assert "price_last_updated" in result[0]
    assert result[0]["price_last_updated"] == "2026-06-25 14:30:00"
```

### Step 2: Run test to verify it fails

Run: `pytest tests/test_price_update_service.py::test_analyze_bill_includes_write_date -v`
Expected: FAIL with KeyError "price_last_updated" or AttributeError

### Step 3: Add write_date to fields list in template query

```python
# logic/price_update_service.py:193-200
# Before:
tmpl_data = self.conn.search_read(
    "product.template",
    domain=[("id", "in", template_ids)],
    fields=["id", "name", "list_price"],
)

# After:
tmpl_data = self.conn.search_read(
    "product.template",
    domain=[("id", "in", template_ids)],
    fields=["id", "name", "list_price", "write_date"],
)
```

### Step 4: Pass write_date through to row data

```python
# logic/price_update_service.py:297-305 (in analyze_bill loop)
# Find the line where rows.append() is called, add write_date field:

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
    "price_last_updated": tmpl.get("write_date"),  # ADD THIS LINE
})
```

### Step 5: Run test to verify it passes

Run: `pytest tests/test_price_update_service.py::test_analyze_bill_includes_write_date -v`
Expected: PASS

### Step 6: Commit

```bash
git add logic/price_update_service.py tests/test_price_update_service.py
git commit -m "feat: fetch write_date from product.template in analyze_bill"
```
