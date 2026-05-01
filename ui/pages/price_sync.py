"""Sinkronisasi Harga"""

import streamlit as st
import pandas as pd
from datetime import datetime
from typing import List, Dict, Set

from logic.indexeddb_price_sync import IndexedDBPriceSyncService, SyncResult, PriceChange
from logic.price_tag_service import PriceTagService


# ---------------------------------------------------------------------------
# Cached helpers
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def _get_sync_service() -> IndexedDBPriceSyncService:
    """Instantiate the IndexedDB sync service once per session."""
    return IndexedDBPriceSyncService()


def _build_change_lookup(result: SyncResult) -> Dict[str, list]:
    """
    Bucket changes by type in a single O(n) pass.
    Returns {'increase': [...], 'decrease': [...], 'new': [...], 'removed': [...], 'discount_change': [...], 'het_and_discount': []}.
    """
    buckets: Dict[str, list] = {
        "increase": [],
        "decrease": [],
        "new": [],
        "removed": [],
        "discount_change": [],
        "het_and_discount": [],
    }
    for c in result.changes:
        if c.change_type in buckets:
            buckets[c.change_type].append(c)
    return buckets


def _filter_changes(
    buckets: Dict[str, list],
    show_increase: bool,
    show_decrease: bool,
    show_new: bool,
    show_removed: bool,
    show_discount_change: bool,
    show_het_and_discount: bool = True,
) -> list:
    """Assemble the filtered list from pre-bucketed data — O(k) where k = result size."""
    filtered: list = []
    if show_increase:
        filtered.extend(buckets["increase"])
    if show_decrease:
        filtered.extend(buckets["decrease"])
    if show_new:
        filtered.extend(buckets["new"])
    if show_removed:
        filtered.extend(buckets["removed"])
    if show_discount_change:
        filtered.extend(buckets["discount_change"])
    if show_het_and_discount:
        filtered.extend(buckets.get("het_and_discount", []))
    return filtered


def _build_dataframe(filtered_changes: list) -> pd.DataFrame:
    """Build display DataFrame in a single vectorised pass."""
    # Pre-compute each column as a list — avoids repeated dict construction
    barcodes   = [c.barcode for c in filtered_changes]
    names      = [c.name[:50] + "…" if len(c.name) > 50 else c.name for c in filtered_changes]
    types      = [c.change_type.upper() for c in filtered_changes]
    
    # Handle both old and new sync service field names
    def get_old_price(c):
        if hasattr(c, 'old_het'):
            return c.old_het
        return getattr(c, 'old_price', None)
    
    def get_new_price(c):
        if hasattr(c, 'new_het'):
            return c.new_het
        return getattr(c, 'new_price', 0)
    
    old_prices = [f"Rp {get_old_price(c):,.0f}" if get_old_price(c) else "-" for c in filtered_changes]
    new_prices = [f"Rp {get_new_price(c):,.0f}" for c in filtered_changes]
    diffs      = [f"Rp {c.price_diff():,.0f}" if get_old_price(c) else "-" for c in filtered_changes]
    diff_pcts  = [f"{c.price_diff_pct():.1f}%" if get_old_price(c) else "-" for c in filtered_changes]
    # Show diskon for discount_change items
    diskons    = [f"Rp {c.new_diskon:,.0f}" if c.change_type == "discount_change" and hasattr(c, 'new_diskon') and c.new_diskon else "-" for c in filtered_changes]

    return pd.DataFrame(
        {
            "Select":   [True] * len(filtered_changes),
            "Barcode":  barcodes,
            "Name":     names,
            "Type":     types,
            "Old Price": old_prices,
            "New Price": new_prices,
            "Diskon":   diskons,
            "Diff":     diffs,
            "Diff %":   diff_pcts,
        }
    )


# Column config is a constant — define once, not on every render
_COLUMN_CONFIG = {
    "Select":    st.column_config.CheckboxColumn("Print", default=True),
    "Barcode":   st.column_config.TextColumn("Barcode", disabled=True),
    "Name":      st.column_config.TextColumn("Product Name", disabled=True, width="large"),
    "Type":      st.column_config.TextColumn("Change", disabled=True),
    "Old Price": st.column_config.TextColumn("Old", disabled=True),
    "New Price": st.column_config.TextColumn("New", disabled=True),
    "Diskon":    st.column_config.TextColumn("Diskon", disabled=True),
    "Diff":      st.column_config.TextColumn("Diff", disabled=True),
    "Diff %":    st.column_config.TextColumn("%", disabled=True),
}


# ---------------------------------------------------------------------------
# Sub-renderers (keep render_price_sync_page lean)
# ---------------------------------------------------------------------------

def _render_sync_section(sync_service: IndexedDBPriceSyncService) -> None:
    """Render the sync controls and trigger sync."""
    st.subheader("Update Harga Sistem Odoo")

    # Get IndexedDB status
    sync_status = sync_service.get_sync_status()
    if sync_status["is_initialized"]:
        st.success(f"📦 {sync_status['cached_products']:,} produk tersimpan di perangkat ini")
    else:
        st.info("ℹ️ Sinkronisasi pertama akan menyimpan semua produk ke perangkat ini")

    col1, col2 = st.columns([2, 1])

    with col1:
        if st.button("Update Harga", type="primary", use_container_width=True):
            with st.spinner("Mengambil harga dari Odoo…"):
                try:
                    result = sync_service.detect_changes()
                    st.session_state.last_sync_result = result
                    # Invalidate cached buckets whenever a new sync arrives
                    st.session_state.pop("_change_buckets", None)
                    st.success(f"Selesai! {len(result.changes)} perubahan ditemukan")
                except Exception as e:
                    st.error(f"Sinkron gagal: {e}")
                    # Show detailed error in expander
                    with st.expander("Lihat detail error"):
                        import traceback
                        st.code(traceback.format_exc())

    with col2:
        if st.button("Lihat Histori", use_container_width=True):
            history = sync_service.get_sync_history(limit=5)
            if history:
                with st.expander("Sinkron terbaru", expanded=True):
                    for h in reversed(history):
                        ts = h["timestamp"][:19].replace("T", " ")
                        st.caption(
                            f"{ts}: {len(h['changes'])} changes "
                            f"(Odoo: {h['total_odoo_products']}, Local: {h['total_local_products']})"
                        )
            else:
                st.info("Belum ada riwayat")


def _render_results_section(sync_service: IndexedDBPriceSyncService, result: SyncResult) -> None:
    st.subheader("Perubahan harga terdeteksi")

    # Build buckets once per result; cache in session_state to survive widget reruns
    if "_change_buckets" not in st.session_state:
        st.session_state["_change_buckets"] = _build_change_lookup(result)
    buckets: Dict[str, list] = st.session_state["_change_buckets"]
    
    # Ensure all buckets exist (for backward compatibility)
    for key in ["discount_change", "het_and_discount"]:
        if key not in buckets:
            buckets[key] = []

    # Summary metrics — counts come straight from pre-built buckets (O(1))
    cols = st.columns(6)
    with cols[0]:
        st.metric("Harga Naik",      len(buckets["increase"]))
    with cols[1]:
        st.metric("Harga Turun",    len(buckets["decrease"]))
    with cols[2]:
        st.metric("Diskon Berubah", len(buckets["discount_change"]))
    with cols[3]:
        st.metric("HET+Diskon",     len(buckets.get("het_and_discount", [])))
    with cols[4]:
        st.metric("Produk Baru",    len(buckets["new"]))
    with cols[5]:
        st.metric("Dihapus",        len(buckets["removed"]))

    # Filters
    st.markdown("#### Filter Changes")
    filter_cols = st.columns(5)
    with filter_cols[0]:
        show_increase = st.checkbox("Kenaikan Harga", value=True,  key="show_inc")
    with filter_cols[1]:
        show_decrease = st.checkbox("Penurunan Harga", value=True,  key="show_dec")
    with filter_cols[2]:
        show_discount_change = st.checkbox("Diskon Berubah", value=True,  key="show_discount")
    with filter_cols[3]:
        show_new      = st.checkbox("Produk Baru",    value=True,  key="show_new")
    with filter_cols[4]:
        show_removed  = st.checkbox("Dihapus",         value=False, key="show_rem")

    filtered_changes = _filter_changes(
        buckets, show_increase, show_decrease, show_new, show_removed, show_discount_change
    )

    if not filtered_changes:
        st.info("ℹ️ No changes match your filter criteria")
        return

    # DataFrame
    df = _build_dataframe(filtered_changes)

    st.markdown("#### Select Products to Print")
    edited_df = st.data_editor(
        df,
        column_config=_COLUMN_CONFIG,
        hide_index=True,
        use_container_width=True,
        key="changes_editor",
    )

    # O(1) lookup via set instead of O(n) list scan
    selected_barcodes: Set[str] = set(edited_df.loc[edited_df["Select"], "Barcode"])
    selected_changes  = [c for c in filtered_changes if c.barcode in selected_barcodes]

    _render_action_buttons(sync_service, result, selected_changes, selected_barcodes)


@st.cache_resource(show_spinner=False)
def _get_price_tag_service() -> PriceTagService:
    """Instantiate the price tag service once per session."""
    return PriceTagService()


def _generate_price_tags_pdf(
    sync_service: IndexedDBPriceSyncService,
    result: SyncResult,
    selected_changes: list,
    selected_barcodes: Set[str],
    odoo_products: Dict[str, dict],
) -> bytes:
    """Generate PDF price tags for selected changes."""
    change_types = list({c.change_type for c in selected_changes})
    items_for_printing = [
        i
        for i in sync_service.get_products_for_printing(result, change_types=change_types, odoo_products=odoo_products)
        if i["barcode"] in selected_barcodes
    ]
    
    if not items_for_printing:
        return b""
    
    price_tag_service = _get_price_tag_service()
    pdf_bytes = price_tag_service.generate_pdf(items_for_printing)
    return pdf_bytes


def _render_action_buttons(
    sync_service: IndexedDBPriceSyncService,
    result: SyncResult,
    selected_changes: list,
    selected_barcodes: Set[str],
) -> None:
    st.subheader("Buat Price Tags")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Generate price tag", type="primary", use_container_width=True):
            if not selected_changes:
                st.warning("Tidak ada produk dipilih")
            else:
                # Fetch odoo products for committing to IndexedDB
                with st.spinner("Mengambil data produk..."):
                    odoo_products = sync_service.fetch_odoo_products()
                
                pdf_bytes = _generate_price_tags_pdf(
                    sync_service, result, selected_changes, selected_barcodes, odoo_products
                )
                if pdf_bytes:
                    # Commit printed products to IndexedDB as new baseline
                    with st.spinner("Menyimpan ke database lokal..."):
                        sync_service.commit_changes(list(selected_barcodes), odoo_products)
                    
                    st.session_state["generated_pdf"] = pdf_bytes
                    st.session_state["pdf_item_count"] = len(selected_changes)
                    st.success(f"{len(selected_changes)} price tags generated dan tersimpan!")
                    st.balloons()
                else:
                    st.error("Failed to generate PDF")
    
    # Show download button if PDF was generated
    if st.session_state.get("generated_pdf"):
        with col1:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            st.download_button(
                label="⬇ Download PDF",
                data=st.session_state["generated_pdf"],
                file_name=f"price_tags_{timestamp}.pdf",
                mime="application/pdf",
                type="primary",
                use_container_width=True,
            )

    with col2:
        if st.button("Jadikan excel", use_container_width=True):
            timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"price_changes_{timestamp}.xlsx"
            sync_service.export_changes_to_excel(result, output_path)

            with open(output_path, "rb") as f:
                st.download_button(
                    label="⬇Download Excel",
                    data=f,
                    file_name=output_path,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )

    with col3:
        if st.button("Hapus", use_container_width=True):
            st.session_state.last_sync_result = None
            st.session_state.pop("_change_buckets", None)
            st.session_state.pop("generated_pdf", None)
            st.session_state.pop("pdf_item_count", None)
            st.rerun()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render_price_sync_page() -> None:
    """Render the Price Sync page."""
    st.title("Price Sync & Change Detector")
    st.caption(
        "Compare Odoo prices with local database and generate tags for changed products"
    )

    sync_service = _get_sync_service()

    # Debug: Show configuration
    with st.expander("🔧 Debug: Configuration", expanded=False):
        from config.settings import get_odoo_settings
        settings = get_odoo_settings()
        st.json({
            "ODOO_HOST": settings.host,
            "ODOO_PORT": settings.port,
            "ODOO_DATABASE": settings.database,
            "ODOO_USERNAME": settings.username,
            "ODOO_API_KEY": f"{'*' * len(settings.api_key) if settings.api_key else 'None'}",
        })
        st.caption("If you see 'localhost' or 'None', secrets are not configured correctly.")

    # Initialise session state keys once
    st.session_state.setdefault("last_sync_result", None)
    st.session_state.setdefault("selected_changes", [])
    st.session_state.setdefault("generated_pdf", None)
    st.session_state.setdefault("pdf_item_count", 0)

    st.markdown("---")
    _render_sync_section(sync_service)

    result: SyncResult | None = st.session_state.last_sync_result
    if result:
        st.markdown("---")
        _render_results_section(sync_service, result)
    else:
        st.info("👆 Click 'Sync Now' to compare prices with Odoo")



def render() -> None:
    """Entry point for app.py."""
    render_price_sync_page()