# Mulai Sesi — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the manual "Update harga" button with "Mulai Sesi" that syncs live Odoo prices to parquet (products with qty_available > 0 only), hiding the price tag UI behind a session gate.

**Architecture:** Two independent changes: (1) new `sync_from_odoo()` method on `PriceTagService` queries Odoo in 2 batch RPCs and writes to parquet; (2) UI in `PriceTagPage` guards content behind a "Mulai Sesi" button, removes the old manual update button.

**Tech Stack:** Odoo RPC (`connection_manager.search_read`), pandas, parquet (zstd), Streamlit.

## Global Constraints

- Only query products where `qty_available > 0`
- `het` = `list_price` from `product.product`
- `diskon` = `fixed_price` from `product.pricelist.item` (only if > 0, else null)
- Must call `self._load_parquet_to_memory()` after write to refresh cache
- UI must block all price tag content until session starts
- Removal of old "🔄 Update harga" button and its associated logic

---

## File Map

| File | Change | Responsibility |
|------|--------|----------------|
| `logic/price_tag_service.py` | Add method `sync_from_odoo()` | Query Odoo, write parquet, reload cache |
| `ui/pages/price_tag_generator.py` | Modify UI | Session gate, remove old button |

### Task N: PriceTagService.sync_from_odoo()

**Files:**
- Modify: `logic/price_tag_service.py` — add `sync_from_odoo()` method after line 136 (after `__init__`)
- Test: `tests/test_price_tag_sync.py` — new file

**Interfaces:**
- Consumes: `oc.connection_manager` global singleton
- Produces: `sync_from_odoo(self) -> Dict[str, int]` — returns `{"success": int, "skipped": int}`

**Context:** Need `from odoo.connection import connection_manager` at top of `price_tag_service.py`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for PriceTagService.sync_from_odoo()."""

import pytest
import pandas as pd
import os
from logic.price_tag_service import PriceTagService


@pytest.fixture
def service(tmp_path):
    """Build a PriceTagService that writes parquet to tmp_path."""
    parquet_path = str(tmp_path / "products.parquet")
    svc = PriceTagService(
        auto_convert=False,
        use_memory_cache=False,
    )
    svc.parquet_path = parquet_path
    svc._products = {}
    svc._suffix_index = {}
    return svc


def test_sync_from_odoo_success(service, mocker):
    """Mock Odoo responses and verify parquet file is written."""
    mock_conn = mocker.patch("logic.price_tag_service.connection_manager")

    # First RPC: product.product
    product_a = {
        "id": 1, "barcode": "8991001010049", "name": "Indomie Goreng",
        "list_price": 3500.0, "product_tmpl_id": [10, "Template A"],
    }
    product_b = {
        "id": 2, "barcode": "8886388100017", "name": "Mie Sedaap",
        "list_price": 3200.0, "product_tmpl_id": [20, "Template B"],
    }
    mock_conn.search_read.side_effect = [
        [product_a, product_b],        # first call: product.product
        [                              # second call: product.pricelist.item
            {"product_tmpl_id": [10], "fixed_price": 2800.0},
        ],
    ]

    result = service.sync_from_odoo()

    assert result["success"] == 2
    assert result["skipped"] == 0
    assert os.path.exists(service.parquet_path)

    # Verify parquet content
    df = pd.read_parquet(service.parquet_path)
    assert len(df) == 2
    assert df.iloc[0]["barcode"] == "8991001010049"
    assert df.iloc[0]["het"] == 3500.0
    assert df.iloc[0]["diskon"] == 2800.0
    assert df.iloc[1]["barcode"] == "8886388100017"
    assert df.iloc[1]["het"] == 3200.0
    assert pd.isna(df.iloc[1]["diskon"])  # no pricelist item → null


def test_sync_from_odoo_memory_cache_reloaded(service, mocker):
    """After sync, in-memory cache should contain the new products."""
    mock_conn = mocker.patch("logic.price_tag_service.connection_manager")
    mock_conn.search_read.side_effect = [
        [
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3500.0, "product_tmpl_id": [10, "Tpl"]},
        ],
        [],  # no pricelist items
    ]

    service.sync_from_odoo()

    # _load_parquet_to_memory is called → products accessible via lookup
    prod = service.lookup_product("8991001010049")
    assert prod is not None
    assert prod["name"] == "Indomie"
    assert prod["het"] == 3500.0


def test_sync_from_odoo_skips_missing_barcode(service, mocker):
    """Products without barcode are counted as skipped."""
    mock_conn = mocker.patch("logic.price_tag_service.connection_manager")
    mock_conn.search_read.side_effect = [
        [
            {"id": 1, "barcode": "", "name": "No Barcode",
             "list_price": 1000.0, "product_tmpl_id": [10, "Tpl"]},
            {"id": 2, "barcode": "8991001010049", "name": "Valid Product",
             "list_price": 3500.0, "product_tmpl_id": [20, "Tpl"]},
        ],
        [],
    ]

    result = service.sync_from_odoo()
    assert result["success"] == 1
    assert result["skipped"] == 1


def test_sync_from_odoo_empty_stock(service, mocker):
    """No products with qty > 0 → empty parquet, success=0."""
    mock_conn = mocker.patch("logic.price_tag_service.connection_manager")
    mock_conn.search_read.side_effect = [[], []]

    result = service.sync_from_odoo()

    assert result["success"] == 0
    assert result["skipped"] == 0
    assert os.path.exists(service.parquet_path)
    df = pd.read_parquet(service.parquet_path)
    assert len(df) == 0


def test_sync_from_odoo_connection_error(service, mocker):
    """Odoo connection failure → exception raised to caller."""
    from odoo.connection import OdooIntegrationError
    mock_conn = mocker.patch("logic.price_tag_service.connection_manager")
    mock_conn.search_read.side_effect = OdooIntegrationError("Odoo down")

    with pytest.raises(OdooIntegrationError):
        service.sync_from_odoo()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_price_tag_sync.py -v
```
Expected: FAIL — `sync_from_odoo` not defined.

- [ ] **Step 3: Write minimal implementation**

Add import at top of `logic/price_tag_service.py`:
```python
from odoo.connection import connection_manager
```

Append after `__init__` (after line 136) or before the Parquet/Excel management section (before line 173):

```python
# ------------------------------------------------------------------
# Odoo sync
# ------------------------------------------------------------------

def sync_from_odoo(self) -> Dict[str, int]:
    """Sync in-stock products from Odoo to local parquet file.

    Queries ``product.product`` where ``qty_available > 0``,
    joins ``product.pricelist.item.fixed_price`` as ``diskon``,
    writes to parquet, and reloads the in-memory cache.

    Returns:
        Dict with ``success`` (valid records written) and
        ``skipped`` (records missing barcode/name).
    """
    # 1. Fetch in-stock products
    products = connection_manager.search_read(
        "product.product",
        domain=[("qty_available", ">", 0)],
        fields=["barcode", "name", "list_price", "id", "product_tmpl_id"],
    )

    # 2. Fetch pricelist items (batch)
    tmpl_ids = list({
        p["product_tmpl_id"][0]
        for p in products
        if isinstance(p.get("product_tmpl_id"), (list, tuple)) and len(p["product_tmpl_id"]) > 0
    })
    pricelist_items: List[Dict[str, Any]] = []
    if tmpl_ids:
        pricelist_items = connection_manager.search_read(
            "product.pricelist.item",
            domain=[("product_tmpl_id", "in", tmpl_ids)],
            fields=["product_tmpl_id", "fixed_price"],
        )

    # Build fixed_price lookup: {tmpl_id: fixed_price}
    fp_map: Dict[int, float] = {}
    for pi in pricelist_items:
        ptid = pi.get("product_tmpl_id")
        fp = float(pi.get("fixed_price") or 0)
        if isinstance(ptid, (list, tuple)) and ptid and fp > 0:
            fp_map[int(ptid[0])] = fp

    # 3. Build records
    records: List[Dict[str, Any]] = []
    skipped = 0
    for p in products:
        barcode = str(p.get("barcode") or "").strip()
        name = str(p.get("name") or "").strip()
        if not barcode or not name:
            skipped += 1
            continue

        tmpl_id = None
        ptid = p.get("product_tmpl_id")
        if isinstance(ptid, (list, tuple)) and ptid:
            tmpl_id = int(ptid[0])

        diskon = fp_map.get(tmpl_id) if tmpl_id is not None else None

        records.append({
            "barcode": barcode,
            "name": name,
            "het": float(p.get("list_price") or 0),
            "diskon": diskon,
        })

    # 4. Write parquet
    df = pd.DataFrame(records)
    os.makedirs(os.path.dirname(self.parquet_path), exist_ok=True)
    df.to_parquet(self.parquet_path, index=False, compression="zstd")

    # 5. Reload cache
    self._load_parquet_to_memory()

    return {"success": len(records), "skipped": skipped}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_price_tag_sync.py -v
```
Expected: PASS (all 5 tests).

- [ ] **Step 5: Commit**

```bash
git add logic/price_tag_service.py tests/test_price_tag_sync.py
git commit -m "feat: add sync_from_odoo() to PriceTagService, tests"
```

---

### Task 2: UI — Session gate + remove manual update

**Files:**
- Modify: `ui/pages/price_tag_generator.py`

**Interfaces:**
- Consumes: `PriceTagService.sync_from_odoo()` (returns `Dict[str, int]`)
- Consumes: `st.session_state.price_tag_session_active` boolean

**What changes:**
1. Add `_render_session_start()` method
2. Add early-return gate in `render()` before any other content
3. Remove "🔄 Update harga" button block
4. Add "🏁 Akhiri Sesi" button at page bottom
5. Remove `service.load_database()` call from `get_price_tag_service()` — sync from Odoo replaces file loading

- [ ] **Step 1: Modify `get_price_tag_service()` — remove auto-load**

Change lines 22-30:

**Old:**
```python
@st.cache_resource(
    ttl=3600,
    hash_funcs={PriceTagService: lambda x: "v3"}
)
def get_price_tag_service() -> PriceTagService:
    """Get or create cached PriceTagService - expensive resource cached globally."""
    service = PriceTagService()
    service.load_database()
    return service
```

**New:**
```python
@st.cache_resource(
    ttl=3600,
    hash_funcs={PriceTagService: lambda x: "v4"}  # bump for new impl
)
def get_price_tag_service() -> PriceTagService:
    """Get or create cached PriceTagService - expensive resource cached globally."""
    service = PriceTagService(auto_convert=False, use_memory_cache=False)
    return service
```

Note: `auto_convert=False, use_memory_cache=False` — no Excel→parquet conversion at startup; memory loads fresh only after Odoo sync.

- [ ] **Step 2: Add `_render_session_start()` method to `PriceTagPage`**

Append after `__init__` (after `_init_session_state` method block, after line 135):

```python
def _render_session_start(self):
    """Render the session-start gate: big button + explanation."""
    st.markdown("---")
    st.markdown("### 🚀 Mulai Sesi Price Tag")
    st.caption(
        "Ambil data harga terbaru dari Odoo (hanya produk dengan stok > 0). "
        "Setelah sinkronisasi, Anda bisa mencari produk dan cetak label harga."
    )

    if st.button("Mulai Sesi", type="primary", use_container_width=True):
        with st.spinner("Mengambil data harga dari Odoo..."):
            try:
                result = self.service.sync_from_odoo()
                st.toast(
                    f"✅ {result['success']} produk berhasil di-sinkronisasi!",
                    icon="✅",
                )
                if result["skipped"] > 0:
                    st.toast(
                        f"⚠️ {result['skipped']} produk dilewati (barcode/nama kosong)",
                        icon="⚠️",
                    )
                st.session_state.price_tag_session_active = True
                self._valid_items_cache = None
                st.rerun()
            except Exception as e:
                st.error(f"Gagal sinkronisasi: {e}")
```

- [ ] **Step 3: Add `_render_end_session()` method**

Append after `_render_session_start()`:

```python
def _render_end_session(self):
    """Render session-end UI at the bottom of the page."""
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("🏁 Akhiri Sesi", use_container_width=True, type="secondary"):
            st.session_state.price_tag_session_active = False
            st.session_state.price_tag_pdf_ready = False
            st.session_state.price_tag_pdf_bytes = None
            st.session_state.price_tag_items_hash = None
            st.session_state.price_tag_pdf_size_preset = None
            self._valid_items_cache = None
            st.rerun()
```

- [ ] **Step 4: Modify `render()` — gate + remove update button**

**Current `render()` (lines 965-994):**
```python
def render(self):
    st.title("Price Tag Generator 😸")

    col1, col2 = st.columns([4, 1])
    with col1:
        st.caption(f"📦 Database: {self.service.product_count:,} harga sudah terupdate")
    with col2:
        if st.button("🔄 Update harga", type="secondary",
                     help="Force reload price data from file"):
            try:
                self.service._auto_convert_if_needed()
            except Exception:
                pass
            self.service._last_load_mtime = None
            self.service._load_parquet_to_memory()
            st.session_state.price_tag_pdf_ready = False
            st.session_state.price_tag_pdf_bytes = None
            st.session_state.price_tag_items_hash = None
            st.session_state.price_tag_pdf_size_preset = None
            st.success("Harga sudah terupdate!")

    tab_a4, tab_thermal = st.tabs(["A4 Price Tag", "Thermal 18x28mm"])
    ...
```

**New `render()`:**
```python
def render(self):
    st.title("Price Tag Generator 😸")

    # ── Session gate ──────────────────────────────────────────────
    if not st.session_state.get("price_tag_session_active", False):
        self._render_session_start()
        return  # Block everything until session starts

    st.caption(f"📦 Database: {self.service.product_count:,} harga tersedia")

    tab_a4, tab_thermal = st.tabs(["A4 Price Tag", "Thermal 18x28mm"])
    with tab_a4:
        self.render_database_section()
        self.render_items_table()
        self.render_pdf_section()
    with tab_thermal:
        self.render_thermal_section()

    self._process_pending_focus()
    self._render_end_session()
```

- [ ] **Step 5: Add session state default to `_init_session_state()`**

After line 95 (`defaults = {`), add:
```python
'price_tag_session_active': False,
```

- [ ] **Step 6: Test manually**

```bash
streamlit run app.py
```
1. Navigate to Price Tag page
2. Verify "Mulai Sesi" button is shown (no price tag UI visible)
3. Click "Mulai Sesi" — should show spinner, then toast success
4. After sync, should see normal price tag UI with product count
5. Verify "🏁 Akhiri Sesi" button at bottom
6. Click → should return to start gate
7. Refresh page → should be back at session gate (non-persistent)

- [ ] **Step 7: Commit**

```bash
git add ui/pages/price_tag_generator.py
git commit -m "feat: price tag session gate with Mulai Sesi, remove manual update"
```
