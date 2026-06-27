## Report: Task 2 - Timestamp Formatting Helper

### Implemented
- Added `_fmt_datetime(v: str | None) -> str` to `ui/pages/update_price.py`
  - Formats ISO 8601 "YYYY-MM-DD HH:MM:SS" -> "DD/MM/YYYY HH:MM"
  - Returns "-" for None, empty string, or invalid format
- Added `datetime` import to the file imports
- Created `tests/test_update_price_helpers.py` with 4 test cases

### TDD Evidence
- RED: `ImportError: cannot import name '_fmt_datetime' from 'ui.pages.update_price'` (expected - function not yet defined)
- GREEN: `4 passed in 7.30s` (all 4 test cases passing)

### Files Changed
- Modify: `ui/pages/update_price.py` (added import + function, +19 lines)
- Create: `tests/test_update_price_helpers.py` (+33 lines)

### Self-Review
- All 4 edge cases covered: valid timestamp, None, empty string, invalid format
- Uses `.get()` pattern consistent with codebase
- No over-engineering (YAGNI)
