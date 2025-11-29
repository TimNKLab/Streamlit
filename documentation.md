# NK Streamlit Dashboard Documentation

## Overview

This Streamlit application consolidates business intelligence workflows for NK Labs. Key features include:

- **Authentication barrier** to guard access to internal tools.
- **Dashboard tab** with live data pulled from Odoo (sales orders + PoS orders).
- **BA Sales Report, Stock Control, and DSI Report** utilities for operational teams.

The dashboard now integrates tightly with Odoo using `odoorpc`, featuring a configurable connection pool and centralized environment-based configuration.

---

## Environment Configuration

Create a `.env` file at the repository root with the following keys:

```ini
# Odoo Connection Configuration
ODOO_HOST=your-odoo-host
ODOO_PORT=443
ODOO_PROTOCOL=jsonrpc+ssl
ODOO_DATABASE=your-db
ODOO_USERNAME=your-user
ODOO_API_KEY=your-api-key

# Optional connection pool tuning
ODOO_POOL_MIN_CONNECTIONS=2
ODOO_POOL_MAX_CONNECTIONS=10
ODOO_POOL_MAX_IDLE_TIME=300
ODOO_POOL_MAX_LIFETIME=3600
ODOO_POOL_HEALTH_CHECK_INTERVAL=60
ODOO_POOL_CONNECTION_TIMEOUT=30
```

> **Tip:** When deploying to production, prefer secret managers or environment variables over plain files.

---

## Installation & Local Run

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Launch the dashboard:
   ```bash
   streamlit run app.py
   ```
3. (Optional) Verify Odoo connectivity via CLI:
   ```bash
   cd scripts
   python test_odoo_connection.py
   ```

---

## Architecture

| Layer | Location | Responsibility |
| --- | --- | --- |
| Configuration | `config/settings.py` | Loads `.env`, exposes cached `OdooSettings`. |
| Connection Pool | `odoo/connection.py` | Manages `odoorpc` clients with pooling, health checks, and error handling. |
| Services | `odoo/services.py` | High-level helpers (sales metrics, POS queries, health). |
| UI Pages | `ui/pages/*.py` | Streamlit views. `dashboard.py` consumes Odoo services. |
| CLI Diagnostics | `scripts/test_odoo_connection.py` | Pings Odoo and samples orders. |

---

## Dashboard Details

### Authentication
- Implemented via `logic/auth.py` and `ui/components/auth_components.py`.
- Uses a simple password check (configurable) before showing tabs.

### Metrics Cards
- Display four KPIs:
  1. POS Orders (count for selected window).
  2. POS Revenue.
  3. Confirmed Sales Orders (Odoo sales). 
  4. Sales Revenue (confirmed orders total).
- Data comes from `get_sales_metrics`, which now mirrors the POS filter window.

### POS Order Table
- Fetches rows via `_cached_recent_pos_orders` → `get_recent_pos_orders`.
- Default window: last 24 hours.
- Users can customize **From/Until Date** and **From/Until Hour** through the “POS Order Filter” expander.
- Summary caption reflects the active window.

### Health Indicator & Refresh
- “Odoo status” info box indicates connectivity (based on `check_odoo_health`).
- `🔄 Refresh Data` button clears Streamlit caches to force fresh queries.

---

## POS Filter Mechanics

1. On load, `st.session_state.pos_filter_state` is initialized to `now` and `now - 1 day`.
2. Users adjust filters via date/time inputs. Submit via **Apply POS Filter**.
3. Selected datetimes feed into:
   - `_cached_recent_pos_orders(limit=None, start_dt=..., end_dt=...)` for the table.
   - `_cached_sales_metrics(pos_start_dt=..., pos_end_dt=...)` for metric cards.
4. Caching (5-minute TTL) ensures performance while enabling ad-hoc refresh.

---

## Error Handling & Troubleshooting

- **Disconnected status despite data:** Hosted Odoo instances may block `db.list()` used by `ping()`. Data loads remain functional.
- **Authentication failure:** Ensure `.env` credentials are correct and API key has proper permissions.
- **Timeouts:** Adjust pool settings (e.g., `ODOO_POOL_CONNECTION_TIMEOUT`) or increase `limit`/`start_dt` windows carefully.

---

## Extending the Dashboard

1. **Add new metrics:** Implement in `odoo/services.py`, expose via cache helper, render with `st.metric`.
2. **Additional tabs:** Follow the pattern in `app.py` and place UI logic under `ui/pages/`.
3. **More data sources:** Reuse `OdooConnectionManager` or build new service layers (e.g., inventory, accounting).

---

## Changelog (recent)

- **POS Integration:** Switched dashboard orders to `pos.order`, added date/hour filters.
- **Metrics Sync:** Sales metrics now reflect POS window (counts + revenue) alongside legacy sales order stats.
- **Diagnostics:** Added `scripts/test_odoo_connection.py` for quick connectivity verification.
