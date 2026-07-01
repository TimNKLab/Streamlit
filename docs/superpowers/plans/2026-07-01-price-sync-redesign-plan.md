# Price Sync Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace IndexedDB-based price sync with Odoo+parquet change detection using `mail.tracking.value` timestamps. Remove IndexedDB entirely.

**Architecture:** Extend existing `OdooPriceSyncService` with `detect_changes(start_date)` — queries `mail.tracking.value` for `list_price` field changes since start date, diffs against parquet, returns categorized changes (naik/turun/baru). Fallback to `write_date` when tracking unavailable.

**Tech Stack:** Odoo RPC (`connection_manager.search_read`), pandas, parquet, mail.tracking.value.

## Global Constraints

- Query `mail.tracking.value` with `field_id` for `product.product.list_price` only
- Fallback chain: mail tracking → write_date → exception
- `PriceChange` dataclass must include `changed_at` (ISO timestamp or None)
- Odoo query: `product.product` where `qty_available > 0`
- Parquet path: same as `PriceTagService.parquet_path` (`data/products.parquet`)
- Must NOT depend on IndexedDB (`indexeddb_bridge.py` / `indexeddb_price_sync.py`)
- Remove `utils/indexeddb_bridge.py` only after replacing its last usage in `price_tag_generator.py`

---

## File Map

| File | Task | Responsibility |
|------|------|----------------|
| `logic/odoo_price_sync.py` | 1 | Add `detect_changes(start_date)`, add `changed_at` field to `PriceChange` |
| `tests/test_odoo_price_sync.py` | 1 | Tests for new detection logic |
| `ui/pages/price_sync.py` | 2 | Rewrite UI: date range selector, call new service, show results |
| `logic/indexeddb_price_sync.py` | 3 | Delete entire file |
| `ui/pages/price_tag_generator.py` | 3 | Replace `IndexedDBBridge` usage with `PriceTagService.lookup_product()` |
| `utils/indexeddb_bridge.py` | 3 | Delete entire file |
| `tests/test_indexeddb_bridge.py` | 3 | Delete |

### Task 1: Add detect_changes() to OdooPriceSyncService

**Files:**
- Modify: `logic/odoo_price_sync.py`
- Test: `tests/test_odoo_price_sync.py` — new file

**Interfaces:**
- Consumes: `connection_manager` (global), `PriceTagService.parquet_path` convention (`data/products.parquet`)
- Produces: `detect_changes(self, start_date: date) -> SyncResult` where `SyncResult.changes` contains `PriceChange` items with `changed_at` field

**Changes to existing code:**
- Add `changed_at: Optional[str]` field to `PriceChange` dataclass
- Add `_get_price_field_id()` method (cached)
- Add `_query_mail_tracking(start_date, field_id)` method
- Add `_query_write_date_fallback(start_date)` method
- Add `detect_changes(start_date: date)` method

- [ ] **Step 1: Update `PriceChange` dataclass**

```python
@dataclass
class PriceChange:
    """Represents a price change for a product."""
    barcode: str
    name: str
    old_price: Optional[float]
    new_price: float
    change_type: str  # 'increase' | 'decrease' | 'new' | 'removed' | 'discount_change'
    changed_at: Optional[str] = None  # ISO timestamp from tracking/write_date
```

- [ ] **Step 2: Write failing tests**

Create `tests/test_odoo_price_sync.py`:

```python
"""Tests for OdooPriceSyncService.detect_changes()."""

import pytest
import os
from datetime import date, datetime
from logic.odoo_price_sync import OdooPriceSyncService, PriceChange, SyncResult


@pytest.fixture
def service(tmp_path):
    """Service that uses temp dir for local db path."""
    return OdooPriceSyncService()


def test_detect_changes_success(service, mocker):
    """Mock Odoo and parquet data, verify changes detected correctly."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mock_parquet = mocker.patch("logic.odoo_price_sync.pd.read_parquet")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=True)

    # Mock field_id lookup
    mock_conn.search_read.side_effect = [
        # 1. ir.model.fields for list_price
        [{"id": 123}],
        # 2. product.product (qty > 0)
        [
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3800.0, "product_tmpl_id": [10]},
            {"id": 2, "barcode": "8886388100017", "name": "Mie Sedaap",
             "list_price": 3200.0, "product_tmpl_id": [20]},
        ],
        # 3. mail.tracking.value
        [
            {"create_date": "2026-06-28 10:00:00", "mail_message_id": [100]},
        ],
        # 4. mail.message
        [
            {"id": 100, "res_id": 1, "model": "product.product"},
        ],
    ]

    # Old parquet data
    mock_parquet.return_value = mocker.patch("pandas.DataFrame")
    mock_parquet.return_value.set_index.return_value.to_dict.return_value = {
        "8991001010049": {"name": "Indomie", "het": 3500.0, "diskon": None},
        # Mie Sedaap not in old parquet → new product
    }

    result = service.detect_changes(start_date=date(2026, 6, 1))

    assert isinstance(result, SyncResult)
    assert len(result.changes) == 2

    # Change 1: price increase 3500 → 3800
    inc = [c for c in result.changes if c.change_type == "increase"]
    assert len(inc) == 1
    assert inc[0].barcode == "8991001010049"
    assert inc[0].old_price == 3500.0
    assert inc[0].new_price == 3800.0
    assert inc[0].changed_at == "2026-06-28 10:00:00"

    # Change 2: new product
    new = [c for c in result.changes if c.change_type == "new"]
    assert len(new) == 1
    assert new[0].barcode == "8886388100017"
    assert new[0].old_price is None
    assert new[0].new_price == 3200.0


def test_detect_changes_no_tracking_fallback(service, mocker):
    """When mail.tracking is empty, fallback to write_date."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mock_parquet = mocker.patch("logic.odoo_price_sync.pd.read_parquet")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=True)

    # ir.model.fields succeeds, but mail.tracking returns empty
    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # field_id
        [],             # mail.tracking.value (empty)
        [               # product.product (write_date fallback)
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3800.0, "product_tmpl_id": [10]},
        ],
    ]

    mock_parquet.return_value = mocker.patch("pandas.DataFrame")
    mock_parquet.return_value.set_index.return_value.to_dict.return_value = {
        "8991001010049": {"name": "Indomie", "het": 3500.0, "diskon": None},
    }

    result = service.detect_changes(start_date=date(2026, 6, 1))

    assert len(result.changes) == 1
    assert result.changes[0].barcode == "8991001010049"


def test_detect_changes_no_parquet(service, mocker):
    """No parquet file → all Odoo products are 'new'."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=False)

    mock_conn.search_read.side_effect = [
        [{"id": 123}],  # field_id
        [
            {"id": 1, "barcode": "8991001010049", "name": "Indomie",
             "list_price": 3500.0, "product_tmpl_id": [10]},
        ],
    ]

    result = service.detect_changes(start_date=date(2026, 6, 1))

    assert len(result.changes) == 1
    assert result.changes[0].change_type == "new"
    assert result.changes[0].barcode == "8991001010049"


def test_detect_changes_empty_range(service, mocker):
    """No products changed in range → empty result."""
    mock_conn = mocker.patch.object(service, "conn_mgr")
    mock_parquet = mocker.patch("logic.odoo_price_sync.pd.read_parquet")
    mocker.patch("logic.odoo_price_sync.os.path.exists", return_value=True)

    mock_conn.search_read.side_effect = [
        [{"id": 123}],
        [],  # no product.product changes in range
    ]

    mock_parquet.return_value = mocker.patch("pandas.DataFrame")
    mock_parquet.return_value.set_index.return_value.to_dict.return_value = {}

    result = service.detect_changes(start_date=date(2026, 6, 1))

    assert len(result.changes) == 0
```

- [ ] **Step 3: Run tests — expect FAIL**

```bash
cd D:\NKLabs\Streamlit && python -m pytest tests/test_odoo_price_sync.py -v
```

- [ ] **Step 4: Implement `detect_changes()` in `odoo_price_sync.py`**

Add import at top:
```python
from datetime import date, datetime
```

Update `PriceChange` to add `changed_at` field:
- Add `changed_at: Optional[str] = None` after `change_type` field

Add methods to `OdooPriceSyncService`:

```python
# ------------------------------------------------------------------
# Change detection via mail tracking
# ------------------------------------------------------------------

def _get_price_field_id(self) -> Optional[int]:
    """Cache field_id for product.product.list_price."""
    try:
        fields = self.conn_mgr.search_read(
            "ir.model.fields",
            domain=[("model", "=", "product.product"), ("name", "=", "list_price")],
            fields=["id"],
            limit=1,
        )
        return fields[0]["id"] if fields else None
    except Exception:
        return None

def _query_mail_tracking(
    self, start_date: date, field_id: int
) -> Dict[int, str]:
    """Query mail.tracking.value for list_price changes since start_date.

    Returns {product_id: create_date} for products with list_price changes.
    Returns empty dict if tracking unavailable.
    """
    try:
        trackings = self.conn_mgr.search_read(
            "mail.tracking.value",
            domain=[
                ("field_id", "=", field_id),
                ("create_date", ">=", start_date.isoformat()),
            ],
            fields=["create_date", "mail_message_id", "new_value_float"],
            order="create_date desc",
        )
    except Exception:
        return {}

    if not trackings:
        return {}

    # Resolve res_id via mail.message
    msg_ids = []
    for t in trackings:
        mid = t.get("mail_message_id")
        if isinstance(mid, (list, tuple)) and mid:
            msg_ids.append(mid[0])

    if not msg_ids:
        return {}

    try:
        msgs = self.conn_mgr.search_read(
            "mail.message",
            domain=[("id", "in", msg_ids)],
            fields=["id", "res_id", "model"],
        )
    except Exception:
        return {}

    # Build {product_id: last_changed_at}
    result: Dict[int, str] = {}
    msg_map = {m["id"]: m for m in msgs}
    for t in trackings:
        mid = t.get("mail_message_id")
        if isinstance(mid, (list, tuple)) and mid:
            mid = mid[0]
        msg = msg_map.get(mid)
        if not msg or msg.get("model") != "product.product":
            continue
        pid = msg["res_id"]
        if pid not in result:  # first occurrence = latest (ordered desc)
            result[pid] = t["create_date"]
    return result

def _query_write_date_fallback(self, start_date: date) -> List[Dict]:
    """Fallback: query product.product with write_date filter."""
    try:
        return self.conn_mgr.search_read(
            "product.product",
            domain=[
                ("qty_available", ">", 0),
                ("write_date", ">=", start_date.isoformat()),
            ],
            fields=["id", "barcode", "name", "list_price", "product_tmpl_id", "write_date"],
        )
    except Exception:
        return []

def _load_parquet_data(self, parquet_path: str) -> Dict[str, dict]:
    """Load parquet file into {barcode: {het, diskon}} dict."""
    if not os.path.exists(parquet_path):
        return {}
    try:
        import pandas as pd
        df = pd.read_parquet(parquet_path)
        if "barcode" not in df.columns:
            return {}
        df["barcode"] = df["barcode"].astype(str).str.strip()
        has_diskon = "diskon" in df.columns
        result = {}
        for _, row in df.iterrows():
            bc = row["barcode"]
            if not bc:
                continue
            result[bc] = {
                "het": float(row["het"]) if not pd.isna(row.get("het")) else None,
                "diskon": float(row["diskon"]) if has_diskon and not pd.isna(row.get("diskon")) else None,
            }
        return result
    except Exception:
        return {}

def _diff_with_parquet(
    self,
    odoo_products: List[Dict],
    parquet_data: Dict[str, dict],
    changed_map: Dict[int, str],
) -> List[PriceChange]:
    """Diff Odoo products vs parquet, return changes."""
    changes: List[PriceChange] = []

    for p in odoo_products:
        barcode = str(p.get("barcode") or "").strip()
        name = str(p.get("name") or "").strip()
        if not barcode or not name:
            continue

        new_price = float(p.get("list_price") or 0)
        pid = p["id"]
        old = parquet_data.get(barcode)

        if old is None:
            # New product
            changes.append(PriceChange(
                barcode=barcode, name=name,
                old_price=None, new_price=new_price,
                change_type="new",
                changed_at=changed_map.get(pid),
            ))
        else:
            old_price = old.get("het")
            if old_price is None:
                continue  # no baseline to compare
            if new_price > old_price:
                changes.append(PriceChange(
                    barcode=barcode, name=name,
                    old_price=old_price, new_price=new_price,
                    change_type="increase",
                    changed_at=changed_map.get(pid),
                ))
            elif new_price < old_price:
                changes.append(PriceChange(
                    barcode=barcode, name=name,
                    old_price=old_price, new_price=new_price,
                    change_type="decrease",
                    changed_at=changed_map.get(pid),
                ))

    return changes

def detect_changes(self, start_date: date) -> SyncResult:
    """Detect price changes since start_date.

    Primary: mail.tracking.value for list_price field.
    Fallback: write_date on product.product.

    Returns SyncResult with changes categorized as increase/decrease/new.
    """
    # 1. Load parquet baseline
    parquet_path = str(
        Path(__file__).parent.parent / "data" / "products.parquet"
    )
    parquet_data = self._load_parquet_data(parquet_path)

    # 2. Try primary: mail tracking
    field_id = self._get_price_field_id()
    changed_map: Dict[int, str] = {}

    if field_id is not None:
        changed_map = self._query_mail_tracking(start_date, field_id)

    # 3. Query Odoo products — filter by changed_map or fallback to write_date
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

    if not odoo_products:
        # Fallback: write_date
        odoo_products = self._query_write_date_fallback(start_date)
        if changed_map is None or (not changed_map and not odoo_products):
            # Also fetch unchanged products to detect "new" that have no tracking
            try:
                all_products = self.conn_mgr.search_read(
                    "product.product",
                    domain=[("qty_available", ">", 0)],
                    fields=["id", "barcode", "name", "list_price", "product_tmpl_id"],
                )
                new_products = [p for p in all_products if p["id"] not in {pp["id"] for pp in odoo_products}]
                odoo_products = odoo_products + new_products
            except Exception:
                pass

    # 4. Diff
    changes = self._diff_with_parquet(odoo_products, parquet_data, changed_map)

    changes.sort(key=lambda c: _CHANGE_TYPE_ORDER.get(c.change_type, 99))

    result = SyncResult(
        timestamp=datetime.now().isoformat(),
        total_odoo_products=len(odoo_products),
        total_local_products=len(parquet_data),
        changes=changes,
    )
    self._save_sync_result(result)
    return result
```

- [ ] **Step 5: Run tests — expect PASS**

```bash
cd D:\NKLabs\Streamlit && python -m pytest tests/test_odoo_price_sync.py -v
```

- [ ] **Step 6: Run existing tests — verify no regressions**

```bash
cd D:\NKLabs\Streamlit && python -m pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add logic/odoo_price_sync.py tests/test_odoo_price_sync.py
git commit -m "feat: add detect_changes(start_date) to OdooPriceSyncService"
```

### Task 2: Rewrite price_sync.py UI

**Files:**
- Modify: `ui/pages/price_sync.py` — rewrite to use `OdooPriceSyncService.detect_changes()`

**Interfaces:**
- Consumes: `OdooPriceSyncService.detect_changes(start_date)` → `SyncResult`
- Produces: Rendered Streamlit UI with date selector + changes table

**What changes:**
- Remove all `IndexedDBPriceSyncService` imports/references
- Add date range selector (3/7/14/30 hari)
- Call `OdooPriceSyncService.detect_changes(start_date)`
- Display results table with change type coloring
- Keep Export Excel functionality
- Keep Generate PDF functionality (using `PriceTagService`)

- [ ] **Step 1: Write the new `price_sync.py`**

```python
"""Price Sync — detect price changes from Odoo via mail tracking."""

import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from typing import List

from logic.odoo_price_sync import OdooPriceSyncService, PriceChange, SyncResult
from logic.price_tag_service import PriceTagService


@st.cache_resource(ttl=3600)
def _get_sync_service() -> OdooPriceSyncService:
    return OdooPriceSyncService()


@st.cache_resource(ttl=3600)
def _get_price_tag_service() -> PriceTagService:
    return PriceTagService(auto_convert=False, use_memory_cache=False)


_CHANGE_EMOJI = {
    "increase": "📈",
    "decrease": "📉",
    "new": "🆕",
    "removed": "🗑️",
    "discount_change": "🏷️",
}

_COLUMN_CONFIG = {
    "Type": st.column_config.TextColumn("", disabled=True, width="small"),
    "Barcode": st.column_config.TextColumn("Barcode", disabled=True, width="small"),
    "Nama Produk": st.column_config.TextColumn("Nama Produk", disabled=True, width="large"),
    "Harga Lama": st.column_config.TextColumn("Harga Lama", disabled=True),
    "Harga Baru": st.column_config.TextColumn("Harga Baru", disabled=True),
    "Selisih": st.column_config.TextColumn("Selisih", disabled=True),
    "Terakhir": st.column_config.TextColumn("Terakhir Update", disabled=True, width="medium"),
    "Select": st.column_config.CheckboxColumn("Print", default=True),
}


def _build_dataframe(changes: List[PriceChange]) -> pd.DataFrame:
    rows = []
    for c in changes:
        emoji = _CHANGE_EMOJI.get(c.change_type, "❓")
        old = f"Rp {c.old_price:,.0f}" if c.old_price else "-"
        new = f"Rp {c.new_price:,.0f}"
        diff = f"Rp {c.price_diff():,.0f}" if c.old_price else "-"
        changed_at = str(c.changed_at)[:19] if c.changed_at else "-"
        rows.append({
            "Type": f"{emoji} {c.change_type.title()}",
            "Barcode": c.barcode,
            "Nama Produk": c.name,
            "Harga Lama": old,
            "Harga Baru": new,
            "Selisih": diff,
            "Terakhir": changed_at,
            "Select": True,
            "_change": c,
        })
    return pd.DataFrame(rows)


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


def render_price_sync_page() -> None:
    st.title("📊 Price Sync — Deteksi Perubahan Harga")
    st.caption("Deteksi produk dengan perubahan harga atau produk baru dalam rentang waktu tertentu.")

    service = _get_sync_service()

    # Date range selector
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        range_option = st.selectbox(
            "Rentang Waktu",
            options=[3, 7, 14, 30],
            format_func=lambda x: f"{x} Hari Terakhir",
            index=1,  # default 7 hari
            key="sync_range",
        )
    with col2:
        if range_option == 30:
            st.warning("⚠️ Range 30 hari mungkin membutuhkan waktu lebih lama")
        start_date = date.today() - timedelta(days=range_option)
        st.caption(f"Perubahan sejak {start_date.isoformat()}")
    with col3:
        st.markdown("###")
        detect_clicked = st.button("🔍 Deteksi", type="primary", use_container_width=True)

    if detect_clicked:
        with st.spinner("Mendeteksi perubahan harga..."):
            try:
                result = service.detect_changes(start_date)
                st.session_state.sync_result = result
                st.session_state.sync_start_date = start_date
            except Exception as e:
                st.error(f"Gagal mendeteksi perubahan: {e}")
                st.session_state.sync_result = None

    result: SyncResult | None = st.session_state.get("sync_result")
    if result is None:
        st.info("👆 Pilih rentang waktu dan klik 'Deteksi' untuk memulai")
        return

    # Summary metrics
    inc = len(result.get_by_type("increase"))
    dec = len(result.get_by_type("decrease"))
    new = len(result.get_by_type("new"))
    total = len(result.changes)

    cols = st.columns(4)
    cols[0].metric("Total Perubahan", total)
    cols[1].metric("📈 Naik", inc)
    cols[2].metric("📉 Turun", dec)
    cols[3].metric("🆕 Baru", new)

    if total == 0:
        st.success(f"✅ Tidak ada perubahan harga sejak {st.session_state.sync_start_date.isoformat()}")
        return

    # Results table
    df = _build_dataframe(result.changes)

    edited_df = st.data_editor(
        df.drop(columns=["_change"]),
        column_config=_COLUMN_CONFIG,
        hide_index=True,
        use_container_width=True,
        key="sync_editor",
    )

    # Action buttons
    selected_indices = edited_df[edited_df["Select"]].index.tolist()
    selected = [result.changes[i] for i in selected_indices]

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🖨️ Generate PDF Price Tag", type="primary", use_container_width=True,
                     disabled=not selected):
            pdf_bytes = _generate_pdf(selected)
            if pdf_bytes:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    "⬇️ Download PDF",
                    data=pdf_bytes,
                    file_name=f"price_changes_{timestamp}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
                st.success(f"✅ {len(selected)} label siap cetak!")
            else:
                st.error("Gagal membuat PDF")

    with col2:
        if st.button("📊 Export Excel", use_container_width=True, disabled=not selected):
            export_df = pd.DataFrame([{
                "Barcode": c.barcode,
                "Nama": c.name,
                "Tipe": c.change_type,
                "Harga Lama": c.old_price,
                "Harga Baru": c.new_price,
                "Selisih": c.price_diff(),
                "Terakhir Update": str(c.changed_at)[:19] if c.changed_at else "",
            } for c in selected])
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_path = f"price_changes_{timestamp}.xlsx"
            export_df.to_excel(export_path, index=False, sheet_name="Price Changes")
            with open(export_path, "rb") as f:
                st.download_button(
                    "⬇️ Download Excel",
                    data=f,
                    file_name=export_path,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    with col3:
        if st.button("🗑️ Hapus Hasil", use_container_width=True):
            st.session_state.sync_result = None
            st.rerun()


def render() -> None:
    render_price_sync_page()
```

- [ ] **Step 2: Verify import consistency**

Check that `price_sync.py` no longer imports from `indexeddb_price_sync` or `indexeddb_bridge`.

- [ ] **Step 3: Run existing tests — no regressions**

```bash
cd D:\NKLabs\Streamlit && python -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add ui/pages/price_sync.py
git commit -m "feat: rewrite price sync UI with Odoo mail tracking detection"
```

### Task 3: Remove IndexedDB dependencies

**Files:**
- Delete: `logic/indexeddb_price_sync.py`
- Delete: `utils/indexeddb_bridge.py`
- Delete: `tests/test_indexeddb_bridge.py`
- Modify: `ui/pages/price_tag_generator.py` — replace `IndexedDBBridge` usage

- [ ] **Step 1: Replace `IndexedDBBridge` in `price_tag_generator.py`**

The only remaining usage is in `_resolve_het_from_indexeddb()` method used by thermal labels. Replace with `PriceTagService.lookup_product()`:

```python
def _resolve_het_from_price_tag(self, barcode: str, fallback_het) -> float | None:
    """Resolve HET via PriceTagService (replaces IndexedDBBridge)."""
    try:
        product = self.service.lookup_product(barcode)
        if product and product.get("het") is not None:
            return float(product["het"])
    except Exception:
        pass
    try:
        return float(fallback_het) if fallback_het is not None else None
    except (TypeError, ValueError):
        return None
```

And update the caller in `_build_thermal_items`:
- Remove `IndexedDBBridge()` instantiation
- Change `self._resolve_het_from_indexeddb(indexeddb, ...)` → `self._resolve_het_from_price_tag(...)`

Remove `from utils.indexeddb_bridge import IndexedDBBridge` import.

- [ ] **Step 2: Delete files**

Verify nothing imports from these files, then:

```bash
git rm logic/indexeddb_price_sync.py
git rm utils/indexeddb_bridge.py
git rm tests/test_indexeddb_bridge.py
```

- [ ] **Step 3: Run all tests — no regressions**

```bash
cd D:\NKLabs\Streamlit && python -m pytest tests/ -v
```

Expected: test_indexeddb_bridge tests removed. All other tests pass.

- [ ] **Step 4: Commit**

```bash
git add ui/pages/price_tag_generator.py
git rm logic/indexeddb_price_sync.py utils/indexeddb_bridge.py tests/test_indexeddb_bridge.py
git commit -m "feat: remove IndexedDB dependencies, replace with PriceTagService lookup"
```
