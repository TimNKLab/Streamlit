### Task 4: Create UI Page

**Files:**
- Create: `ui/pages/update_price.py`
- Modify: `ui/__init__.py`

**Interfaces:**
- Consumes: `PriceUpdateService` from `logic.price_update_service`
- Produces: `render_update_price_page()` function

- [ ] **Step 1: Create page with bill selector and data_editor**

Create `ui/pages/update_price.py`:

```python
"""Update Harga page — search vendor bills, analyze margins, update Odoo prices."""

from __future__ import annotations

from typing import Any, Dict, List

import streamlit as st
import pandas as pd

from logic.price_update_service import PriceUpdateService


def _get_service() -> PriceUpdateService:
    """Get or create cached PriceUpdateService."""
    if "price_update_service" not in st.session_state:
        st.session_state.price_update_service = PriceUpdateService()
    return st.session_state.price_update_service


def _format_rp(value: float | None) -> str:
    if value is None:
        return "-"
    return f"Rp {value:,.0f}"


def _format_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def render_update_price_page() -> None:
    """Main render function for Update Harga page."""
    st.title("📈 Update Harga dari Vendor Bill")
    service = _get_service()

    # Step 1: Load recent bills
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

    # Build dropdown options
    bill_options = {}
    for b in bills:
        label = b.get("name", "?")
        ref = b.get("ref", "")
        date_str = str(b.get("invoice_date", ""))[:10]
        partner = b.get("partner_id")
        partner_name = partner[1] if isinstance(partner, (list, tuple)) and len(partner) >= 2 else ""
        display = f"{label} | {date_str} | {partner_name}"
        if ref:
            display += f" ({ref})"
        bill_options[display] = int(b["id"])

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

    # Step 2: Load and analyze bill
    if load_clicked:
        bill_id = bill_options[selected_label]
        with st.spinner("Menganalisis faktur..."):
            try:
                rows = service.analyze_bill(bill_id)
                st.session_state.analysis_rows = rows
                st.session_state.selected_bill_id = bill_id
                st.session_state.selected_bill_label = selected_label
            except Exception as e:
                st.error(f"Gagal menganalisis faktur: {e}")
                st.session_state.analysis_rows = []

    # Step 3: Display results
    if "analysis_rows" not in st.session_state or not st.session_state.analysis_rows:
        return

    rows = st.session_state.analysis_rows

    # Count promo items for banner
    promo_count = sum(1 for r in rows if r["has_promo"])
    if promo_count > 0:
        st.warning(
            f"⚠️ **{promo_count} produk** memiliki promo aktif. "
            "Centang 'Force?' untuk override guardrail."
        )

    # Build DataFrame for display
    df_data = []
    for idx, r in enumerate(rows):
        df_data.append({
            "No": idx + 1,
            "Barcode": r["barcode"],
            "Nama Produk": r["name"],
            "Harga Modal Lama": _format_rp(r["modal_lama"]),
            "Harga Modal Baru": _format_rp(r["modal_baru"]),
            "Harga Jual": _format_rp(r["list_price"]),
            "Margin Lama": _format_pct(r["margin_before"]),
            "Margin Baru": _format_pct(r["margin_after"]),
            "Promo": "✅ Aktif" if r["has_promo"] else "❌ Tidak",
            "Periode Promo": r["promo_period_str"],
            "Sales Price Baru": r["sales_price_baru"],
            "Fixed Price Baru": r["fixed_price_baru"],
        })

    df = pd.DataFrame(df_data)

    st.markdown("### Hasil Analisis")
    st.caption(
        f"Menampilkan {len(rows)} produk dengan perubahan harga > Rp500. "
        f"{promo_count} produk dengan promo aktif."
    )

    # Checkbox columns for Force? and Pilih
    force_checks = []
    select_checks = []
    for idx, r in enumerate(rows):
        default_force = False
        default_select = not r["has_promo"]
        force_key = f"force_{idx}"
        select_key = f"select_{idx}"

        force_checks.append(st.checkbox(
            "Force?", key=force_key, value=default_force,
            help="Override guardrail promo aktif" if r["has_promo"] else "",
        ))
        select_checks.append(st.checkbox(
            "Pilih", key=select_key, value=default_select,
        ))

    # Display data_editor
    edited_df = st.data_editor(
        df,
        column_config={
            "Sales Price Baru": st.column_config.NumberColumn(
                "Sales Price Baru",
                format="Rp %d",
                min_value=0,
                required=True,
            ),
            "Fixed Price Baru": st.column_config.NumberColumn(
                "Fixed Price Baru",
                format="Rp %d",
                min_value=0,
                required=True,
            ),
            "Harga Modal Lama": st.column_config.TextColumn("Harga Modal Lama", disabled=True),
            "Harga Modal Baru": st.column_config.TextColumn("Harga Modal Baru", disabled=True),
            "Harga Jual": st.column_config.TextColumn("Harga Jual", disabled=True),
            "Margin Lama": st.column_config.TextColumn("Margin Lama", disabled=True),
            "Margin Baru": st.column_config.TextColumn("Margin Baru", disabled=True),
            "Promo": st.column_config.TextColumn("Promo", disabled=True),
            "Periode Promo": st.column_config.TextColumn("Periode Promo", disabled=True),
            "Barcode": st.column_config.TextColumn("Barcode", disabled=True),
            "Nama Produk": st.column_config.TextColumn("Nama Produk", disabled=True),
            "No": st.column_config.NumberColumn("No", disabled=True),
        },
        hide_index=True,
        use_container_width=True,
        disabled=[c for c in df.columns if c not in ["Sales Price Baru", "Fixed Price Baru"]],
        key="analysis_editor",
    )

    # Sync edited values back to session state
    for idx in range(len(rows)):
        rows[idx]["sales_price_baru"] = float(edited_df.iloc[idx]["Sales Price Baru"])
        rows[idx]["fixed_price_baru"] = float(edited_df.iloc[idx]["Fixed Price Baru"])
        rows[idx]["force"] = force_checks[idx]
    st.session_state.analysis_rows = rows

    # Summary
    valid_rows = [r for r in rows if r["margin_before"] is not None and r["margin_after"] is not None]
    if valid_rows:
        avg_margin_lama = sum(r["margin_before"] for r in valid_rows) / len(valid_rows)
        avg_margin_baru = sum(r["margin_after"] for r in valid_rows) / len(valid_rows)
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Produk", len(rows))
        col2.metric("Rata-rata Margin Lama", f"{avg_margin_lama * 100:.1f}%")
        col3.metric("Rata-rata Margin Baru", f"{avg_margin_baru * 100:.1f}%")

    # Step 4: Update button
    selected_indices = [i for i, s in enumerate(select_checks) if s]
    if not selected_indices:
        st.info("Pilih produk yang ingin diupdate, lalu klik 'Update ke Odoo'.")
        return

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button(
            f"🚀 Update {len(selected_indices)} Produk ke Odoo",
            type="primary",
            use_container_width=True,
        ):
            force_map = {i: force_checks[i] for i in selected_indices}
            with st.spinner("Mengupdate harga ke Odoo..."):
                try:
                    result = service.update_selected(rows, selected_indices, force_map)
                    if result["failed"] > 0:
                        st.warning(
                            f"{result['success']} berhasil, {result['failed']} gagal."
                        )
                        for barcode, err in result["errors"]:
                            st.error(f"{barcode}: {err}")
                    else:
                        st.success(f"✅ {result['success']} produk berhasil diupdate ke Odoo!")
                except Exception as e:
                    st.error(f"Gagal mengupdate: {e}")
    with col2:
        if st.button("🔄 Reset", use_container_width=True):
            for key in ["analysis_rows", "selected_bill_id", "selected_bill_label"]:
                st.session_state.pop(key, None)
            st.rerun()
```

- [ ] **Step 2: Verify import**

Run: `python -c "from ui.pages.update_price import render_update_price_page; print('OK')"`

- [ ] **Step 3: Update ui/__init__.py**

Add to `ui/__init__.py`:
```python
from .pages.update_price import render_update_price_page
__all__.append('render_update_price_page')
```

- [ ] **Step 4: Commit**

```bash
git add ui/pages/update_price.py ui/__init__.py
git commit -m "feat: add Update Harga UI page with data_editor"
```
