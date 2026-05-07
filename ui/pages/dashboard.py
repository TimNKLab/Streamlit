"""Dashboard page UI"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd
from st_aggrid import AgGrid, GridOptionsBuilder

from odoo.services import (
    OdooIntegrationError,
    SalesMetrics,
    check_odoo_health,
    get_recent_pos_orders,
    get_sales_metrics,
)

# Define WIB timezone (UTC+7) at module level
WIB = ZoneInfo("Asia/Jakarta")


@st.cache_data(ttl=300)
def _cached_sales_metrics(
    *,
    pos_start_dt: "datetime" | None = None,
    pos_end_dt: "datetime" | None = None,
) -> SalesMetrics:
    return get_sales_metrics(pos_start_dt=pos_start_dt, pos_end_dt=pos_end_dt)


@st.cache_data(ttl=300)
def _cached_recent_pos_orders(
    *,
    limit: int | None = None,
    start_dt: "datetime" | None = None,
    end_dt: "datetime" | None = None,
):
    """Wrap recent POS orders with caching.

    Args:
        limit: Max number of orders to retrieve. ``None`` fetches all.
        start_dt: Inclusive start datetime filter.
        end_dt: Inclusive end datetime filter.
    """
    return get_recent_pos_orders(limit=limit, start_dt=start_dt, end_dt=end_dt)


def format_utc_to_wib(date_str):
    """Convert UTC datetime string to WIB timezone for display."""
    if not date_str:
        return date_str
    
    try:
        # Simple approach: parse datetime and add exactly 7 hours
        # Handle different Odoo date formats
        if 'T' in date_str:
            # ISO format: "2024-05-02T03:18:45Z" or "2024-05-02T03:18:45"
            clean_str = date_str.replace('Z', '').split('.')[0].split('+')[0]
            utc_dt = datetime.fromisoformat(clean_str)
        else:
            # Standard format: "2024-05-02 03:18:45"
            clean_str = date_str.split('.')[0]
            utc_dt = datetime.strptime(clean_str, "%Y-%m-%d %H:%M:%S")
        
        # Add exactly 7 hours for WIB (UTC+7)
        wib_dt = utc_dt + timedelta(hours=7)
        
        # Handle day overflow
        if wib_dt.day != utc_dt.day:
            # If adding 7 hours crosses to next day, adjust accordingly
            pass
        
        return wib_dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, AttributeError):
        # If all else fails, return original string
        return date_str


def render_dashboard_page():
    """Render dashboard page content backed by live Odoo data."""

    st.title("Dashboard")
    st.markdown("### NK Dashboard v0.7.0")
    st.caption("Ada internal tool untuk Stok Opnam! 😸")

    now = datetime.now(WIB).replace(microsecond=0)
    default_start_dt = (now - timedelta(days=1))

    if "pos_filter_state" not in st.session_state:
        st.session_state.pos_filter_state = {
            "start_date": default_start_dt.date(),
            "start_time": default_start_dt.time(),
            "end_date": now.date(),
            "end_time": now.time(),
        }

    filter_state = st.session_state.pos_filter_state

    with st.expander("POS Order Filter", expanded=False):
        with st.form("pos_filter_form"):
            col_dates = st.columns(2)
            with col_dates[0]:
                start_date_input = st.date_input(
                    "From date",
                    value=filter_state["start_date"],
                    key="pos_start_date_input",
                )
                start_time_input = st.time_input(
                    "From hour",
                    value=filter_state["start_time"],
                    key="pos_start_time_input",
                )
            with col_dates[1]:
                end_date_input = st.date_input(
                    "Until date",
                    value=filter_state["end_date"],
                    key="pos_end_date_input",
                )
                end_time_input = st.time_input(
                    "Until hour",
                    value=filter_state["end_time"],
                    key="pos_end_time_input",
                )

            submitted_filter = st.form_submit_button("Apply POS Filter")

        if submitted_filter:
            new_state = {
                "start_date": start_date_input,
                "start_time": start_time_input,
                "end_date": end_date_input,
                "end_time": end_time_input,
            }
            st.session_state.pos_filter_state = new_state
            filter_state = new_state
            st.toast("Filter POS diperbarui", icon="⏱️")

    col_health, col_refresh = st.columns([4, 1])
    with col_health:
        health_status = "Terhubung" if check_odoo_health() else "Belum Terhubung"
        st.info(f"Odoo status: {health_status}")
    with col_refresh:
        if st.button("🔄 Refresh Data"):
            _cached_sales_metrics.clear()
            _cached_recent_pos_orders.clear()
            st.toast("Dashboard data refreshed", icon="✅")

    pos_start_dt = datetime.combine(filter_state["start_date"], filter_state["start_time"], tzinfo=WIB)
    pos_end_dt = datetime.combine(filter_state["end_date"], filter_state["end_time"], tzinfo=WIB)

    try:
        metrics = _cached_sales_metrics(pos_start_dt=pos_start_dt, pos_end_dt=pos_end_dt)
    except OdooIntegrationError as exc:
        st.error(f"Gagal sinkron ke database: {exc}")
        metrics = None

    col1, col2 = st.columns(2)

    if metrics:
        with col1:
            st.metric("POS Orders (range)", f"{metrics.pos_order_count:,}")
        with col2:
            st.metric("Confirmed Sales Orders", f"{metrics.total_confirmed_orders:,}")


    else:
        for col in (col1, col2):
            with col:
                st.metric("--", "---")

    st.markdown("---")
    st.subheader("📋 Recent Sales Orders")

    if pos_start_dt > pos_end_dt:
        st.error("Rentang POS tidak valid: tanggal/hari awal melebihi akhir.")
        recent_orders = []
    else:
        try:
            recent_orders = _cached_recent_pos_orders(
                limit=None,
                start_dt=pos_start_dt,
                end_dt=pos_end_dt,
            )
        except OdooIntegrationError as exc:
            st.error(f"Tidak dapat mengambil data penjualan terbaru: {exc}")
            recent_orders = []

    st.caption(
        f"Menampilkan POS order dari {pos_start_dt:%Y-%m-%d %H:%M} hingga {pos_end_dt:%Y-%m-%d %H:%M}."
    )

    if recent_orders:
        formatted_rows = [
            {
                "Nomor Order": row.get("name"),
                "Nama Pelanggan": (row.get("partner_id") or [None, "Tidak diketahui"])[1],
                "Status Transaksi": row.get("state"),
                "Tanggal": format_utc_to_wib(row.get("date_order")),
            }
            for row in recent_orders
        ]
        df_orders = pd.DataFrame(formatted_rows)
        
        gb = GridOptionsBuilder.from_dataframe(
            df_orders,
            editable=False,
            sortable=True,
            filterable=True,
            resizable=True
        )

        # Configure columns for better display
        gb.configure_selection("disabled")
        
        grid_options = gb.build()
        
        AgGrid(
            df_orders,
            gridOptions=grid_options,
            allow_unsafe_jscode=True,  # Set to True to allow JsCode objects in gridOptions
            enable_enterprise_modules=False,
            height=300,
            width='100%',
            data_return_mode='AS_INPUT',
            update_mode='VALUE_CHANGED',
            fit_columns_on_grid_load=True,
            key='recent_orders_grid',
            theme='streamlit', # Use the Streamlit theme
        )
    else:
        st.info("Belum ada data yang bisa ditampilkan.")

    st.caption("Data ditarik langsung dari Odoo melalui API odoorpc.")
