# Task 1 (7): Session State Init and Accumulation

**Files:**
- Modify: `ui/pages/update_price.py`

**Goal:** Replace immediate per-bill price tag PDF generation with session-level accumulation in `st.session_state.price_tag_items`.

## Changes

### 1. Add session helper functions

Add after `_fmt_datetime`, before `_roundup`:

```python
# ── Price tag session management ──────────────────────────────────────

def _init_tag_session() -> None:
    """Initialize session state for accumulated price tags."""
    if "price_tag_items" not in st.session_state:
        st.session_state.price_tag_items = []


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


def _tag_session_count() -> int:
    """Return number of pending price tag items."""
    return len(st.session_state.price_tag_items)
```

### 2. Init session at page start

In `render_update_price_page()`, add `_init_tag_session()` as first line.

### 3. Modify update button to accumulate tags

In the update button handler (inside `_render_analysis`), replace the line:
```python
st.session_state.updated_indices = selected_indices
```
with:
```python
new_items = _build_price_tag_items(raw_rows, selected_indices)
_accumulate_tag_items(new_items)
```

### 4. Remove updated_indices from reset

In reset button, remove `"updated_indices"` from the keys list.

### 5. Remove updated_indices from load_clicked

Remove `st.session_state.updated_indices = []` from load_clicked handler.

### 6. Create test file

```python
# tests/test_price_tag_session.py
import pytest
import streamlit as st
from ui.pages.update_price import _init_tag_session, _accumulate_tag_items, _clear_tag_session, _tag_session_count

def test_session_init():
    """Test session state initializes price_tag_items as empty list."""
    if "price_tag_items" in st.session_state:
        del st.session_state.price_tag_items
    _init_tag_session()
    assert "price_tag_items" in st.session_state
    assert st.session_state.price_tag_items == []

def test_accumulate_appends():
    """Test that accumulate adds new items."""
    st.session_state.price_tag_items = []
    _accumulate_tag_items([
        {"barcode": "123", "name": "A", "het": 5000, "diskon": None},
        {"barcode": "456", "name": "B", "het": 10000, "diskon": None},
    ])
    assert len(st.session_state.price_tag_items) == 2

def test_accumulate_updates_existing():
    """Test same barcode updates het, no duplicate."""
    st.session_state.price_tag_items = [
        {"barcode": "123", "name": "A", "het": 5000, "diskon": None},
    ]
    _accumulate_tag_items([
        {"barcode": "123", "name": "A", "het": 6000, "diskon": None},
    ])
    assert len(st.session_state.price_tag_items) == 1
    assert st.session_state.price_tag_items[0]["het"] == 6000

def test_tag_session_count():
    """Test count returns correct number."""
    st.session_state.price_tag_items = [
        {"barcode": "123", "name": "A", "het": 5000, "diskon": None},
        {"barcode": "456", "name": "B", "het": 10000, "diskon": None},
    ]
    assert _tag_session_count() == 2

def test_clear_tag_session():
    """Test clear empties the list."""
    st.session_state.price_tag_items = [{"barcode": "123", "name": "A", "het": 5000, "diskon": None}]
    _clear_tag_session()
    assert st.session_state.price_tag_items == []
```

### 7. Commit

```
git add ui/pages/update_price.py tests/test_price_tag_session.py
git commit -m "feat: session-based price tag accumulation"
```
