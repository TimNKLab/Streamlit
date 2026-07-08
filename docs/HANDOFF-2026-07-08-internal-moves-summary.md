# Handoff: Internal Moves Summary on Dashboard

## What
Hilangkan table "Recent Sales Orders" di dashboard → ganti dengan "Internal Moves Hari Ini" — laporan per-contact untuk stock moves dengan source GDG dan dest STR/DISPLAY pada tanggal hari ini.

## Files Changed
| File | Change |
|------|--------|
| `odoo/stock_services.py` | + new dataclass `InternalMoveSummary` + function `get_internal_moves_summary_by_day()` |
| `ui/pages/dashboard.py` | − POS filter form, AgGrid table, `_cached_recent_pos_orders`, `format_utc_to_wib`. + internal moves section with st.dataframe |

## Query Logic (`get_internal_moves_summary_by_day`)
- **Model:** `stock.move`
- **Domain:** `[("location_id.complete_name", "ilike", "GDG"), "|", ("location_dest_id.complete_name", "ilike", "STR"), ("location_dest_id.complete_name", "ilike", "DISPLAY"), ("date", "=", target_date)]`
  → source contains GDG AND (dest contains STR OR DISPLAY) AND date = today
- **Fields:** `["partner_id", "product_qty"]`
- **Grouping:** Python dict → group by `partner_id` → count records + sum `product_qty`
- **Caching:** `@st.cache_data(ttl=300)` on dashboard
- **Export:** `InternalMoveSummary(partner_id, partner_name, record_count, total_product_qty)`

## UI
```
📦 Internal Moves Hari Ini (08/07/2026)
  Contact        | Jumlah Record | Total Qty
  ───────────────┼───────────────┼──────────
  PT ABC         | 15            | 234
  Toko XYZ       | 8             | 89
```

## Removed
- `get_recent_pos_orders()` from odoo/services (import dead — still exists in services.py but dashboard no longer calls it)
- POS Filter expander/form (session state `pos_filter_state` removed)
- `format_utc_to_wib()` function
- `st_aggrid` dependency (was only used for the table)

## Edge Cases
- **No partner:** rows without `partner_id` are skipped
- **No data:** shows `st.info("Belum ada internal moves hari ini.")`
- **Odoo error:** shows `st.error()` with exception message
- **Empty result:** still shows table header with date then info message

## Commit
`71d5f86` — `feat(dashboard): Replace Recent Sales Orders with Internal Moves summary`
