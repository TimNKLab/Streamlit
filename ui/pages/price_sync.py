"""Price Sync — detect price changes from Odoo via mail tracking."""

import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from typing import List

from logic.odoo_price_sync import OdooPriceSyncService, PriceChange, SyncResult
from logic.price_tag_service import PriceTagService


@st.cache_resource(ttl=3600)
def _get_sync_service() -> OdooPriceSyncService:
    return OdooPriceSyncService()


@st.cache_resource(ttl=3600)
def _get_price_tag_service() -> PriceTagService:
    return PriceTagService(auto_convert=False, use_memory_cache=False)


_CHANGE_EMOJI = {
    "increase": "📈",
    "decrease": "📉",
    "new": "🆕",
    "removed": "🗑️",
    "discount_change": "🏷️",
}

_COLUMN_CONFIG = {
    "Type": st.column_config.TextColumn("", disabled=True, width="small"),
    "Barcode": st.column_config.TextColumn("Barcode", disabled=True, width="small"),
    "Nama Produk": st.column_config.TextColumn("Nama Produk", disabled=True, width="large"),
    "Harga Lama": st.column_config.TextColumn("Harga Lama", disabled=True),
    "Harga Baru": st.column_config.TextColumn("Harga Baru", disabled=True),
    "Selisih": st.column_config.TextColumn("Selisih", disabled=True),
    "Terakhir": st.column_config.TextColumn("Terakhir Update", disabled=True, width="medium"),
    "Select": st.column_config.CheckboxColumn("Print", default=True),
}


def _build_dataframe(changes: List[PriceChange]) -> pd.DataFrame:
    rows = []
    for c in changes:
        emoji = _CHANGE_EMOJI.get(c.change_type, "❓")
        old = f"Rp {c.old_price:,.0f}" if c.old_price else "-"
        new = f"Rp {c.new_price:,.0f}"
        diff = f"Rp {c.price_diff():,.0f}" if c.old_price else "-"
        changed_at = str(c.changed_at)[:19] if c.changed_at else "-"
        rows.append({
            "Type": f"{emoji} {c.change_type.title()}",
            "Barcode": c.barcode,
            "Nama Produk": c.name,
            "Harga Lama": old,
            "Harga Baru": new,
            "Selisih": diff,
            "Terakhir": changed_at,
            "Select": True,
            "_change": c,
        })
    return pd.DataFrame(rows)


def _generate_pdf(selected_changes: List[PriceChange]) -> bytes:
    items = []
    tag_service = _get_price_tag_service()
    # Sync from Odoo so parquet has current het + diskon
    tag_service.sync_from_odoo()
    for c in selected_changes:
        local = tag_service.lookup_product(c.barcode)
        if local:
            het = local.get("het") or c.new_price
            diskon = local.get("diskon")
            diskon = None if diskon != diskon else diskon  # NaN guard
        else:
            het = c.new_price
            diskon = None
        items.append({"barcode": c.barcode, "name": c.name, "het": het, "diskon": diskon})
    if not items:
        return b""
    return tag_service.generate_pdf(items, size_preset="standard")


def render_price_sync_page() -> None:
    st.title("📊 Price Sync — Deteksi Perubahan Harga")
    st.caption("Deteksi produk dengan perubahan harga atau produk baru dalam rentang waktu tertentu.")

    service = _get_sync_service()

    # Date range selector with datetime picker
    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        start_date = st.date_input(
            "Dari Tanggal",
            value=date.today() - timedelta(days=7),
            max_value=date.today(),
            key="sync_picker_start",
        )
    with col2:
        end_date = st.date_input(
            "Sampai Tanggal",
            value=date.today(),
            max_value=date.today(),
            key="sync_picker_end",
        )
    with col3:
        st.markdown("###")
        detect_clicked = st.button("🔍 Deteksi", type="primary", use_container_width=True)

    # Validate range
    if start_date and end_date:
        diff_days = (end_date - start_date).days
        if diff_days < 0:
            st.error("❌ Tanggal akhir harus setelah tanggal awal")
            detect_clicked = False
        elif diff_days > 30:
            st.warning("⚠️ Maksimal 30 hari. Pilih rentang yang lebih pendek.")
            detect_clicked = False
        elif diff_days >= 14:
            st.warning("⚠️ Range 14+ hari mungkin membutuhkan waktu lebih lama")

    if detect_clicked:
        with st.spinner("Mendeteksi perubahan harga..."):
            try:
                result = service.detect_changes_since(start_date)
                st.session_state.sync_result = result
                st.session_state.sync_start_date = start_date
            except Exception as e:
                st.error(f"Gagal mendeteksi perubahan: {e}")
                st.session_state.sync_result = None

    result: SyncResult | None = st.session_state.get("sync_result")
    if result is None:
        st.info("👆 Pilih rentang waktu dan klik 'Deteksi' untuk memulai")
        return

    # Summary metrics
    inc = len(result.get_by_type("increase"))
    dec = len(result.get_by_type("decrease"))
    new = len(result.get_by_type("new"))
    total = len(result.changes)

    cols = st.columns(4)
    cols[0].metric("Total Perubahan", total)
    cols[1].metric("📈 Naik", inc)
    cols[2].metric("📉 Turun", dec)
    cols[3].metric("🆕 Baru", new)

    if total == 0:
        st.success(f"✅ Tidak ada perubahan harga sejak {st.session_state.sync_start_date.isoformat()}")
        return

    # Results table
    df = _build_dataframe(result.changes)

    edited_df = st.data_editor(
        df.drop(columns=["_change"]),
        column_config=_COLUMN_CONFIG,
        hide_index=True,
        use_container_width=True,
        key="sync_editor",
    )

    # Action buttons
    if "Select" in edited_df.columns:
        selected_mask = edited_df["Select"]
        selected = [result.changes[i] for i in selected_mask[selected_mask].index.tolist()]
    else:
        selected = []

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🖨️ Generate PDF Price Tag", type="primary", use_container_width=True,
                     disabled=not selected):
            pdf_bytes = _generate_pdf(selected)
            if pdf_bytes:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                st.download_button(
                    "⬇️ Download PDF",
                    data=pdf_bytes,
                    file_name=f"price_changes_{timestamp}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                )
                st.success(f"✅ {len(selected)} label siap cetak!")
            else:
                st.error("Gagal membuat PDF")

    with col2:
        if st.button("📊 Export Excel", use_container_width=True, disabled=not selected):
            export_rows = []
            for c in selected:
                export_rows.append({
                    "Barcode": c.barcode,
                    "Nama": c.name,
                    "Tipe": c.change_type,
                    "Harga Lama": c.old_price,
                    "Harga Baru": c.new_price,
                    "Selisih": c.price_diff(),
                    "Terakhir Update": str(c.changed_at)[:19] if c.changed_at else "",
                })
            export_df = pd.DataFrame(export_rows)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_path = f"price_changes_{timestamp}.xlsx"
            export_df.to_excel(export_path, index=False, sheet_name="Price Changes")
            with open(export_path, "rb") as f:
                st.download_button(
                    "⬇️ Download Excel",
                    data=f,
                    file_name=export_path,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    with col3:
        if st.button("🗑️ Hapus Hasil", use_container_width=True):
            st.session_state.sync_result = None
            st.rerun()


def render() -> None:
    render_price_sync_page()
