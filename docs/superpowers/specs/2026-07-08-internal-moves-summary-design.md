# Internal Moves Summary by Contact - Design

## Objective
Replace "Recent Sales Orders" table on dashboard with summary of internal moves filtered by:
- Source location contains "GDG" (gudang)
- Destination location contains "STR" or "DISPLAY"
- Date filter: current day only (e.g., 2026-07-08)

Group results by contact showing record count and total product quantity.

## Architecture

### Query Layer (`odoo/stock_services.py`)
New function:
```python
@dataclass(frozen=True)
class InternalMoveSummary:
    partner_id: int
    partner_name: str
    record_count: int
    total_product_qty: float

def get_internal_moves_summary_by_day(*, target_date: date) -> List[InternalMoveSummary]
```

**Odoo Query:**
- Model: `stock.move`
- Domain:
  - `AND: ("location_id.complete_name", "ilike", "GDG")` (source gudang)
  - `OR: ("location_dest_id.complete_name", "ilike", "STR")`
  - `OR: ("location_dest_id.complete_name", "ilike", "DISPLAY")` (destination)
  - `AND: ("date", "=", target_date_str)`
- Fields: `["partner_id", "product_qty"]`

**Processing:**
1. Execute single `search_read`
2. Filter out rows without partner_id
3. Group by `partner_id` in Python
4. Aggregate: count + sum qty per partner
5. Return sorted list (by name)

### Dashboard Changes (`ui/pages/dashboard.py`)
1. Remove: Recent Sales Orders section (AgGrid + `_cached_recent_pos_orders`)
2. Add after metrics cards:
   - `st.subheader("📦 Internal Moves Hari Ini")`
   - `_cached_internal_moves_summary(target_date=today)`
   - Display DataFrame: Contact | Jumlah Record | Total Qty
   - Fallback: `st.info("Belum ada internal moves hari ini")` if no data

### Data Flow
```
render_dashboard_page()
  → _cached_internal_moves_summary(ttl=300)
    → get_internal_moves_summary_by_day(target_date=today_wib)
      → 1 RPC search_read on stock.move
      → Python groupby partner_id
      → List[InternalMoveSummary]
  → st.dataframe()
```

## Timezone
Use WIB (UTC+7) via `ZoneInfo("Asia/Jakarta")` to match existing dashboard conventions.

## Error Handling
- Wrap in try/except `OdooIntegrationError` → show `st.error()`
- Empty result → show `st.info()` not error

## Change Scope
**Files to modify:**
- `odoo/stock_services.py` — add dataclass + query function
- `ui/pages/dashboard.py` — remove POS orders table, add internal moves section
- `docs/superpowers/specs/2026-07-08-internal-moves-summary-design.md` — this doc

**Files to delete:** none

## Testing
Manual: run app, check table shows internal moves for current date. Verify empty state shows info message.
