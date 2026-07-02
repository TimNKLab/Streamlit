"""Update Cost page — search vendor bills, analyze cost changes, update Odoo standard_price."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import streamlit as st
import pandas as pd

from logic.cost_update_service import CostUpdateService


def _get_service() -> CostUpdateService:
    if "cost_update_service" not in st.session_state:
        st.session_state.cost_update_service = CostUpdateService()
    # Force recreate on code reload (stale cached instances miss new methods)
    if not hasattr(st.session_state.cost_update_service, "get_bills_by_date_range"):
        st.session_state.cost_update_service = CostUpdateService()
    return st.session_state.cost_update_service


def _fmt_rp(v: float | None) -> str:
    if v is None:
        return "-"
    return f"Rp {v:,.0f}"


def _fmt_datetime(v: str | None) -> str:
    """Format ISO timestamp to DD/MM/YYYY HH:MM WIB (UTC+7). Returns '-' for None/invalid."""
    if not v or not isinstance(v, str):
        return "-"
    try:
        dt = datetime.fromisoformat(str(v).replace(" ", "T"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        dt_wib = dt.astimezone(ZoneInfo("Asia/Jakarta"))
        return dt_wib.strftime("%d/%m/%Y %H:%M")
    except (ValueError, AttributeError):
        return "-"


# ── Main render ───────────────────────────────────────────────────────────


def render_update_cost_page() -> None:
    """Main render function for Update Cost page."""
    st.title("💰 Update Cost (Modal) dari Vendor Bill")
    service = _get_service()

    # ── Mode toggle ────────────────────────────────────────────────────────
    mode = st.radio("Mode", ["Pilih Vendor Bill", "Pilih Tanggal"], horizontal=True, label_visibility="collapsed")

    # ── Step 1: Select source ──────────────────────────────────────────────
    load_clicked = False
    bill_id = None
    bill_label = ""
    date_mode = False

    if mode == "Pilih Vendor Bill":
        if "recent_bills_cost" not in st.session_state:
            with st.spinner("Memuat daftar faktur terbaru..."):
                try:
                    st.session_state.recent_bills_cost = service.get_recent_bills()
                except Exception as e:
                    st.error(f"Gagal memuat faktur: {e}")
                    st.session_state.recent_bills_cost = []

        bills = st.session_state.recent_bills_cost
        if not bills:
            st.info("Tidak ada faktur vendor ditemukan.")
            return

        bill_options: Dict[str, int] = {}
        for b in bills:
            bid = int(b["id"])
            name_raw = b.get("name")
            ref_raw = b.get("ref")
            bill_no = str(name_raw).strip() if name_raw and str(name_raw).strip() not in ("", "/", "False") else ""
            if not bill_no:
                bill_no = str(ref_raw).strip() if ref_raw and str(ref_raw).strip() not in ("", "False") else ""
            if not bill_no:
                bill_no = f"Bill #{bid} (Draft)"
            partner = b.get("partner_id")
            partner_name = partner[1] if isinstance(partner, (list, tuple)) and len(partner) >= 2 else ""
            date_str = str(b.get("invoice_date", ""))[:10] or "-"
            bill_options[f"{bill_no} | {date_str} | {partner_name}"] = bid

        col1, col2 = st.columns([3, 1])
        with col1:
            sel_label = st.selectbox("Pilih Faktur Vendor", options=list(bill_options.keys()), key="bill_selector_cost")
        with col2:
            st.markdown("###")
            load_clicked = st.button("🔍 Load", type="primary", use_container_width=True)

        if load_clicked:
            bill_id = bill_options[sel_label]
            bill_label = sel_label

    else:  # Pilih Tanggal
        date_mode = True
        col1, col2, col3 = st.columns([2, 2, 1])
        with col1:
            date_from = st.date_input("Dari", value=date.today().replace(day=1), key="date_from_cost")
        with col2:
            date_to = st.date_input("Sampai", value=date.today(), key="date_to_cost")
        with col3:
            st.markdown("###")
            load_clicked = st.button("🔍 Load Bills", type="primary", use_container_width=True)

    # ── Step 2: Load & analyze ─────────────────────────────────────────────
    if load_clicked:
        if not date_mode:
            # Single bill
            with st.spinner("Menganalisis faktur..."):
                try:
                    raw_rows = service.analyze_bill_for_cost(bill_id)
                    st.session_state.cost_analysis_rows = raw_rows
                    st.session_state.selected_bill_id_cost = bill_id
                    st.session_state.selected_bill_label_cost = bill_label
                except Exception as e:
                    st.error(f"Gagal menganalisis faktur: {e}")
                    st.session_state.cost_analysis_rows = []
        else:
            # Batch by date range
            with st.spinner(f"Mengambil faktur {date_from.isoformat()} s.d {date_to.isoformat()}..."):
                try:
                    bills = service.get_bills_by_date_range(date_from, date_to)
                except Exception as e:
                    st.error(f"Gagal mengambil faktur: {e}")
                    st.session_state.cost_analysis_rows = []
                    return

            if not bills:
                st.info(f"Tidak ada faktur vendor untuk range {date_from.isoformat()} s.d {date_to.isoformat()}.")
                st.session_state.cost_analysis_rows = []
                return

            bill_status = st.empty()
            all_rows: List[Dict[str, Any]] = []
            errors = []

            for i, b in enumerate(bills):
                bid = int(b["id"])
                bname = str(b.get("name") or f"Bill #{bid}")
                bill_status.info(f"Memproses {i+1}/{len(bills)}: {bname}")
                try:
                    rows = service.analyze_bill_for_cost(bid)
                    all_rows.extend(rows)
                except Exception as e:
                    errors.append((bname, str(e)))

            bill_status.empty()

            # Dedup by barcode — keep first (largest bill ID is first in order)
            seen: set = set()
            deduped = []
            for r in all_rows:
                if r["barcode"] not in seen:
                    seen.add(r["barcode"])
                    deduped.append(r)

            st.session_state.cost_analysis_rows = deduped
            bill_label = f"{date_from.isoformat()} s.d {date_to.isoformat()} — {len(deduped)} produk dari {len(bills)} bill"
            st.session_state.selected_bill_label_cost = bill_label

            # Show bill status
            if errors:
                with st.expander(f"⚠️ {len(errors)} bill gagal diproses", expanded=False):
                    for bname, err in errors:
                        st.caption(f"{bname}: {err}")
            st.caption(f"✅ {len(bills)} bill ditemukan. {len(deduped)} produk unik dari {len(all_rows)} total baris.")

    # ── Step 3: Render analysis if data exists ─────────────────────────────
    if "cost_analysis_rows" not in st.session_state or not st.session_state.cost_analysis_rows:
        return

    _render_cost_analysis(service, st.session_state.cost_analysis_rows, st.session_state.get("selected_bill_label_cost", ""))


def _render_cost_analysis(service: CostUpdateService, raw_rows: List[Dict[str, Any]], bill_label: str) -> None:
    """Render cost analysis table, editor, and update button."""
    st.session_state.selected_bill_label_cost = bill_label

    df_data = []
    for idx, r in enumerate(raw_rows):
        modal_baru = r.get("modal_baru")
        std_price_lama = r.get("standard_price_lama", 0)
        cost_diff = r.get("cost_diff", 0)

        df_data.append({
            "No": idx + 1,
            "Pilih": True,
            "Barcode": r["barcode"],
            "Nama Produk": r["name"],
            "Harga Jual": _fmt_rp(r.get("list_price")),
            "Cost Lama (Odoo)": _fmt_rp(std_price_lama),
            "Modal Baru": _fmt_rp(modal_baru),
            "Cost Baru": int(r.get("standard_price_baru", 0)),
            "Selisih Cost": _fmt_rp(cost_diff),
        })

    df = pd.DataFrame(df_data)

    st.markdown("### Hasil Analisis Cost Update")
    st.caption(f"Menampilkan {len(raw_rows)} produk dengan perubahan cost > Rp500.")

    editable_cols = ["Cost Baru", "Pilih"]
    edited_df = st.data_editor(
        df,
        column_config={
            "Pilih": st.column_config.CheckboxColumn("Pilih", default=True, width="small"),
            "Cost Baru": st.column_config.NumberColumn("Cost Baru", format="Rp %d", min_value=0, required=True),
            "Harga Jual": st.column_config.TextColumn("Harga Jual", disabled=True),
            "Cost Lama (Odoo)": st.column_config.TextColumn("Cost Lama (Odoo)", disabled=True),
            "Modal Baru": st.column_config.TextColumn("Modal Baru", disabled=True),
            "Selisih Cost": st.column_config.TextColumn("Selisih Cost", disabled=True),
            "Barcode": st.column_config.TextColumn("Barcode", disabled=True),
            "Nama Produk": st.column_config.TextColumn("Nama Produk", disabled=True),
            "No": st.column_config.NumberColumn("No", disabled=True),
        },
        hide_index=True,
        use_container_width=True,
        disabled=[c for c in df.columns if c not in editable_cols],
        key="cost_analysis_editor",
    )

    # Sync edits
    for idx in range(len(raw_rows)):
        cost_val = edited_df.iloc[idx]["Cost Baru"]
        if isinstance(cost_val, str):
            # Stale persistence from old code — clear and reload
            for k in ["cost_analysis_rows", "selected_bill_id_cost",
                       "selected_bill_label_cost", "recent_bills_cost"]:
                st.session_state.pop(k, None)
            st.rerun()
            return
        raw_rows[idx]["standard_price_baru"] = float(cost_val)
        raw_rows[idx]["selected"] = bool(edited_df.iloc[idx]["Pilih"])
    st.session_state.cost_analysis_rows = raw_rows

    # Summary metrics
    if raw_rows:
        c1, c2 = st.columns(2)
        c1.metric("Total Produk", len(raw_rows))
        avg_cost_diff = sum(r.get("cost_diff", 0) for r in raw_rows) / len(raw_rows)
        c2.metric("Rata-rata Δ Cost", _fmt_rp(avg_cost_diff))

    # Update button
    selected_indices = [i for i, r in enumerate(raw_rows) if r.get("selected")]
    if not selected_indices:
        st.info("Pilih produk yang ingin diupdate cost-nya, lalu klik 'Update Cost ke Odoo'.")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button(
            f"🚀 Update Cost {len(selected_indices)} Produk ke Odoo",
            type="primary", use_container_width=True,
        ):
            with st.spinner("Mengupdate cost (standard_price) ke Odoo..."):
                try:
                    result = service.update_selected(raw_rows, selected_indices)
                    for barcode, err in result.get("errors", []):
                        st.error(f"{barcode}: {err}")
                    if result["failed"] > 0:
                        st.warning(f"{result['success']} berhasil, {result['failed']} gagal.")
                    else:
                        st.success(f"✅ {result['success']} produk berhasil diupdate cost ke Odoo!")
                except Exception as e:
                    st.error(f"Gagal mengupdate: {e}")
    with col2:
        if st.button("🔄 Reset", use_container_width=True):
            for key in ["cost_analysis_rows", "selected_bill_id_cost", "selected_bill_label_cost", "recent_bills_cost"]:
                st.session_state.pop(key, None)
            st.rerun()