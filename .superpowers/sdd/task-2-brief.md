# Task 2: Add Timestamp Formatting Helper

**Files:**
- Modify: `ui/pages/update_price.py:15-30`

**Interfaces:**
- Consumes: ISO 8601 timestamp string from Odoo (e.g., "2026-06-25 14:30:00")
- Produces: `_fmt_datetime(v: str | None) -> str` function returning formatted string "25/06/2026 14:30" or "-"

## Steps

### Step 1: Write the failing test

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

### Step 2: Run test to verify it fails

Run: `pytest tests/test_update_price_helpers.py::test_fmt_datetime_with_valid_timestamp -v`
Expected: FAIL with ImportError or function not defined

### Step 3: Implement _fmt_datetime helper

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

### Step 4: Run test to verify it passes

Run: `pytest tests/test_update_price_helpers.py -v`
Expected: PASS (all 4 tests)

### Step 5: Commit

```bash
git add ui/pages/update_price.py tests/test_update_price_helpers.py
git commit -m "feat: add timestamp formatter for Indonesian locale"
```
