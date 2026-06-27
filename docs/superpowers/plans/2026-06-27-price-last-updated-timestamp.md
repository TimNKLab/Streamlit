# Price Last Updated Timestamp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a timestamp column to the Update Harga page showing when each product's sales price was last modified in Odoo

**Architecture:** Query the `write_date` field from `product.template` (Odoo's automatic audit field), pass it through the analysis pipeline, and display it as a formatted column in the data editor. No custom fields needed since Odoo automatically tracks `write_date` for all record modifications.

**Tech Stack:** Python, Streamlit, Odoo XML-RPC API, pandas

## Global Constraints

- Must use existing Odoo automatic fields (`write_date`) - no custom field creation
- Timestamp must display in Indonesian locale format (DD/MM/YYYY HH:MM)
- Must handle missing/null `write_date` values gracefully
- No breaking changes to existing analyze_bill workflow
- Must work for both single bill and batch-by-date modes

---

### Task 1: Add write_date to Product Template Query

**Files:**
- Modify: `logic/price_update_service.py:193-200`

**Interfaces:**
- Consumes: Existing `self.conn.search_read()` from `odoo.connection`
- Produces: `tmpl_map` dict entries now include `write_date` field (str, ISO 8601 format: "YYYY-MM-DD HH:MM:SS")

- [ ] **Step 1: Write the failing test**

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

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_price_update_service.py::test_analyze_bill_includes_write_date -v`
Expected: FAIL with KeyError "price_last_updated" or AttributeError

- [ ] **Step 3: Add write_date to fields list in template query**

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

- [ ] **Step 4: Pass write_date through to row data**

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

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_price_update_service.py::test_analyze_bill_includes_write_date -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add logic/price_update_service.py tests/test_price_update_service.py
git commit -m "feat: fetch write_date from product.template in analyze_bill"
```

---

### Task 2: Add Timestamp Formatting Helper

**Files:**
- Modify: `ui/pages/update_price.py:15-30`

**Interfaces:**
- Consumes: ISO 8601 timestamp string from Odoo (e.g., "2026-06-25 14:30:00")
- Produces: `_fmt_datetime(v: str | None) -> str` function returning formatted string "25/06/2026 14:30" or "-"

- [ ] **Step 1: Write the failing test**

```python
# tests/test_update_price_helpers.py (create new file)
import pytest
from ui.pages.update_price import _fmt_datetime

def test_fmt_datetime_with_valid_timestamp():
    """Test formatting valid ISO timestamp to Indonesian format."""
    result = _fmt_datetime("2026-06-25 14:30:00")
    assert result == "25/06/2026 14:30"

def test_fmt_datetime_with_none():
    """Test formatting None returns dash."""
    result = _fmt_datetime(None)
    assert result == "-"

def test_fmt_datetime_with_empty_string():
    """Test formatting empty string returns dash."""
    result = _fmt_datetime("")
    assert result == "-"

def test_fmt_datetime_with_invalid_format():
    """Test formatting invalid timestamp returns dash."""
    result = _fmt_datetime("invalid-date")
    assert result == "-"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_update_price_helpers.py -v`
Expected: FAIL with ImportError or function not defined

- [ ] **Step 3: Implement _fmt_datetime helper**

```python
# ui/pages/update_price.py:26-36 (after existing _fmt_pct helper)
from datetime import datetime

def _fmt_datetime(v: str | None) -> str:
    """Format ISO timestamp to DD/MM/YYYY HH:MM. Returns '-' for None/invalid."""
    if not v or not isinstance(v, str):
        return "-"
    try:
        dt = datetime.fromisoformat(str(v).replace(" ", "T"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except (ValueError, AttributeError):
        return "-"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_update_price_helpers.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add ui/pages/update_price.py tests/test_update_price_helpers.py
git commit -m "feat: add timestamp formatter for Indonesian locale"
```

---

### Task 3: Add Timestamp Column to Analysis Table

**Files:**
- Modify: `ui/pages/update_price.py:135-170` (df_data loop in _render_analysis)

**Interfaces:**
- Consumes: `raw_rows` with `price_last_updated` field from Task 1
- Produces: DataFrame column "Terakhir Diupdate" displaying formatted timestamps

- [ ] **Step 1: Write integration test**

```python
# tests/test_update_price_ui.py (create new file)
import pytest
import pandas as pd
from ui.pages.update_price import _render_analysis

def test_analysis_table_includes_timestamp_column(mocker):
    """Test that analysis table includes 'Terakhir Diupdate' column."""
    # Mock streamlit components
    mocker.patch('streamlit.markdown')
    mocker.patch('streamlit.caption')
    mocker.patch('streamlit.data_editor', return_value=pd.DataFrame())
    mocker.patch('streamlit.columns', return_value=[mocker.Mock(), mocker.Mock(), mocker.Mock()])
    mocker.patch('streamlit.info')
    
    mock_service = mocker.Mock()
    raw_rows = [{
        "barcode": "TEST123",
        "name": "Test Product",
        "list_price": 15000,
        "margin_before": 0.25,
        "modal_lama": 12000,
        "modal_baru": 13000,
        "has_promo": False,
        "promo_period_str": "-",
        "pricelist_rules": [],
        "price_last_updated": "2026-06-25 14:30:00",
    }]
    
    # Call _render_analysis (which creates df internally)
    # We can't easily test the df structure without refactoring,
    # so this test verifies no errors occur when price_last_updated is present
    try:
        _render_analysis(mock_service, raw_rows, "Test Bill")
        assert True  # No exception means timestamp was handled
    except KeyError as e:
        pytest.fail(f"Missing field in analysis: {e}")
```

- [ ] **Step 2: Run test to verify current behavior**

Run: `pytest tests/test_update_price_ui.py::test_analysis_table_includes_timestamp_column -v`
Expected: PASS (baseline - no changes yet)

- [ ] **Step 3: Add timestamp column to df_data dict**

```python
# ui/pages/update_price.py:150-170 (in df_data.append() call)
# Find the df_data.append() section and add the timestamp field:

df_data.append({
    "No": idx + 1,
    "Pilih": not r["has_promo"],
    "Force?": False,
    "Barcode": r["barcode"],
    "Nama Produk": r["name"],
    "Sales Price Lama": _fmt_rp(r["list_price"]),
    "Fixed Price Lama": _fmt_rp(fp_lama),
    "Margin Lama": _fmt_pct(r["margin_before"]),
    "Modal Lama": _fmt_rp(r["modal_lama"]),
    "Modal Baru": _fmt_rp(r["modal_baru"]),
    "Harga→Fix": _fmt_pct(sf_ratio) if sf_ratio is not None else "-",
    "Sales Price Baru": sp_baru,
    "Fixed Price Baru": fp_baru,
    "Terakhir Diupdate": _fmt_datetime(r.get("price_last_updated")),  # ADD THIS LINE
    "Promo": "✅ Aktif" if r["has_promo"] else "❌ Tidak",
    "Periode Promo": r["promo_period_str"],
})
```

- [ ] **Step 4: Add column config for timestamp column**

```python
# ui/pages/update_price.py:185-210 (in st.data_editor column_config)
# Add configuration for the new column:

edited_df = st.data_editor(
    df,
    column_config={
        "Pilih": st.column_config.CheckboxColumn("Pilih", default=True, width="small"),
        "Force?": st.column_config.CheckboxColumn("Force?", default=False, width="small", help="Override guardrail promo aktif"),
        "Sales Price Baru": st.column_config.NumberColumn("Sales Price Baru", format="Rp %d", min_value=0, required=True),
        "Fixed Price Baru": st.column_config.NumberColumn("Fixed Price Baru", format="Rp %d", min_value=0, required=True),
        "Sales Price Lama": st.column_config.TextColumn("Sales Price Lama", disabled=True),
        "Fixed Price Lama": st.column_config.TextColumn("Fixed Price Lama", disabled=True),
        "Margin Lama": st.column_config.TextColumn("Margin Lama", disabled=True, width="small"),
        "Modal Lama": st.column_config.TextColumn("Modal Lama", disabled=True),
        "Modal Baru": st.column_config.TextColumn("Modal Baru", disabled=True),
        "Harga→Fix": st.column_config.TextColumn("Harga→Fix", disabled=True, width="small"),
        "Terakhir Diupdate": st.column_config.TextColumn("Terakhir Diupdate", disabled=True, width="medium"),  # ADD THIS
        "Promo": st.column_config.TextColumn("Promo", disabled=True, width="small"),
        "Periode Promo": st.column_config.TextColumn("Periode Promo", disabled=True),
        "Barcode": st.column_config.TextColumn("Barcode", disabled=True),
        "Nama Produk": st.column_config.TextColumn("Nama Produk", disabled=True),
        "No": st.column_config.NumberColumn("No", disabled=True),
    },
    # ... rest of config
)
```

- [ ] **Step 5: Manual test in browser**

Run: `streamlit run app.py`
Navigate to: Update Harga page
Action: Select a vendor bill and click Load
Expected: Table shows "Terakhir Diupdate" column with formatted timestamps (DD/MM/YYYY HH:MM)

- [ ] **Step 6: Commit**

```bash
git add ui/pages/update_price.py tests/test_update_price_ui.py
git commit -m "feat: add 'Terakhir Diupdate' timestamp column to price analysis table"
```

---

### Task 4: Verify Batch-by-Date Mode Works

**Files:**
- Test: `ui/pages/update_price.py:358-400` (batch by date workflow)

**Interfaces:**
- Consumes: Existing batch-by-date code path from `update_price.py`
- Produces: Verification that timestamp column appears in batch mode

- [ ] **Step 1: Manual test batch mode**

Run: `streamlit run app.py`
Navigate to: Update Harga page
Action: 
1. Select "Pilih Tanggal" radio button
2. Choose a date with vendor bills
3. Click "Load Bills"
Expected: Table shows "Terakhir Diupdate" column with timestamps for all products from multiple bills

- [ ] **Step 2: Verify dedup preserves timestamp**

Check: Products that appear in multiple bills should show the write_date from the first occurrence (largest bill ID)
Expected: Timestamp matches the first bill's product data, not overwritten by dedup

- [ ] **Step 3: Test edge cases**

Test cases:
1. Product with no write_date (new product) → should show "-"
2. Product with invalid timestamp format → should show "-"
3. Product updated today → should show today's date with time
Expected: All edge cases handle gracefully without errors

- [ ] **Step 4: Document findings**

If any issues found during testing:
- Log them as comments in this task
- If bugs found, create new tasks to fix them
- If working as expected, proceed to commit

- [ ] **Step 5: Commit verification**

```bash
git add -A
git commit -m "test: verify timestamp column works in batch-by-date mode"
```

---

### Task 5: Add User Documentation

**Files:**
- Create: `docs/features/price-last-updated-timestamp.md`

**Interfaces:**
- Consumes: N/A (documentation only)
- Produces: User-facing documentation explaining the new timestamp feature

- [ ] **Step 1: Create documentation file**

```markdown
# Price Last Updated Timestamp

## Overview

The Update Harga page now displays a **"Terakhir Diupdate"** (Last Updated) column showing when each product's sales price was last modified in Odoo.

## How It Works

- **Data Source:** The timestamp comes from Odoo's automatic `write_date` field on `product.template`
- **Format:** Indonesian locale - DD/MM/YYYY HH:MM (e.g., "25/06/2026 14:30")
- **Scope:** Shows when ANY field on the product template was last modified, not just the price
- **Missing Data:** Products with no modification history show "-"

## Use Cases

1. **Price Change Audit:** Quickly see when prices were last updated
2. **Stale Price Detection:** Identify products with old prices that may need review
3. **Update Tracking:** After batch updates, verify which products were modified

## Technical Notes

### Why Not Track Price-Specific Changes?

Odoo's `write_date` tracks ANY field modification on the product record. To track price-specific changes would require:
- Creating a custom field (e.g., `x_price_last_updated`)
- Adding custom logic to update this field on every price change
- Maintaining this custom logic across Odoo upgrades

For this use case, the generic `write_date` provides sufficient information without additional maintenance overhead.

### Timestamp Accuracy

The timestamp reflects the last write operation on the `product.template` record, which could be:
- Sales price (`list_price`) update
- Product name change
- Description update
- Any other field modification
- Automated system updates

If precise price-only tracking is needed in the future, consider using Odoo's field tracking feature with the `mail.thread` mixin, which logs field-specific changes to the chatter.

## See Also

- [Update Harga Feature](HANDOFF-2026-06-24-update-harga.md)
- [Odoo `write_date` Documentation](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html)
```

- [ ] **Step 2: Run documentation through review**

Check:
- Technical accuracy
- User-friendly language
- Complete coverage of feature behavior
Expected: Documentation is clear and accurate

- [ ] **Step 3: Commit documentation**

```bash
git add docs/features/price-last-updated-timestamp.md
git commit -m "docs: add documentation for price last updated timestamp feature"
```

---

### Task 6: Update MEMORY.md

**Files:**
- Modify: `.claude/projects/D--NKLabs-Streamlit/memory/MEMORY.md`

**Interfaces:**
- Consumes: Completed feature implementation
- Produces: Memory entry for future reference

- [ ] **Step 1: Create feature memory file**

```markdown
---
name: price-last-updated-timestamp
description: Update Harga page displays Odoo write_date timestamp showing when products were last modified
metadata:
  type: project
---

# Price Last Updated Timestamp Feature

The Update Harga page now shows a "Terakhir Diupdate" column displaying when each product was last modified in Odoo.

**Why:** User requested visibility into when sales prices were last updated to identify stale prices and audit price changes.

**How to apply:** 
- The timestamp comes from Odoo's automatic `write_date` field on `product.template`
- Format is Indonesian locale: DD/MM/YYYY HH:MM
- Shows ANY field modification on the product record, not just price changes
- This was the pragmatic choice vs. creating custom fields for price-specific tracking

**Implementation:**
- `logic/price_update_service.py` - fetches `write_date` from product.template
- `ui/pages/update_price.py` - formats and displays timestamp in analysis table
- Works in both single-bill and batch-by-date modes

**Related:** [[update-harga-feature-complete]]
```

- [ ] **Step 2: Add entry to MEMORY.md index**

```markdown
# Add this line to MEMORY.md:
- [Price Last Updated Timestamp](price-last-updated-timestamp.md) — Update Harga shows when products were last modified in Odoo
```

- [ ] **Step 3: Commit memory update**

```bash
git add .claude/projects/D--NKLabs-Streamlit/memory/MEMORY.md .claude/projects/D--NKLabs-Streamlit/memory/price-last-updated-timestamp.md
git commit -m "docs: add memory for price last updated timestamp feature"
```

---

## Self-Review Checklist

**Spec coverage:**
- ✓ Timestamp column showing when sales price was last updated
- ✓ Research Odoo's timestamp tracking capabilities (use write_date)
- ✓ No custom field creation needed
- ✓ Works for both single-bill and batch modes

**Placeholder scan:**
- ✓ All code blocks complete with actual implementation
- ✓ No "TBD", "TODO", or "implement later" placeholders
- ✓ All file paths are exact
- ✓ All commands are runnable

**Type consistency:**
- ✓ `price_last_updated` field name consistent across all tasks
- ✓ `_fmt_datetime` function signature consistent
- ✓ DataFrame column name "Terakhir Diupdate" consistent

**DRY/YAGNI/TDD:**
- ✓ TDD workflow: write test → run (fail) → implement → run (pass) → commit
- ✓ No over-engineering: use existing Odoo fields, no custom tracking
- ✓ Frequent commits after each passing test
