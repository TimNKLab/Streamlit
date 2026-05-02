# Fix Price Sync History - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the `AttributeError: 'IndexedDBPriceSyncService' object has no attribute 'get_sync_history'` error when clicking "Lihat Histori" button in Price Sync page.

**Architecture:** Add `get_sync_history()` and `add_sync_to_history()` methods to `IndexedDBPriceSyncService` class. History is stored in Streamlit session state as a list of sync records. Each sync operation appends a new entry with timestamp, product counts, and change summary.

**Tech Stack:** Python, Streamlit, IndexedDB (via IndexedDBBridge), odoorpc for Odoo integration

---

## Problem Analysis

The error occurs because:
1. `IndexedDBPriceSyncService` class is missing the `get_sync_history()` method
2. The UI (`price_sync.py`) calls `sync_service.get_sync_history(limit=5)` at line 157
3. Streamlit's `@st.cache_resource` decorator caches the service instance, so even after adding the method, old cached instances don't have it

**Files to Modify:**
- `logic/indexeddb_price_sync.py` - Add missing methods to IndexedDBPriceSyncService class
- `ui/pages/price_sync.py` - Update UI to handle cache clearing and method calls properly

---

### Task 1: Add get_sync_history Method to IndexedDBPriceSyncService

**Files:**
- Modify: `logic/indexeddb_price_sync.py:354-365`

- [ ] **Step 1: Add the get_sync_history method**

Add this method after `get_sync_status()` and before `export_changes_to_excel()`:

```python
def get_sync_history(self, limit: int = 5) -> List[Dict[str, Any]]:
    """Get recent sync history from session state or return empty list."""
    import streamlit as st
    
    # Get history from session state if available
    history = st.session_state.get("price_sync_history", [])
    
    if not history:
        return []
    
    # Return most recent entries up to limit
    return history[-limit:]
```

- [ ] **Step 2: Commit the change**

```bash
git add logic/indexeddb_price_sync.py
git commit -m "feat: add get_sync_history method to IndexedDBPriceSyncService"
```

---

### Task 2: Add add_sync_to_history Method to IndexedDBPriceSyncService

**Files:**
- Modify: `logic/indexeddb_price_sync.py:367-387`

- [ ] **Step 1: Add the add_sync_to_history method**

Add this method after `get_sync_history()`:

```python
def add_sync_to_history(self, result: SyncResult) -> None:
    """Add a sync result to the history."""
    import streamlit as st
    from datetime import datetime
    
    if "price_sync_history" not in st.session_state:
        st.session_state.price_sync_history = []
    
    history_entry = {
        "timestamp": datetime.now().isoformat(),
        "total_changes": len(result.changes),
        "total_odoo_products": result.total_odoo_products,
        "total_local_products": getattr(result, 'total_local_products', 0),
        "change_summary": result.summary,
    }
    
    st.session_state.price_sync_history.append(history_entry)
    
    # Keep only last 20 entries to prevent memory bloat
    if len(st.session_state.price_sync_history) > 20:
        st.session_state.price_sync_history = st.session_state.price_sync_history[-20:]
```

- [ ] **Step 2: Commit the change**

```bash
git add logic/indexeddb_price_sync.py
git commit -m "feat: add add_sync_to_history method to IndexedDBPriceSyncService"
```

---

### Task 3: Update UI to Call add_sync_to_history After Sync

**Files:**
- Modify: `ui/pages/price_sync.py:144-155`

- [ ] **Step 1: Add call to add_sync_to_history after successful sync**

Find the "Update Harga" button handler and add the history call:

```python
if st.button("Update Harga", type="primary", use_container_width=True):
    with st.spinner("Mengambil harga dari Odoo…"):
        try:
            result = sync_service.detect_changes()
            st.session_state.last_sync_result = result
            # Add to history
            sync_service.add_sync_to_history(result)
            # Invalidate cached buckets whenever a new sync arrives
            st.session_state.pop("_change_buckets", None)
            st.success(f"Selesai! {len(result.changes)} perubahan ditemukan")
        except Exception as e:
            st.error(f"Sinkron gagal: {e}")
```

- [ ] **Step 2: Commit the change**

```bash
git add ui/pages/price_sync.py
git commit -m "feat: add sync to history after successful price sync"
```

---

### Task 4: Update Lihat Histori Button with Error Handling

**Files:**
- Modify: `ui/pages/price_sync.py:157-180`

- [ ] **Step 1: Add error handling to Lihat Histori button**

Replace the simple button handler with one that catches AttributeError and clears cache:

```python
with col2:
    if st.button("Lihat Histori", use_container_width=True):
        try:
            # Use the passed sync_service parameter directly
            history = sync_service.get_sync_history(limit=5)
            if history:
                with st.expander("Sinkron terbaru", expanded=True):
                    for h in reversed(history):
                        ts = h["timestamp"][:19].replace("T", " ")
                        total_changes = h.get("total_changes", 0)
                        odoo_count = h.get("total_odoo_products", 0)
                        local_count = h.get("total_local_products", 0)
                        st.caption(
                            f"{ts}: {total_changes} perubahan "
                            f"(Odoo: {odoo_count}, Local: {local_count})"
                        )
            else:
                st.info("Belum ada riwayat sinkronisasi")
        except AttributeError as e:
            # Method not found - clear cache and retry once
            _get_sync_service.clear()
            st.warning("Cache dibersihkan. Silakan klik 'Lihat Histori' lagi.")
        except Exception as e:
            st.error(f"Gagal memuat riwayat: {e}")
```

- [ ] **Step 2: Commit the change**

```bash
git add ui/pages/price_sync.py
git commit -m "fix: add error handling to Lihat Histori button with cache clearing"
```

---

### Task 5: Deploy and Test

**Files:**
- Test: Streamlit Cloud deployment

- [ ] **Step 1: Push all changes to git**

```bash
git push origin main
```

- [ ] **Step 2: Verify deployment on Streamlit Cloud**

1. Go to Streamlit Cloud dashboard
2. Check that the app redeploys successfully
3. Open the app in incognito mode
4. Navigate to Price Sync page
5. Click "Update Harga" to perform a sync
6. Click "Lihat Histori" to view history

- [ ] **Step 3: Test error recovery**

1. If error still occurs, click "Clear Cache" button
2. Refresh the page
3. Click "Lihat Histori" again - should work now

---

## Self-Review Checklist

**Spec coverage:**
- ✅ `get_sync_history()` method added to IndexedDBPriceSyncService
- ✅ `add_sync_to_history()` method added to IndexedDBPriceSyncService
- ✅ UI calls `add_sync_to_history()` after successful sync
- ✅ UI displays history with proper error handling
- ✅ Cache clearing on AttributeError for backward compatibility

**Placeholder scan:**
- ✅ No TBD/TODO placeholders
- ✅ All code shown in full
- ✅ Complete function definitions provided

**Type consistency:**
- ✅ `get_sync_history` returns `List[Dict[str, Any]]`
- ✅ `add_sync_to_history` takes `SyncResult` parameter
- ✅ History entries have consistent field names

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-02-fix-price-sync-history.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
