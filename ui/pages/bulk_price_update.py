"""Bulk Price Update — upload Excel, preview with checkbox, validate, update Odoo."""
from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List

import streamlit as st
import pandas as pd

from logic.bulk_price_update_service import BulkPriceUpdateService


def _get_service() -> BulkPriceUpdateService:
    if "bulk_price_service" not in st.session_state:
        st.session_state.bulk_price_service = BulkPriceUpdateService()
    return st.session_state.bulk_price_service


# ── Allowed columns mapping ────────────────────────────────────────────

_COLUMN_MAP = {
    "barcode": ["barcode", "kode", "code", "sku"],
    "sales_price": ["sales price", "harga jual", "sales_price", "price", "harga"],
    "fixed_price": ["fixed price", "fixed_price", "harga tetap", "promo price", "diskon"],
    "tanggal_update": ["tanggal update", "tanggal_update", "tanggal", "tgl update", "update date"],
}


def _normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns to canonical: Barcode, Sales Price, Fixed Price, Tanggal Update."""
    rename = {}
    for col in df.columns:
        cl = col.strip().lower()
        for canonical, aliases in _COLUMN_MAP.items():
            if cl in aliases:
                rename[col] = canonical
                break
    return df.rename(columns=rename)


def _save_upload(uploaded_file) -> Optional[str]:
    """Save uploaded file to data/uploads/ and return path."""
    upload_dir = Path(__file__).parent.parent.parent / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = Path(uploaded_file.name).suffix or ".xlsx"
    save_name = f"bulk_price_{timestamp}{ext}"
    save_path = upload_dir / save_name

    with open(save_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return str(save_path)


def _fmt_date(iso_str: str | None) -> str:
    """ISO → DD/MM/YYYY or '-'."""
    if not iso_str:
        return "-"
    try:
        d = datetime.strptime(iso_str[:10], "%Y-%m-%d").date()
        return d.strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso_str[:10] if iso_str else "-"


# ── Main render ────────────────────────────────────────────────────────


def render_bulk_price_update_page() -> None:
    st.title("📦 Update Harga Masal")
    st.caption("Upload Excel, pilih produk, validasi, lalu update ke Odoo.")

    service = _get_service()

    # ── Step 1: Upload ──────────────────────────────────────────────────
    uploaded_file = st.file_uploader(
        "📤 Upload File Excel",
        type=["xlsx", "xls"],
        help="Kolom: Barcode, Sales Price (wajib), Fixed Price, Tanggal Update (opsional).",
    )

    if uploaded_file is None:
        if "bulk_validated" in st.session_state:
            _render_results(service)
            _render_scheduled_section(service)
        _render_sample_help()
        return

    # ── Step 2: Parse & Preview ─────────────────────────────────────────
    df = pd.read_excel(uploaded_file)
    df = _normalise_columns(df)

    required = {"barcode", "sales_price"}
    missing = required - set(df.columns.str.lower().str.strip())
    if missing:
        st.error(f"Kolom wajib tidak ditemukan: {', '.join(missing)}. "
                 f"Gunakan: Barcode, Sales Price.")
        return

    st.success(f"✅ File terbaca: {len(df)} baris")

    with st.expander("📄 Preview Upload", expanded=True):
        st.dataframe(df.head(20), use_container_width=True, hide_index=True)

    # ── Step 3: Validate ────────────────────────────────────────────────
    if st.button("🔍 Validasi ke Odoo", type="primary", use_container_width=True):
        with st.spinner("Memvalidasi barcode ke Odoo..."):
            raw = df.to_dict("records")
            validated = service.validate_rows(raw)
            st.session_state.bulk_validated = validated
            st.session_state.bulk_file_path = _save_upload(uploaded_file)
        st.rerun()

    if "bulk_validated" in st.session_state:
        _render_results(service)
        _render_scheduled_section(service)


def _render_results(service: BulkPriceUpdateService) -> None:
    validated: List[Dict[str, Any]] = st.session_state.get("bulk_validated", [])
    if not validated:
        return

    file_path = st.session_state.get("bulk_file_path", "")
    if file_path:
        st.caption(f"📁 File tersimpan: `{os.path.basename(file_path)}`")

    # Summary
    total = len(validated)
    ok = sum(1 for r in validated if r["found"])
    errs = sum(1 for r in validated if r.get("error"))
    promo = sum(1 for r in validated if r["has_active_promo"])
    selected = sum(1 for r in validated if r.get("selected"))
    updated = sum(1 for r in validated if r["status"] == "✅ Updated")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Total", total)
    c2.metric("🟢 Ditemukan", ok)
    c3.metric("🔴 Error", errs)
    c4.metric("⚠️ Promo", promo)
    c5.metric("✅ Dipilih", selected)

    # ── Editable table with checkbox + Tanggal Update ───────────────────
    st.markdown("### 📋 Hasil Validasi")

    display_rows = []
    for r in validated:
        old = _fmt_rp(r.get("current_list_price"))
        new = _fmt_rp(r.get("sales_price"))
        fp = _fmt_rp(r.get("fixed_price")) if r.get("fixed_price") else "-"
        tgl = _fmt_date(r.get("tanggal_update"))
        display_rows.append({
            "No": r["row_no"],
            "Pilih": r.get("selected", False),
            "Barcode": r["barcode"],
            "Nama": r["name"] if r["name"] else ("—" if r.get("error") else ""),
            "Harga Lama": old,
            "Harga Baru": new,
            "Fixed Price": fp,
            "Tgl Update": tgl,
            "Periode Promo": r.get("promo_period_str") or "-",
            "Status": r["status"],
            "Catatan": r["promo_warning"] if r["promo_warning"] else (r.get("error") or ""),
        })

    df_display = pd.DataFrame(display_rows)

    edited_df = st.data_editor(
        df_display,
        column_config={
            "Pilih": st.column_config.CheckboxColumn("Pilih", default=True, width="small"),
            "Status": st.column_config.TextColumn("Status", width="medium"),
            "Catatan": st.column_config.TextColumn("Catatan", width="large"),
            "Tgl Update": st.column_config.TextColumn("Tgl Update", width="small"),
        },
        disabled=[c for c in df_display.columns if c not in ("Pilih",)],
        hide_index=True,
        use_container_width=True,
        key="bulk_editor",
    )

    # Sync "Pilih" back to validated
    for idx in range(len(validated)):
        validated[idx]["selected"] = bool(edited_df.iloc[idx]["Pilih"])
    st.session_state.bulk_validated = validated

    # ── Promo warnings ──────────────────────────────────────────────────
    promo_rows = [r for r in validated if r["has_active_promo"]]
    if promo_rows:
        if st.toggle("🔓 Tampilkan produk dengan promo", key="show_promo_toggle"):
            with st.expander(f"⚠️ {len(promo_rows)} Produk dengan Promo Aktif", expanded=True):
                for r in promo_rows:
                    tgl_hint = ""
                    if r.get("tanggal_update"):
                        tgl_hint = f" — Rencana naik: {_fmt_date(r['tanggal_update'])}"
                    st.warning(
                        f"**{r['barcode']}** — {r['name']}: {r['promo_warning']}{tgl_hint}",
                        icon="⚠️",
                    )

    # ── Execute ─────────────────────────────────────────────────────────
    ready = [r for r in validated if r.get("selected") and not r.get("error") and r["found"]]
    if not ready:
        st.info("Tidak ada data dipilih untuk diupdate.")
        return

    col1, col2 = st.columns(2)
    with col1:
        if st.button(
            f"🚀 Update {len(ready)} Produk ke Odoo",
            type="primary", use_container_width=True,
        ):
            with st.spinner("Mengupdate harga ke Odoo..."):
                try:
                    result = service.execute_updates(validated)
                    st.success(f"✅ {result['success']} produk berhasil diupdate!")
                    if result.get("errors"):
                        for barcode, err in result["errors"]:
                            st.error(f"{barcode}: {err}")
                    if result.get("warnings"):
                        for bc, warn in result["warnings"]:
                            st.warning(f"{bc}: {warn}")
                    if result["skipped"] > 0:
                        st.info(f"⏭️ {result['skipped']} baris dilewati.")
                    st.session_state.bulk_validated = validated
                except Exception as e:
                    st.error(f"Gagal: {e}")

    with col2:
        # ── Save as scheduled if any have future tanggal_update ──────────
        # Use ALL validated (not just ready-selected) so promo rows also get scheduled
        future_rows = [r for r in validated if r.get("tanggal_update") and r["tanggal_update"] > date.today().isoformat()]
        if future_rows:
            if st.button(
                f"📅 Jadwalkan {len(future_rows)} Produk",
                use_container_width=True,
            ):
                name = service.save_scheduled(validated)
                if name:
                    st.success(f"✅ Disimpan sebagai `{name}` di Odoo — "
                               f"{len(future_rows)} produk akan diupdate otomatis.")
                else:
                    st.info("Tidak ada produk dengan tanggal masa depan untuk dijadwalkan.")


def _render_scheduled_section(service: BulkPriceUpdateService) -> None:
    """Show pending scheduled attachments from Odoo."""
    schedules = service.list_scheduled()
    if not schedules:
        return

    st.markdown("---")
    st.subheader("📅 Update Terjadwal")
    for s in schedules:
        due_label = "🔴 **Jatuh tempo!**" if s["is_due"] else "⏳ Menunggu"
        s_total = s["total_rows"]
        with st.expander(f"{s['label']} — {s_total} produk — {due_label}", expanded=s["is_due"]):
            st.caption(f"Dibuat: {s['created_at'][:19]}")
            col1, col2 = st.columns(2)
            with col1:
                if st.button(f"▶️ Jalankan {s['label']}", key=f"run_{s['id']}", use_container_width=True):
                    with st.spinner(f"Menjalankan {s['label']}..."):
                        result = service.execute_scheduled_file(s["id"])
                    if result["success"]:
                        st.success(f"✅ {result['success']} produk berhasil!")
                    if result.get("errors"):
                        for bc, err in result["errors"]:
                            st.error(f"{bc}: {err}")
                    st.rerun()
            with col2:
                if st.button(f"🗑️ Hapus", key=f"del_{s['id']}", use_container_width=True):
                    service.remove_scheduled_file(s["id"])
                    st.rerun()


def _render_sample_help() -> None:
    with st.expander("ℹ️ Format File", expanded=False):
        st.markdown("""
        **Kolom yang didukung:**

        | Kolom | Wajib | Keterangan |
        |-------|-------|------------|
        | Barcode / Kode / SKU | ✅ | Barcode produk |
        | Sales Price / Harga Jual | ✅ | Harga baru |
        | Fixed Price / Harga Tetap | ❌ | Harga pricelist |
        | Tanggal Update / Tgl Update | ❌ | DD/MM/YYYY — pengingat kapan naik |

        **Contoh:**

        | Barcode | Sales Price | Fixed Price | Tanggal Update |
        |---------|-------------|-------------|----------------|
        | 8991001010049 | 4000 | 3800 | 15/07/2026 |
        | 8991001017215 | 3800 | | |
        """)

    st.info("👆 Upload file Excel untuk memulai.")


def render() -> None:
    render_bulk_price_update_page()


def _fmt_rp(v: float | None) -> str:
    if v is None:
        return "-"
    return f"Rp {v:,.0f}"
