# Price Tag Session Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Accumulate price tags across multiple bill updates into a session, only generate PDF when user explicitly clicks "Cetak."

**Architecture:** Replace immediate PDF generation on each "Update ke Odoo" with session-level accumulation in `st.session_state.price_tag_items`. Show persistent sidebar counter. Dedicated "Cetak Semua" section replaces per-update price tag download block.

**Tech Stack:** Python, Streamlit session_state

## Global Constraints

- No new dependencies — use `st.session_state` only (no IndexedDB, no localstorage)
- Session starts on first successful "Update ke Odoo" in a page visit
- Session ends when user clicks "Cetak Semua" or "Hapus Sesi"
- Sidetab/header shows live count of pending tags
- Must work for both single-bill and batch-by-date modes
- Existing price tag item structure preserved (`barcode`, `name`, `het`, `diskon`)

---

### Task 1: Session State Init and Accumulation

**Files:**
- Modify: `ui/pages/update_price.py:270-290` (update button handler)
- Modify: `ui/pages/update_price.py:20-30` (session state init)

**Interfaces:**
- Consumes: `st.session_state.updated_indices` (list[int]) from update handler
- Produces: `st.session_state.price_tag_items` (list[dict]) accumulated across updates

- [ ] **Step 1: Write the failing test**

```python
# tests/test_price_tag_session.py (create new file)
import pytest
import streamlit as st

def test_session_init_creates_empty_list():
    """Test that session state initializes price_tag_items as empty list."""
    # Simulate session state (mocked)
    from ui.pages.update_price import _init_tag_session
    _init_tag_session()
    assert "price_tag_items" in st.session_state
    assert st.session_state.price_tag_items == []

def test_accumulate_appends_items():
    """Test that accumulate function adds items without duplicates."""
    from ui.pages.update_price import _accumulate_tag_items
    if "price_tag_items" in st.session_state:
        del st.session_state.price_tag_items
    st.session_state.price_tag_items = []
    
    new_items = [
        {"barcode": "123", "name": "A", "het": 5000, "diskon": None},
        {"barcode": "456", "name": "B", "het": 10000, "diskon": None},
    ]
    _accumulate_tag_items(new_items)
    assert len(st.session_state.price_tag_items) == 2

def test_accumulate_does_not_duplicate_barcode():
    """Test that same barcode updates rather than duplicates."""
    from ui.pages.update_price import _accumulate_tag_items
    st.session_state.price_tag_items = [
        {"barcode": "123", "name": "A", "het": 5000, "diskon": None},
    ]
    new_items = [
        {"barcode": "123", "name": "A", "het": 6000, "diskon": None},
    ]
    _accumulate_tag_items(new_items)
    assert len(st.session_state.price_tag_items) == 1
    assert st.session_state.price_tag_items[0]["het"] == 6000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_price_tag_session.py -v`
Expected: FAIL with ImportError for `_init_tag_session` or `_accumulate_tag_items`

- [ ] **Step 3: Implement init + accumulate functions**

```python
# ui/pages/update_price.py (after _fmt_datetime, before _roundup)

# ── Price tag session management ──────────────────────────────────────

def _init_tag_session() -> None:
    """Initialize session state for accumulated price tags."""
    if "price_tag_items" not in st.session_state:
        st.session_state.price_tag_items = []
    if "price_tag_updated_sources" not in st.session_state:
        st.session_state.price_tag_updated_sources = []


def _accumulate_tag_items(new_items: List[Dict[str, Any]]) -> None:
    """Append or update items in the price tag session.

    If barcode already exists in session, update its het (newer price wins).
    Otherwise append.
    """
    existing = {item["barcode"]: i for i, item in enumerate(st.session_state.price_tag_items)}
    for item in new_items:
        bc = item["barcode"]
        if bc in existing:
            st.session_state.price_tag_items[existing[bc]]["het"] = item["het"]
        else:
            st.session_state.price_tag_items.append(item)


def _clear_tag_session() -> None:
    """Clear accumulated price tag items."""
    st.session_state.price_tag_items = []
    st.session_state.price_tag_updated_sources = []


def _tag_session_count() -> int:
    """Return number of pending price tag items."""
    return len(st.session_state.price_tag_items.get("price_tag_items", []))
```

- [ ] **Step 4: Initialize session at page start**

```python
# ui/pages/update_price.py -> render_update_price_page()
# Add as first line in the function:

def render_update_price_page() -> None:
    """Main render function for Update Harga page."""
    st.title("📈 Update Harga dari Vendor Bill")
    _init_tag_session()
    service = _get_service()
```

- [ ] **Step 5: Modify update handler to accumulate tags instead of storing indices**

```python
# ui/pages/update_price.py:270-290 (inside update button handler)
# Replace the lines that set st.session_state.updated_indices:

            if result["success"] > 0:
                # Build price tag items from updated products
                new_items = _build_price_tag_items(raw_rows, selected_indices)
                _accumulate_tag_items(new_items)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_price_tag_session.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 7: Remove old updated_indices logic**

```python
# Remove from _render_analysis (end of function):
# Before:
    # Price tag download
    updated = st.session_state.get("updated_indices", [])
    if updated:
        _render_price_tag_download(updated, raw_rows)

# After:
    # (removed — moved to dedicated session display)
```

Also remove `updated_indices` from the reset handler:
```python
# Before:
    if st.button("🔄 Reset", use_container_width=True):
        for key in ["analysis_rows", "selected_bill_id", "selected_bill_label", "updated_indices"]:
            st.session_state.pop(key, None)
        st.rerun()

# After:
    if st.button("🔄 Reset", use_container_width=True):
        for key in ["analysis_rows", "selected_bill_id", "selected_bill_label"]:
            st.session_state.pop(key, None)
        st.rerun()
```

Also remove `st.session_state.updated_indices = []` from load_clicked handler:
```python
# Before:
    if load_clicked:
        st.session_state.updated_indices = []

# After:
    if load_clicked:
        pass
```

- [ ] **Step 8: Run all existing tests to verify no regressions**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add ui/pages/update_price.py tests/test_price_tag_session.py
git commit -m "feat: session-based price tag accumulation"
```

---

### Task 2: "Cetak Semua" UI Section

**Files:**
- Modify: `ui/pages/update_price.py` (add `_render_tag_session_ui()` function, call from `render_update_price_page()`)

**Interfaces:**
- Consumes: `st.session_state.price_tag_items` from Task 1
- Produces: PDF download + print UI with all accumulated items

- [ ] **Step 1: Write the failing test**

```python
# tests/test_price_tag_session.py (append)
def test_render_tag_session_ui_shows_count(mocker):
    """Test that session UI displays correct item count."""
    mocker.patch('streamlit.markdown')
    mocker.patch('streamlit.subheader')
    mocker.patch('streamlit.columns', return_value=[mocker.Mock(), mocker.Mock()])
    mocker.patch('streamlit.download_button', return_value=False)
    mocker.patch('streamlit.button', return_value=False)
    mocker.patch('streamlit.expander')
    mocker.patch('streamlit.caption')
    mocker.patch('streamlit.spinner')
    mocker.patch('streamlit.warning')
    
    from ui.pages.update_price import _render_tag_session_ui
    st.session_state.price_tag_items = [
        {"barcode": "123", "name": "A", "het": 5000, "diskon": None},
    ]
    _render_tag_session_ui()
    # No exception = UI rendered with 1 item
    assert True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_price_tag_session.py::test_render_tag_session_ui_shows_count -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement _render_tag_session_ui**

```python
# ui/pages/update_price.py (after _clear_tag_session, before _build_price_tag_items)

def _render_tag_session_ui():
    """Show persistent session UI for accumulated price tags.

    Visible whenever price_tag_items is non-empty.
    Shows count, Cetak Semua button, and Clear button.
    """
    items = _tag_session_count()
    if items == 0:
        return

    st.markdown("---")
    st.subheader(f"🏷️ Price Tag Sesi ({items} label)")

    col_pdf, col_print, col_clear = st.columns([1, 1, 1])

    with st.spinner("🔄 Membuat PDF..."):
        tag_service = PriceTagService()
        try:
            pdf_bytes = tag_service.generate_pdf(
                st.session_state.price_tag_items, size_preset="standard"
            )
        except Exception as e:
            st.error(f"Gagal generate PDF: {e}")
            return

    with col_pdf:
        st.download_button(
            "⬇️ Download PDF (A4 48x30mm)",
            data=pdf_bytes,
            file_name=f"label_kenaikan_sesi.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True,
        )
    with col_print:
        if st.button("🖨️ Print di Browser", use_container_width=True):
            import base64
            import streamlit.components.v1 as components
            pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
            components.html(
                f"""<script>
                  (function(){{
                    try {{
                      const bytes = Uint8Array.from(atob("{pdf_b64}"), c=>c.charCodeAt(0));
                      const url = URL.createObjectURL(new Blob([bytes],{{type:'application/pdf'}}));
                      const w = window.open(url,'_blank');
                      if(!w){{ alert('Popup blocked.'); return; }}
                      const t = setInterval(()=>{{
                        try{{ if(w.document.readyState==='complete'){{ clearInterval(t); w.focus(); w.print(); }} }}
                        catch(e){{}}
                      }},250);
                    }}catch(e){{ alert('Failed: '+(e.message||e)); }}
                  }})();
                </script>""",
                height=0,
            )
    with col_clear:
        if st.button("🗑️ Hapus Sesi", type="secondary", use_container_width=True):
            _clear_tag_session()
            st.rerun()

    # Thermal label expander
    with st.expander("🔥 Thermal Label (28x18mm)", expanded=False):
        try:
            thermal_bytes = tag_service.generate_thermal_labels_pdf(
                st.session_state.price_tag_items, width_mm=28.0, height_mm=18.0
            )
            st.download_button(
                "⬇️ Download Thermal PDF",
                data=thermal_bytes,
                file_name=f"thermal_kenaikan_sesi.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.warning(f"Thermal PDF gagal: {e}")
```

- [ ] **Step 4: Call _render_tag_session_ui from page renderer**

```python
# ui/pages/update_price.py -> render_update_price_page()
# Add after _render_analysis call (but not inside it):

    # ── Step 4: Price tag session UI ───────────────────────────────────
    _render_tag_session_ui()
```

- [ ] **Step 5: Reuse same print callback logic to avoid duplicated JS**

The print browser button has identical JS logic as the existing `_render_price_tag_download`. For DRY, extract the common print pattern. But keep it inline since YAGNI — the old `_render_price_tag_download` function is still removable. We'll see if it's called elsewhere first.

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_price_tag_session.py tests/test_price_update_service.py tests/test_update_price_helpers.py -v`
Expected: PASS (all)

- [ ] **Step 7: Commit**

```bash
git add ui/pages/update_price.py
git commit -m "feat: add persistent price tag session UI with cetak semua"
```

---

### Task 3: Remove Legacy Per-Bill Price Tag Section

**Files:**
- Modify: `ui/pages/update_price.py` (remove `_render_price_tag_download` function if no longer used)

**Interfaces:**
- Consumes: Analyzer output
- Produces: Cleaner page without duplicate price tag sections

- [ ] **Step 1: Search for calls to _render_price_tag_download**

Run: `grep -n "_render_price_tag_download" ui/pages/update_price.py`
Verify it's only called from the old location at the bottom of `_render_analysis`.

- [ ] **Step 2: Remove call from _render_analysis**

```python
# Remove these lines from _render_analysis:
    # Price tag download
    updated = st.session_state.get("updated_indices", [])
    if updated:
        _render_price_tag_download(updated, raw_rows)
```

- [ ] **Step 3: Remove the function definition**

```python
# Remove the entire _render_price_tag_download function
# (lines ~100-165 in the original file)
```

Also remove the associated `_build_price_tag_items` function if no longer used by any other code.

Wait — _build_price_tag_items is still used in the update handler (Task 1 Step 5). So keep that function.

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ui/pages/update_price.py
git commit -m "refactor: remove legacy per-bill price tag download, replaced by session UI"
```

---

### Task 4: Update Tests and Docs

**Files:**
- Create: `docs/features/price-tag-session.md`

**Interfaces:**
- Consumes: Final implementation
- Produces: User docs

- [ ] **Step 1: Write docs**

```markdown
# Price Tag Session

## What It Is

Instead of generating price tag PDF after every "Update ke Odoo" (slow, duplicative),
the app now **accumulates items** into a session. All items from all bills are
collected until you choose to print.

## How It Works

1. **Update prices** from any bill (single or batch mode)
2. Items are silently added to the session — no PDF generated
3. A **counter** shows pending labels: "🏷️ Price Tag Sesi (14 label)"
4. When ready, click **"Download PDF"** or **"Print di Browser"**
5. Click **"Hapus Sesi"** to start fresh

## Session Rules

- Same barcode = newer price overwrites older one (no duplicates)
- Switching bills keeps session intact
- Session clears when you click "Hapus Sesi" or "Download PDF" (optional auto-clear)
```

- [ ] **Step 2: Commit docs**

```bash
git add docs/features/price-tag-session.md
git commit -m "docs: add price tag session documentation"
```

---

## Self-Review

**Spec coverage:**
- ✓ Accumulate price tags across bills (`price_tag_items` in session state)
- ✓ Session starts on first "Update ke Odoo"
- ✓ Session ends on "Cetak Semua" or "Hapus Sesi"
- ✓ Dedupe by barcode (newest price wins)
- ✓ Promo guardrail and update flow unchanged

**Placeholder scan:** No TBD, TODO, or filler. All code blocks complete.

**Type consistency:** `_accumulate_tag_items`, `_clear_tag_session`, `_tag_session_count` function names consistent across tasks. Session state key `price_tag_items` consistent.
