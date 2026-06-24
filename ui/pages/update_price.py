"""Update Harga page — search vendor bills, analyze margins, update Odoo prices."""

from __future__ import annotations

import math
from typing import Any, Dict, List

import streamlit as st
import pandas as pd

from logic.price_update_service import PriceUpdateService
from logic.price_tag_service import PriceTagService


def _get_service() -> PriceUpdateService:
    if "price_update_service" not in st.session_state:
        st.session_state.price_update_service = PriceUpdateService()
    return st.session_state.price_update_service


def _fmt_rp(v: float | None) -> str:
    if v is None:
        return "-"
    return f"Rp {v:,.0f}"


def _fmt_pct(v: float | None) -> str:
    if v is None:
        return "-"
    return f"{v * 100:.1f}%"


def _roundup(v: float) -> int:
    """Round up to nearest 100. 19250 -> 19300."""
    return math.ceil(v / 100.0) * 100


def _has_fixed_price(r: Dict[str, Any]) -> bool:
    for rule in r.get("pricelist_rules", []):
        fp = rule.get("fixed_price")
        if fp and float(fp) > 0:
            return True
    return False


def _get_old_fixed_price(r: Dict[str, Any]) -> float | None:
    for rule in r.get("pricelist_rules", []):
        fp = rule.get("fixed_price")
        if fp and float(fp) > 0:
            return float(fp)
    return None


# ── Price tag helpers ─────────────────────────────────────────────────


def _build_price_tag_items(rows: List[Dict[str, Any]], indices: List[int]) -> List[Dict[str, Any]]:
    """Build tag items for new price labels — no strikethrough, just new price."""
    items = []
    for idx in indices:
        r = rows[idx]
        barcode = r.get("barcode", "")
        name = r.get("name", "")
        if not barcode or not name:
            continue
        new_price = int(r.get("sales_price_baru", r.get("list_price", 0)) or 0)
        items.append({
            "barcode": barcode,
            "name": name,
            "het": new_price,   # straight price, no strikethrough
            "diskon": None,
        })
    return items


def _render_price_tag_download(updated_indices: List[int], rows: List[Dict[str, Any]]):
    """Show price tag download section after successful update."""
    st.markdown("---")
    st.subheader("🏷️ Price Tag Kenaikan Harga")

    tag_items = _build_price_tag_items(rows, updated_indices)
    if not tag_items:
        st.info("Tidak ada item valid untuk price tag.")
        return

    st.caption(f"{len(tag_items)} label harga baru siap cetak")

    with st.spinner("🔄 Membuat PDF..."):
        tag_service = PriceTagService()
        try:
            pdf_bytes = tag_service.generate_pdf(tag_items, size_preset="standard")
        except Exception as e:
            st.error(f"Gagal generate PDF: {e}")
            return

    col_a, col_b, col_c = st.columns([1, 1, 1])
    with col_a:
        st.download_button(
            "⬇️ Download PDF (A4 48x30mm)",
            data=pdf_bytes,
            file_name=f"label_kenaikan_harga_{st.session_state.get('selected_bill_label', 'bill')[:15]}.pdf",
            mime="application/pdf",
            type="primary",
            use_container_width=True,
        )
    with col_b:
        if st.button("🖨️ Print di Browser", use_container_width=True):
            import base64
            import streamlit.components.v1 as components
            pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
            components.html(
                f"""<script>
                  (function(){{
                    try {{
                      const bytes = Uint8Array.from(atob("{pdf_b64}"), c=>c.charCodeAt(0));
                      const url = URL.createObjectURL(new Blob([bytes],{{type:'application/pdf'}}));
                      const w = window.open(url,'_blank');
                      if(!w){{ alert('Popup blocked.'); return; }}
                      const t = setInterval(()=>{{
                        try{{ if(w.document.readyState==='complete'){{ clearInterval(t); w.focus(); w.print(); }} }}
                        catch(e){{}}
                      }},250);
                    }}catch(e){{ alert('Failed: '+(e.message||e)); }}
                  }})();
                </script>""",
                height=0,
            )
    with col_c:
        with st.expander("⚙️ Pengaturan Print", expanded=False):
            st.markdown("""
1. **Paper** → A4
2. **Scale** → 100% (jangan Fit to Page)
3. **Margins** → None
            """)

    # Thermal option
    with st.expander("🔥 Thermal Label (28x18mm)", expanded=False):
        try:
            thermal_bytes = tag_service.generate_thermal_labels_pdf(tag_items, width_mm=28.0, height_mm=18.0)
            st.download_button(
                "⬇️ Download Thermal PDF",
                data=thermal_bytes,
                file_name=f"thermal_kenaikan_{st.session_state.get('selected_bill_label', 'bill')[:15]}.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as e:
            st.warning(f"Thermal PDF gagal: {e}")


# ── Main render ───────────────────────────────────────────────────────


def render_update_price_page() -> None:
    """Main render function for Update Harga page."""
    st.title("📈 Update Harga dari Vendor Bill")
    service = _get_service()

    # ── Step 1: Load recent bills ───────────────────────────────────────
    if "recent_bills" not in st.session_state:
        with st.spinner("Memuat daftar faktur terbaru..."):
            try:
                bills = service.get_recent_bills()
                st.session_state.recent_bills = bills
            except Exception as e:
                st.error(f"Gagal memuat faktur: {e}")
                st.session_state.recent_bills = []

    bills = st.session_state.recent_bills
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
        display = f"{bill_no} | {date_str} | {partner_name}"
        bill_options[display] = bid

    col1, col2 = st.columns([3, 1])
    with col1:
        selected_label = st.selectbox(
            "Pilih Faktur Vendor",
            options=list(bill_options.keys()),
            key="bill_selector",
        )
    with col2:
        st.markdown("###")
        load_clicked = st.button("🔍 Load", type="primary", use_container_width=True)

    # ── Step 2: Load & analyze bill ─────────────────────────────────────
    if load_clicked:
        bill_id = bill_options[selected_label]
        with st.spinner("Menganalisis faktur..."):
            try:
                raw_rows = service.analyze_bill(bill_id)
                st.session_state.analysis_rows = raw_rows
                st.session_state.selected_bill_id = bill_id
                st.session_state.selected_bill_label = selected_label
                st.session_state.updated_indices = []  # clear previous update
            except Exception as e:
                st.error(f"Gagal menganalisis faktur: {e}")
                st.session_state.analysis_rows = []

    if "analysis_rows" not in st.session_state or not st.session_state.analysis_rows:
        return

    raw_rows = st.session_state.analysis_rows

    # ── Promo banner ────────────────────────────────────────────────────
    promo_count = sum(1 for r in raw_rows if r["has_promo"])
    if promo_count > 0:
        st.warning(
            f"⚠️ **{promo_count} produk** memiliki promo aktif. "
            "Centang 'Force?' untuk override guardrail."
        )

    # ── Auto-calc defaults ──────────────────────────────────────────────
    valid_margins = [r["margin_before"] for r in raw_rows if r["margin_before"] is not None]
    avg_margin = sum(valid_margins) / len(valid_margins) if valid_margins else 0.20

    df_data = []
    for idx, r in enumerate(raw_rows):
        margin_target = r["margin_before"] if r["margin_before"] is not None else avg_margin
        sp_baru = _roundup(r["modal_baru"] * (1 + margin_target))

        old_fp = _get_old_fixed_price(r)
        has_fp = _has_fixed_price(r)
        if has_fp and old_fp and r["list_price"] > 0:
            ratio = old_fp / r["list_price"]
            fp_baru = _roundup(sp_baru * ratio)
        else:
            fp_baru = sp_baru

        sf_ratio = None
        if has_fp and old_fp and r["list_price"] > 0:
            sf_ratio = old_fp / r["list_price"]

        fp_lama = old_fp if has_fp and old_fp else None

        df_data.append({
            "No": idx + 1,
            "Pilih": not r["has_promo"],
            "Force?": False,
            "Barcode": r["barcode"],
            "Nama Produk": r["name"],
            "Sales Price Lama": _fmt_rp(r["list_price"]),
            "Fixed Price Lama": _fmt_rp(fp_lama),
            "Margin Lama": _fmt_pct(r["margin_before"]),
            "Modal Lama": _fmt_rp(r["modal_lama"]),
            "Modal Baru": _fmt_rp(r["modal_baru"]),
            "Harga→Fix": _fmt_pct(sf_ratio) if sf_ratio is not None else "-",
            "Sales Price Baru": sp_baru,
            "Fixed Price Baru": fp_baru,
            "Promo": "✅ Aktif" if r["has_promo"] else "❌ Tidak",
            "Periode Promo": r["promo_period_str"],
        })

    df = pd.DataFrame(df_data)

    st.markdown("### Hasil Analisis")
    st.caption(
        f"Menampilkan {len(raw_rows)} produk dengan perubahan harga > Rp500. "
        f"{promo_count} produk dengan promo aktif."
    )

    # ── Data editor ─────────────────────────────────────────────────────
    editable_cols = ["Sales Price Baru", "Fixed Price Baru", "Pilih", "Force?"]
    edited_df = st.data_editor(
        df,
        column_config={
            "Pilih": st.column_config.CheckboxColumn("Pilih", default=True, width="small"),
            "Force?": st.column_config.CheckboxColumn(
                "Force?", default=False, width="small",
                help="Override guardrail promo aktif",
            ),
            "Sales Price Baru": st.column_config.NumberColumn("Sales Price Baru", format="Rp %d", min_value=0, required=True),
            "Fixed Price Baru": st.column_config.NumberColumn("Fixed Price Baru", format="Rp %d", min_value=0, required=True),
            "Sales Price Lama": st.column_config.TextColumn("Sales Price Lama", disabled=True),
            "Fixed Price Lama": st.column_config.TextColumn("Fixed Price Lama", disabled=True),
            "Margin Lama": st.column_config.TextColumn("Margin Lama", disabled=True, width="small"),
            "Modal Lama": st.column_config.TextColumn("Modal Lama", disabled=True),
            "Modal Baru": st.column_config.TextColumn("Modal Baru", disabled=True),
            "Harga→Fix": st.column_config.TextColumn("Harga→Fix", disabled=True, width="small"),
            "Promo": st.column_config.TextColumn("Promo", disabled=True, width="small"),
            "Periode Promo": st.column_config.TextColumn("Periode Promo", disabled=True),
            "Barcode": st.column_config.TextColumn("Barcode", disabled=True),
            "Nama Produk": st.column_config.TextColumn("Nama Produk", disabled=True),
            "No": st.column_config.NumberColumn("No", disabled=True),
        },
        hide_index=True,
        use_container_width=True,
        disabled=[c for c in df.columns if c not in editable_cols],
        key="analysis_editor",
    )

    # ── Sync edits ──────────────────────────────────────────────────────
    for idx in range(len(raw_rows)):
        raw_rows[idx]["sales_price_baru"] = float(edited_df.iloc[idx]["Sales Price Baru"])
        raw_rows[idx]["fixed_price_baru"] = float(edited_df.iloc[idx]["Fixed Price Baru"])
        raw_rows[idx]["force"] = bool(edited_df.iloc[idx]["Force?"])
        raw_rows[idx]["selected"] = bool(edited_df.iloc[idx]["Pilih"])
    st.session_state.analysis_rows = raw_rows

    # ── Summary metrics ──────────────────────────────────────────────────
    valid_m = [r for r in raw_rows if r["margin_before"] is not None]
    if valid_m:
        avg_ml = sum(r["margin_before"] for r in valid_m) / len(valid_m)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Produk", len(raw_rows))
        c2.metric("Rata-rata Margin Lama", f"{avg_ml * 100:.1f}%")
        c3.metric("Auto Roundup", "Ke 100")

    # ── Update button ────────────────────────────────────────────────────
    selected_indices = [i for i, r in enumerate(raw_rows) if r.get("selected")]
    if not selected_indices:
        st.info("Pilih produk yang ingin diupdate, lalu klik 'Update ke Odoo'.")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button(
            f"🚀 Update {len(selected_indices)} Produk ke Odoo",
            type="primary", use_container_width=True,
        ):
            force_map = {i: raw_rows[i].get("force", False) for i in selected_indices}
            with st.spinner("Mengupdate harga ke Odoo..."):
                try:
                    result = service.update_selected(raw_rows, selected_indices, force_map)
                    for barcode, err in result.get("errors", []):
                        st.error(f"{barcode}: {err}")
                    for barcode, warn in result.get("warnings", []):
                        st.warning(f"{barcode}: {warn}")
                    if result["failed"] > 0:
                        st.warning(f"{result['success']} berhasil, {result['failed']} gagal.")
                    else:
                        st.success(f"✅ {result['success']} produk berhasil diupdate ke Odoo!")
                    if result["success"] > 0:
                        st.session_state.updated_indices = selected_indices
                except Exception as e:
                    st.error(f"Gagal mengupdate: {e}")
    with col2:
        if st.button("🔄 Reset", use_container_width=True):
            for key in ["analysis_rows", "selected_bill_id", "selected_bill_label", "updated_indices"]:
                st.session_state.pop(key, None)
            st.rerun()

    # ── Price tag download section ───────────────────────────────────────
    updated = st.session_state.get("updated_indices", [])
    if updated:
        _render_price_tag_download(updated, raw_rows)
