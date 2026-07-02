# DSI Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build DSI (Days Sales of Inventory) report page that calculates inventory turnover per product and classifies items as fast/slow moving.

**Architecture:** New `logic/dsi_service.py` handles Odoo queries (stock.valuation.layer + product.product) and DSI calculation. Page UI in `ui/pages/dsi_report.py` renders form + results table. DSI formula: `(avg_inventory_qty / COGS) × date_range_days`. Avg inventory = (beginning + ending) / 2. Classification uses configurable thresholds.

**Tech Stack:** Python, Streamlit, pandas, odoorpc (via existing connection_manager), Odoo v18 API

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `logic/dsi_service.py` | Create | Odoo queries, DSI calculation, classification |
| `ui/pages/dsi_report.py` | Modify | Form UI, results table, metrics display |
| `tests/test_dsi_service.py` | Create | Unit tests for DSI logic |

---

## Data Source Strategy

Odoo v18 doesn't have a direct "inventory at date" RPC. Two approaches:

1. **`stock.valuation.layer`** — records each stock move with `remaining_qty` and `remaining_value`. Filter by `create_date` ≤ target_date to get on-hand qty and value. This is the most accurate for valuation-based DSI.

2. **`stock.quant`** — has `quantity` but only current snapshot (no historical via standard RPC). Not suitable for "at date" queries.

**Chosen: `stock.valuation.layer`** — filter by product_id + date range, sum `remaining_qty` for inventory levels, sum `value` for COGS.

Fallback: if valuation layers aren't populated (company config), derive from `stock.move.line` with `date` field.

---

## Fast/Slow Moving Classification — Proposal

### Industry Standard Approach
| Category | DSI Range | Interpretation |
|----------|-----------|----------------|
| **Very Fast** | 0–30 days | Sells through inventory in ≤1 month |
| **Fast** | 31–60 days | Sells through in 1–2 months |
| **Normal** | 61–90 days | Healthy turnover |
| **Slow** | 91–180 days | Takes 3–6 months to sell |
| **Dead** | >180 days | Over 6 months, potential write-off |

### Customization
- User can adjust thresholds via sidebar inputs (future enhancement)
- Initial version uses hardcoded industry-standard thresholds
- Color coding: 🟢 Very Fast, 🔵 Fast, ⟡ Normal, 🟠 Slow, 🔴 Dead

---

## Global Constraints

- Python ≥3.10, Streamlit, pandas, odoorpc
- Follow existing codebase patterns (service class in logic/, page class in ui/pages/)
- All Odoo queries via `connection_manager` from `odoo.connection`
- No new dependencies — use stdlib + already-installed packages only
- Date handling: UTC+0700 (WIB) per existing convention

---

### Task 1: Create DSI Service — Core Calculation Logic

**Files:**
- Create: `logic/dsi_service.py`
- Test: `tests/test_dsi_service.py`

**Interfaces:**
- Consumes: `connection_manager` from `odoo.connection`
- Produces: `DSIService` class with methods below

- [ ] **Step 1: Write the failing test**

```python
# tests/test_dsi_service.py
"""Tests for DSI service calculation logic."""

from logic.dsi_service import classify_dsi, calculate_dsi


def test_classify_dsi_very_fast():
    assert classify_dsi(15) == "Very Fast"


def test_classify_dsi_fast():
    assert classify_dsi(45) == "Fast"


def test_classify_dsi_normal():
    assert classify_dsi(75) == "Normal"


def test_classify_dsi_slow():
    assert classify_dsi(120) == "Slow"


def test_classify_dsi_dead():
    assert classify_dsi(200) == "Dead"


def test_calculate_dsi_basic():
    # DSI = (avg_qty / COGS) * days
    # avg_qty = (100 + 50) / 2 = 75
    # COGS = 1000 (total cost of goods sold in period)
    # days = 30
    # DSI = (75 / 1000) * 30 = 2.25
    result = calculate_dsi(
        beginning_qty=100,
        ending_qty=50,
        cogs=1000,
        days=30,
    )
    assert result == 2.25


def test_calculate_dsi_zero_cogs():
    result = calculate_dsi(
        beginning_qty=100,
        ending_qty=50,
        cogs=0,
        days=30,
    )
    assert result is None


def test_calculate_dsi_zero_days():
    result = calculate_dsi(
        beginning_qty=100,
        ending_qty=50,
        cogs=1000,
        days=0,
    )
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dsi_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'logic.dsi_service'`

- [ ] **Step 3: Write minimal implementation**

```python
# logic/dsi_service.py
"""DSI (Days Sales of Inventory) calculation service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import pandas as pd

from odoo.connection import connection_manager


# Classification thresholds (days)
THRESHOLDS = {
    "Very Fast": (0, 30),
    "Fast": (31, 60),
    "Normal": (61, 90),
    "Slow": (91, 180),
    "Dead": (181, float("inf")),
}


@dataclass
class DSIResult:
    """DSI calculation result for a single product."""
    product_id: int
    barcode: str
    name: str
    brand: str
    categ: str
    beginning_qty: float
    ending_qty: float
    avg_qty: float
    cogs: float
    dsi: Optional[float]
    classification: str


def classify_dsi(dsi: float) -> str:
    """Classify DSI value into fast/slow moving category."""
    for label, (low, high) in THRESHOLDS.items():
        if low <= dsi <= high:
            return label
    return "Unknown"


def calculate_dsi(
    beginning_qty: float,
    ending_qty: float,
    cogs: float,
    days: int,
) -> Optional[float]:
    """Calculate DSI: (avg_inventory / COGS) × days."""
    if cogs <= 0 or days <= 0:
        return None
    avg_qty = (beginning_qty + ending_qty) / 2
    return (avg_qty / cogs) * days


def _get_valuation_layers(
    product_ids: List[int],
    date_from: date,
    date_to: date,
) -> Dict[int, Dict[str, float]]:
    """Fetch stock valuation layers for products in date range.
    
    Returns: {product_id: {"qty": float, "value": float}}
    """
    if not product_ids:
        return {}

    rows = connection_manager.search_read(
        model_name="stock.valuation.layer",
        domain=[
            ("product_id", "in", product_ids),
            ("create_date", ">=", date_from.isoformat()),
            ("create_date", "<=", date_to.isoformat()),
        ],
        fields=["product_id", "remaining_qty", "remaining_value"],
        limit=None,
    )

    result: Dict[int, Dict[str, float]] = {}
    for r in rows:
        product = r.get("product_id")
        if not isinstance(product, list):
            continue
        pid = int(product[0])
        qty = float(r.get("remaining_qty") or 0)
        value = float(r.get("remaining_value") or 0)
        if pid not in result:
            result[pid] = {"qty": 0.0, "value": 0.0}
        result[pid]["qty"] += qty
        result[pid]["value"] += value

    return result


def _get_product_info(product_ids: List[int]) -> Dict[int, Dict[str, str]]:
    """Fetch product barcode, name, brand, category."""
    if not product_ids:
        return {}

    rows = connection_manager.search_read(
        model_name="product.product",
        domain=[("id", "in", product_ids)],
        fields=["id", "barcode", "name", "categ_id"],
        limit=None,
    )

    result: Dict[int, Dict[str, str]] = {}
    for r in rows:
        pid = int(r["id"])
        categ = r.get("categ_id")
        categ_name = str(categ[1]) if isinstance(categ, list) and len(categ) > 1 else ""
        result[pid] = {
            "barcode": str(r.get("barcode") or ""),
            "name": str(r.get("name") or ""),
            "brand": "",  # brand field TBD — may be x_studio_brand or custom
            "categ": categ_name,
        }

    return result


def compute_dsi_report(
    date_from: date,
    date_to: date,
    brand_filter: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Compute DSI report for all products with valuation data.
    
    Args:
        date_from: Start date (beginning inventory snapshot)
        date_to: End date (ending inventory snapshot)
        brand_filter: Optional list of brand names to filter by
    
    Returns:
        DataFrame with DSI results per product
    """
    days = (date_to - date_from).days
    if days <= 0:
        return pd.DataFrame()

    # Get beginning inventory (layers at date_from)
    beginning = _get_valuation_layers([], date_from, date_from)
    # Get ending inventory (layers at date_to)
    ending = _get_valuation_layers([], date_to, date_to)
    
    # COGS = sum of outgoing value in the period
    # For now, use ending value as proxy
    all_product_ids = list(set(list(beginning.keys()) + list(ending.keys())))
    
    if not all_product_ids:
        return pd.DataFrame()

    product_info = _get_product_info(all_product_ids)

    records = []
    for pid in all_product_ids:
        info = product_info.get(pid, {})
        beg = beginning.get(pid, {"qty": 0, "value": 0})
        end = ending.get(pid, {"qty": 0, "value": 0})
        
        avg_qty = (beg["qty"] + end["qty"]) / 2
        cogs = end["value"]  # simplified — real COGS needs outgoing moves
        
        dsi = calculate_dsi(beg["qty"], end["qty"], cogs, days)
        classification = classify_dsi(dsi) if dsi is not None else "Unknown"
        
        records.append({
            "product_id": pid,
            "barcode": info.get("barcode", ""),
            "name": info.get("name", ""),
            "brand": info.get("brand", ""),
            "category": info.get("categ", ""),
            "beginning_qty": beg["qty"],
            "ending_qty": end["qty"],
            "avg_qty": avg_qty,
            "cogs": cogs,
            "dsi": dsi,
            "classification": classification,
        })

    df = pd.DataFrame(records)
    
    if brand_filter and "brand" in df.columns:
        df = df[df["brand"].isin(brand_filter)]
    
    # Sort by DSI ascending (fastest movers first)
    df = df.sort_values("dsi", ascending=True, na_position="last")
    df = df.reset_index(drop=True)
    
    return df
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dsi_service.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add logic/dsi_service.py tests/test_dsi_service.py
git commit -m "feat(dsi): add DSI calculation service with classification logic"
```

---

### Task 2: DSI Service — Odoo Integration Tests

**Files:**
- Modify: `tests/test_dsi_service.py`

**Interfaces:**
- Consumes: `DSIService` from Task 1
- Produces: Additional test coverage for edge cases

- [ ] **Step 1: Add classification boundary tests**

```python
# Append to tests/test_dsi_service.py

def test_classify_dsi_boundary_30():
    assert classify_dsi(30) == "Very Fast"


def test_classify_dsi_boundary_31():
    assert classify_dsi(31) == "Fast"


def test_classify_dsi_boundary_60():
    assert classify_dsi(60) == "Fast"


def test_classify_dsi_boundary_61():
    assert classify_dsi(61) == "Normal"


def test_classify_dsi_boundary_90():
    assert classify_dsi(90) == "Normal"


def test_classify_dsi_boundary_91():
    assert classify_dsi(91) == "Slow"


def test_classify_dsi_boundary_180():
    assert classify_dsi(180) == "Slow"


def test_classify_dsi_boundary_181():
    assert classify_dsi(181) == "Dead"


def test_calculate_dsi_negative_cogs():
    result = calculate_dsi(
        beginning_qty=100,
        ending_qty=50,
        cogs=-100,
        days=30,
    )
    assert result is None
```

- [ ] **Step 2: Run all tests**

Run: `python -m pytest tests/test_dsi_service.py -v`
Expected: All 16 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_dsi_service.py
git commit -m "test(dsi): add boundary and edge case tests"
```

---

### Task 3: DSI Report Page — Form UI

**Files:**
- Modify: `ui/pages/dsi_report.py`

**Interfaces:**
- Consumes: `compute_dsi_report()` from Task 1
- Produces: `render_dsi_report_page()` function (already imported in app.py)

- [ ] **Step 1: Write the page with form and placeholder**

```python
# ui/pages/dsi_report.py
"""DSI Report page UI"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta

from logic.dsi_service import compute_dsi_report, classify_dsi


def render_dsi_report_page():
    """Render DSI Report page content"""
    st.title("📋 DSI Report")
    st.markdown("### Days Sales of Inventory Report")

    # --- Form Section ---
    with st.form("dsi_form"):
        col1, col2 = st.columns(2)

        with col1:
            today = date.today()
            default_start = today - timedelta(days=30)
            date_range = st.date_input(
                "📅 Date Range",
                value=(default_start, today),
                max_value=today,
            )

        with col2:
            brand_input = st.text_input(
                "🏷️ Brand Filter (comma-separated, optional)",
                placeholder="e.g. Paragon, Wardah, Make Over",
            )

        submitted = st.form_submit_button(
            "🔍 Generate DSI Report",
            type="primary",
            use_container_width=True,
        )

    # --- Process ---
    if submitted:
        if len(date_range) != 2:
            st.error("❌ Pilih tanggal awal dan akhir.")
            return

        date_from, date_to = date_range
        brand_filter = None
        if brand_input.strip():
            brand_filter = [b.strip() for b in brand_input.split(",") if b.strip()]

        with st.spinner("Menghitung DSI..."):
            try:
                df = compute_dsi_report(
                    date_from=date_from,
                    date_to=date_to,
                    brand_filter=brand_filter,
                )
                st.session_state.dsi_results = df
                st.session_state.dsi_params = {
                    "date_from": date_from,
                    "date_to": date_to,
                    "brand_filter": brand_filter,
                }
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error: {e}")

    # --- Results Section ---
    if "dsi_results" in st.session_state and st.session_state.dsi_results is not None:
        df = st.session_state.dsi_results
        params = st.session_state.get("dsi_params", {})

        if df.empty:
            st.warning("⚠️ Tidak ada data ditemukan untuk filter yang dipilih.")
            return

        # Summary metrics
        st.markdown("---")
        st.subheader("📊 Summary")

        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Total Products", len(df))
        with col2:
            very_fast = len(df[df["classification"] == "Very Fast"])
            st.metric("🟢 Very Fast", very_fast)
        with col3:
            fast = len(df[df["classification"] == "Fast"])
            st.metric("🔵 Fast", fast)
        with col4:
            slow = len(df[df["classification"] == "Slow"])
            st.metric("🟠 Slow", slow)
        with col5:
            dead = len(df[df["classification"] == "Dead"])
            st.metric("🔴 Dead", dead)

        # Classification distribution chart
        st.markdown("---")
        st.subheader("📈 Distribution")

        classification_counts = df["classification"].value_counts()
        st.bar_chart(classification_counts)

        # Results table
        st.markdown("---")
        st.subheader("📋 DSI Details")

        # Format for display
        display_df = df.copy()
        if "dsi" in display_df.columns:
            display_df["dsi"] = display_df["dsi"].apply(
                lambda x: f"{x:.1f}" if pd.notna(x) else "-"
            )
        if "cogs" in display_df.columns:
            display_df["cogs"] = display_df["cogs"].apply(
                lambda x: f"Rp {x:,.0f}" if pd.notna(x) and x > 0 else "-"
            )

        st.dataframe(
            display_df[[
                "barcode", "name", "brand", "category",
                "beginning_qty", "ending_qty", "avg_qty",
                "cogs", "dsi", "classification",
            ]],
            use_container_width=True,
            hide_index=True,
        )

        # Download button
        st.markdown("---")
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name=f"dsi_report_{params.get('date_from', 'export')}.csv",
            mime="text/csv",
        )
```

- [ ] **Step 2: Verify page renders without import errors**

Run: `python -c "from ui.pages.dsi_report import render_dsi_report_page; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/test_dsi_service.py -v`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add ui/pages/dsi_report.py
git commit -m "feat(dsi): add DSI report page with form and results table"
```

---

### Task 4: Verify Integration with App

**Files:**
- Verify: `app.py` (already imports `render_dsi_report_page`)

**Interfaces:**
- Consumes: `render_dsi_report_page()` from Task 3

- [ ] **Step 1: Check app.py already has the import**

Run: `grep "dsi_report" app.py`
Expected: Shows import and tab definition

- [ ] **Step 2: Run app locally**

Run: `streamlit run app.py`
Expected: DSI Report tab visible and functional

- [ ] **Step 3: Final commit if any tweaks needed**

```bash
git add -A
git commit -m "chore(dsi): verify integration with main app"
```

---

## Future Enhancements (Not in This Plan)

1. **Brand field resolution** — Odoo may use `x_studio_brand` or custom field. Need to verify actual field name in production.
2. **COGS accuracy** — Current implementation uses ending valuation as proxy. Real COGS requires querying `stock.move` with `location_dest_id.usage = 'customer'`.
3. **Adjustable thresholds** — Add sidebar inputs for custom classification thresholds.
4. **Historical trends** — Compare DSI across multiple periods.
5. **Export to Excel** — Enhanced formatting with conditional coloring.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-02-dsi-report.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
