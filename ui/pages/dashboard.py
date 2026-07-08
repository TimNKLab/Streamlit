"""Dashboard page UI"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

from odoo.connection import OdooIntegrationError
from odoo.services import SalesMetrics, check_odoo_health, get_sales_metrics
from odoo.stock_services import InternalMoveSummary, get_internal_moves_summary_by_day

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
def _cached_internal_moves_summary(*, target_date: date) -> list[InternalMoveSummary]:
    return get_internal_moves_summary_by_day(target_date=target_date)


def _render_price_update_reminders() -> None:
    """Show banner + full schedule listing for due/upcoming price updates."""
    from logic.schedule_storage import ScheduleStorage
    from logic.bulk_price_update_service import BulkPriceUpdateService
    storage = ScheduleStorage()
    schedules = storage.list_all()
    if not schedules:
        return

    due_rows = []
    upcoming_rows = []
    today = datetime.now(WIB).date()

    for s in schedules:
        for r in s.get("rows", []):
            tgl = r.get("tanggal_update", "")
            if not tgl:
                continue
            try:
                dt = datetime.strptime(tgl[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            entry = {"barcode": r.get("barcode", ""), "name": r.get("name", ""),
                     "tanggal": dt.strftime("%d/%m/%Y")}
            if dt <= today:
                due_rows.append(entry)
            elif dt <= today + timedelta(days=3):
                upcoming_rows.append(entry)

    if due_rows:
        barcodes = ", ".join(f"**{r['barcode']}**" for r in due_rows[:5])
        more = f" +{len(due_rows)-5} lagi" if len(due_rows) > 5 else ""
        st.error(
            f"🔴 **{len(due_rows)} produk perlu dinaikkan harganya!** "
            f"{barcodes}{more} — "
            f"buka **Update Harga Masal → 📅 Update Terjadwal** untuk eksekusi.",
            icon="🚨",
        )
    if upcoming_rows:
        barcodes = ", ".join(f"**{upcoming_rows[0]['barcode']}**" for r in upcoming_rows[:3])
        more = f" +{len(upcoming_rows)-3} lagi" if len(upcoming_rows) > 3 else ""
        st.warning(
            f"⏰ **{len(upcoming_rows)} produk akan naik dalam 3 hari ke depan.** "
            f"{barcodes}{more}",
            icon="📅",
        )

    # ── Full schedule listing (same as bulk_price_update) ──────────────
    st.markdown("---")
    st.subheader("📅 Update Terjadwal")
    service = BulkPriceUpdateService()
    for s in schedules:
        due_label = "🔴 **Jatuh tempo!**" if s["is_due"] else "⏳ Menunggu"
        s_total = s["total_rows"]
        with st.expander(f"{s['label']} — {s_total} produk — {due_label}", expanded=s["is_due"]):
            st.caption(f"Dibuat: {s['created_at'][:19]}")
            for r in s.get("rows", []):
                tgl_display = r.get("tanggal_update", "")[:10] if r.get("tanggal_update") else "-"
                fp = f"Rp {r['fixed_price']:,.0f}" if r.get("fixed_price") else "-"
                st.text(f"  {r['barcode']} — {r['name']}: Rp {r['sales_price']:,.0f} | Fixed: {fp} | Tgl: {tgl_display}")
            col1, col2 = st.columns(2)
            with col1:
                if s["is_due"]:
                    if st.button(f"▶️ Jalankan {s['label']}", key=f"dash_run_{s['id']}", use_container_width=True):
                        with st.spinner(f"Menjalankan {s['label']}..."):
                            result = service.execute_scheduled_file(s["id"])
                        if result["success"]:
                            st.success(f"✅ {result['success']} produk berhasil!")
                        if result.get("errors"):
                            for bc, err in result["errors"]:
                                st.error(f"{bc}: {err}")
                        st.rerun()
            with col2:
                if st.button(f"🗑️ Hapus", key=f"dash_del_{s['id']}", use_container_width=True):
                    service.remove_scheduled_file(s["id"])
                    st.rerun()
def render_dashboard_page():
    """Render dashboard page content backed by live Odoo data."""

    st.title("Dashboard")
    st.markdown("### NK Dashboard v1.0.0")
    st.caption("Terima kasih New Khatulistiwa! 🙋🏻‍♂️")

    # ── Reminder: scheduled price updates that are due ──────────────────
    _render_price_update_reminders()

    now = datetime.now(WIB).replace(microsecond=0)
    today = now.date()

    col_health, col_refresh = st.columns([4, 1])
    with col_health:
        health_status = "Terhubung" if check_odoo_health() else "Belum Terhubung"
        st.info(f"Odoo status: {health_status}")
    with col_refresh:
        if st.button("🔄 Refresh Data"):
            _cached_sales_metrics.clear()
            _cached_internal_moves_summary.clear()
            st.toast("Dashboard data refreshed", icon="✅")

    pos_start_dt = now - timedelta(days=1)
    pos_end_dt = now

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
    st.subheader(f"📦 Internal Moves Hari Ini ({today:%d/%m/%Y})")

    try:
        summaries = _cached_internal_moves_summary(target_date=today)
    except OdooIntegrationError as exc:
        st.error(f"Gagal mengambil data internal moves: {exc}")
        summaries = []

    if summaries:
        df = pd.DataFrame([
            {
                "Contact": s.partner_name,
                "Jumlah Record": s.record_count,
                "Total Qty": f"{s.total_product_qty:,.0f}",
            }
            for s in summaries
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Belum ada internal moves hari ini.")

    st.caption("Data ditarik langsung dari Odoo melalui API odoorpc.")
