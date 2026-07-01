# Price Sync Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `detect_changes_since()` mapping bug, add `_detect_new_products_since()`, integrate `PriceTagService` for PDF generation.

**Architecture:** 4 focused changes to 2 files. Fix template→variant ID mapping in `_query_mail_tracking()`. Add `_detect_new_products_since()` using `create_date` filter. Simplify `detect_changes_since()` by removing unreliable write_date fallback. Use `PriceTagService.lookup_product()` for price tag preparation instead of raw PriceChange data.

**Tech Stack:** Python, Odoo XML-RPC, pandas, Streamlit

---
### Task 1: Fix `_query_mail_tracking()` — clean template IDs from result

**Files:**
- Modify: `logic/odoo_price_sync.py:424-461`

**Problem:** Template IDs (from `product.template` tracking entries) stay in the returned `result` dict alongside variant IDs. Caller at line 574 queries `product.product` with `("id", "in", product_ids)` — template IDs don't match any product.product → those products silently vanish from results.

**Fix:** After the template→variant mapping loop, remove template IDs from `result`.

- [ ] **Step 1: Add cleanup after mapping loop**

Locate lines 446-460 (the `if template_ids:` block). After the inner `for v in variants:` loop ends (after line 457), add:

```python
    # Remove template IDs — only variant IDs go to caller
    for tid in template_ids:
        result.pop(tid, None)
```

So the full block becomes:

```python
    if template_ids:
        try:
            variants = self.conn_mgr.search_read(
                "product.product",
                domain=[("product_tmpl_id", "in", list(template_ids))],
                fields=["id", "product_tmpl_id"],
            )
            for v in variants:
                vid = v["id"]
                ptid = v.get("product_tmpl_id")
                if isinstance(ptid, (list, tuple)) and ptid:
                    ptid = ptid[0]
                if ptid in result and vid not in result:
                    result[vid] = result[ptid]
        except Exception:
            pass

    # Remove template IDs — only variant IDs go to caller
    for tid in template_ids:
        result.pop(tid, None)

    return result
```

- [ ] **Step 2: Run existing tests to confirm they still pass**

```bash
cd D:\NKLabs\Streamlit && python -m pytest tests/test_odoo_price_sync.py -v
```

Expected: all existing tests pass.

---

### Task 2: Fix `_diff_with_tracking()` — handle old_value=None as "new"

**Files:**
- Modify: `logic/odoo_price_sync.py:528-531`

**Problem:** When `old_value_float` is `None` (product's first price change, or tracking from creation), the function skips (`continue`) rather than treating it as a "new" change type.

- [ ] **Step 1: Change skip → emit "new" change**

Replace lines 528-531:

```python
            if old_price is None:
                # No old value in tracking → can't diff, treat as new
                continue
```

With:

```python
            if old_price is None:
                changes.append(PriceChange(
                    barcode=barcode, name=name,
                    old_price=None, new_price=new_price,
                    change_type="new",
                    changed_at=changed_at,
                ))
                continue
```

- [ ] **Step 2: Run tests**

```bash
cd D:\NKLabs\Streamlit && python -m pytest tests/test_odoo_price_sync.py -v
```

Expected: all existing tests pass.

---

### Task 3: Add `_detect_new_products_since()` + simplify `detect_changes_since()`

**Files:**
- Modify: `logic/odoo_price_sync.py`
- Add after line 547: new method `_detect_new_products_since()`
- Rewrite `detect_changes_since()` (lines 549-658)

**Note:** `_load_parquet_data()` is called inside `_detect_new_products_since()` for the "not already known" filter.

- [ ] **Step 1: Add `_detect_new_products_since()` method**

Add this method after `_diff_with_tracking()` (after line 547):

```python
    def _detect_new_products_since(self, start_date: date) -> List[PriceChange]:
        """Detect products created since start_date that are not yet in parquet.

        Queries product.product with create_date >= start_date, qty > 0,
        and barcode not empty. Filters out barcodes already known in parquet.
        """
        parquet_path = str(
            Path(__file__).parent.parent / "data" / "products.parquet"
        )
        parquet_data = self._load_parquet_data(parquet_path)

        try:
            products = self.conn_mgr.search_read(
                "product.product",
                domain=[
                    ("create_date", ">=", start_date.isoformat()),
                    ("qty_available", ">", 0),
                    ("barcode", "!=", False),
                ],
                fields=["id", "barcode", "name", "list_price", "product_tmpl_id"],
            )
        except Exception:
            return []

        changes: List[PriceChange] = []
        for p in products:
            barcode = str(p.get("barcode") or "").strip()
            name = str(p.get("name") or "").strip()
            if not barcode or not name:
                continue
            if barcode in parquet_data:
                continue  # already known, not "new" to us
            changes.append(PriceChange(
                barcode=barcode, name=name,
                old_price=None,
                new_price=float(p.get("list_price") or 0),
                change_type="new",
            ))
        return changes
```

- [ ] **Step 2: Rewrite `detect_changes_since()`**

Replace the entire method (lines 549-658) with:

```python
    def detect_changes_since(self, start_date: date) -> SyncResult:
        """Detect price changes since start_date.

        Primary: mail.tracking.value for list_price field —
        uses old_value_float as baseline, NOT parquet.

        New products: query product.product create_date >= start_date.

        Returns SyncResult with changes categorized as increase/decrease/new.
        """
        # 1. Mail tracking (primary)
        variant_fid, template_fid = self._get_price_field_ids()
        changed_map: Dict[int, tuple] = {}
        if variant_fid is not None or template_fid is not None:
            changed_map = self._query_mail_tracking(
                start_date, variant_fid, template_fid
            )

        # 2. Query tracked products from Odoo
        odoo_products: List[Dict] = []
        if changed_map:
            product_ids = list(changed_map.keys())
            try:
                odoo_products = self.conn_mgr.search_read(
                    "product.product",
                    domain=[
                        ("id", "in", product_ids),
                        ("qty_available", ">", 0),
                    ],
                    fields=["id", "barcode", "name", "list_price", "product_tmpl_id"],
                )
            except Exception:
                pass

        # 3. Diff tracking old_value_float → changes
        changes = self._diff_with_tracking(odoo_products, changed_map)

        # 4. New products (by create_date, not in parquet)
        new_changes = self._detect_new_products_since(start_date)
        changes.extend(new_changes)

        changes.sort(key=lambda c: _CHANGE_TYPE_ORDER.get(c.change_type, 99))

        # 5. Parquet metadata for SyncResult
        parquet_path = str(
            Path(__file__).parent.parent / "data" / "products.parquet"
        )
        parquet_data = self._load_parquet_data(parquet_path)

        result = SyncResult(
            timestamp=datetime.now().isoformat(),
            total_odoo_products=len(odoo_products) + len(new_changes),
            total_local_products=len(parquet_data),
            changes=changes,
        )
        self._save_sync_result(result)
        return result
```

Removed:
- `_query_write_date_fallback()` method (lines 463-476) — no longer called
- "All products" query for new detection (old lines 594-616) — replaced by `_detect_new_products_since()`
- Duplicate `changes.sort()` (old line 649)
- `write_date` fallback path

**Note:** Do NOT delete `_query_write_date_fallback()` — it's public API. Just stop calling it from `detect_changes_since()`.

- [ ] **Step 3: Run tests**

```bash
cd D:\NKLabs\Streamlit && python -m pytest tests/test_odoo_price_sync.py -v
```

Expected: `test_detect_changes_since_write_date_fallback` FAILS (removed fallback). Other tests pass.

---

### Task 4: Update tests

**Files:**
- Modify: `tests/test_odoo_price_sync.py`

- [ ] **Step 1: Add `_detect_new_products_since` mock to new-product tests**

In `test_detect_changes_since_new_product`, the test's mocks for `search_read.side_effect` must now include the `_detect_new_products_since` call (1 extra search_read for create_date query).

Replace the `search_read.side_effect` in `test_detect_changes_since_new_product` (lines 86-95):

```python
    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # 1. ir.model.fields product.product.list_price
        [{"id": 456}],  # 2. ir.model.fields product.template.list_price
        [],              # 3. mail.tracking.value — empty
        [                # 4. _detect_new_products_since: create_date query
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3500.0, "product_tmpl_id": [10]},
        ],
    ]
```

Also remove the old parquet mocks for this test — but keep the `os.path.exists` and `pd.read_parquet` mocks (needed by `_load_parquet_data` inside `_detect_new_products_since`).

In `test_detect_changes_since_no_parquet`, same pattern — `search_read.side_effect` needs the create_date query. Replace lines 109-118:

```python
    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # 1. ir.model.fields product.product.list_price
        [{"id": 456}],  # 2. ir.model.fields product.template.list_price
        [],              # 3. mail.tracking.value — empty
        [                # 4. _detect_new_products_since: create_date query
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3500.0, "product_tmpl_id": [10]},
        ],
    ]
```

- [ ] **Step 2: Update `test_detect_changes_since_empty_range`**

Similarly add the `_detect_new_products_since` search_read (empty result):

```python
    mock_conn.search_read.side_effect = [
        [{"id": 123}],
        [{"id": 456}],
        [],  # mail.tracking empty
        [],  # _detect_new_products_since — empty
    ]
```

- [ ] **Step 3: Update `test_detect_changes_since_write_date_fallback`**

This test validates removed behavior. Rename it to test the new `_detect_new_products_since` path instead. Replace the test function with:

```python
def test_detect_changes_since_new_via_create_date(service, mocker):
    """Product created in range, not in parquet → detected as 'new'."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=True)
    import pandas as pd
    empty_df = pd.DataFrame(columns=["barcode", "het", "diskon"])
    mocker.patch("logic.odoo_price_sync.pd.read_parquet", return_value=empty_df)

    mock_conn.search_read.side_effect = [
        [{"id": 123}],          # 1. ir.model.fields product.product
        [{"id": 456}],          # 2. ir.model.fields product.template
        [],                      # 3. mail.tracking — empty
        [                        # 4. _detect_new_products_since hits
            {"id": 99, "barcode": "8889990001111", "name": "New Product",
             "list_price": 5000.0, "product_tmpl_id": [50]},
        ],
    ]

    result = service.detect_changes_since(start_date=date(2026, 6, 1))

    new = [c for c in result.changes if c.change_type == "new"]
    assert len(new) == 1
    assert new[0].barcode == "8889990001111"
    assert new[0].new_price == 5000.0
    assert new[0].old_price is None
```

- [ ] **Step 4: Run all tests**

```bash
cd D:\NKLabs\Streamlit && python -m pytest tests/test_odoo_price_sync.py -v
```

Expected: ALL 6 tests pass.

---

### Task 5: Update `_generate_pdf()` to use PriceTagService

**Files:**
- Modify: `ui/pages/price_sync.py:64-77`

**Problem:** Current `_generate_pdf()` only uses `c.new_price` as `het` and sets `diskon=None`. Should use `PriceTagService.lookup_product()` to get current price + discount from local DB.

- [ ] **Step 1: Replace `_generate_pdf()` body**

Replace lines 64-77:

```python
def _generate_pdf(selected_changes: List[PriceChange]) -> bytes:
    items = []
    for c in selected_changes:
        items.append({
            "barcode": c.barcode,
            "name": c.name,
            "het": c.new_price,
            "diskon": None,
        })
    if not items:
        return b""
    service = _get_price_tag_service()
    return service.generate_pdf(items, size_preset="standard")
```

With:

```python
def _generate_pdf(selected_changes: List[PriceChange]) -> bytes:
    items = []
    tag_service = _get_price_tag_service()
    for c in selected_changes:
        local = tag_service.lookup_product(c.barcode)
        items.append({
            "barcode": c.barcode,
            "name": c.name,
            "het": local["het"] if local else c.new_price,
            "diskon": local.get("diskon") if local else None,
        })
    if not items:
        return b""
    return tag_service.generate_pdf(items, size_preset="standard")
```

- [ ] **Step 2: Run app to verify**

```bash
cd D:\NKLabs\Streamlit && streamlit run app.py
```

Navigate to Price Sync page, select date range, click Deteksi → confirm results appear. Select products, click Generate PDF → confirm no errors.
