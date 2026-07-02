"""DSI Report page UI"""

import streamlit as st
import pandas as pd
from datetime import date, timedelta

from logic.dsi_service import compute_dsi_report


def render_dsi_report_page():
    """Render DSI Report page content"""
    st.title("📋 DSI Report")
    st.markdown("### Days Sales of Inventory Report")

    st.warning(
        "⚠️ **Keterbatasan data:** DSI dihitung dari data stok saat ini. "
        "Untuk produk dengan pergerakan cepat, akurasi mungkin terpengaruh. "
        "Hasil adalah estimasi, bukan angka pasti."
    )

    # --- Form Section ---
    with st.form("dsi_form"):
        col1, col2 = st.columns(2)

        with col1:
            today = date.today()
            default_start = today - timedelta(days=30)
            date_range = st.date_input(
                "📅 Date Range",
                value=(default_start, today),
                max_value=today,
            )

        with col2:
            st.info("🏷️ Brand filter akan ditambahkan setelah field brand tersedia di Odoo.")

        submitted = st.form_submit_button(
            "🔍 Generate DSI Report",
            type="primary",
            use_container_width=True,
        )

    # --- Process ---
    if submitted:
        if len(date_range) != 2:
            st.error("❌ Pilih tanggal awal dan akhir.")
            return

        date_from, date_to = date_range
        assert isinstance(date_from, date) and isinstance(date_to, date)

        with st.spinner("Menghitung DSI..."):
            try:
                df = compute_dsi_report(
                    date_from=date_from,
                    date_to=date_to,
                )

                st.session_state.dsi_results = df
                st.session_state.dsi_params = {
                    "date_from": date_from,
                    "date_to": date_to,
                }
                st.rerun()
            except Exception as e:
                st.error(f"❌ Error: {e}")

    # --- Results Section ---
    if "dsi_results" in st.session_state and st.session_state.dsi_results is not None:
        df = st.session_state.dsi_results
        params = st.session_state.get("dsi_params", {})

        if df.empty:
            st.warning("⚠️ Tidak ada data ditemukan.")
            return

        # Summary metrics
        st.markdown("---")
        st.subheader("📊 Summary")

        # Define classification order and colors
        classification_order = {
            "Very Fast": "🟢",
            "Fast": "🔵",
            "Normal": "🟡",
            "Slow": "🟠",
            "Dead": "🔴",
        }

        total = len(df)
        st.metric("Total Products", total)

        display_cols = st.columns(5)
        for col_idx, (label, icon) in enumerate(classification_order.items()):
            count = len(df[df["classification"] == label])
            with display_cols[col_idx]:
                st.metric(f"{icon} {label}", f"{count} ({count/total*100:.0f}%)")

        # Classification distribution chart
        st.markdown("---")
        st.subheader("📈 Distribution")

        # Count by classification in order
        class_counts = {}
        for label in classification_order:
            class_counts[label] = len(df[df["classification"] == label])

        chart_df = pd.DataFrame({
            "classification": list(class_counts.keys()),
            "count": list(class_counts.values()),
        }).set_index("classification")

        st.bar_chart(chart_df)

        # Results table
        st.markdown("---")
        st.subheader("📋 DSI Details")

        # Format for display
        display_df = df.copy()
        if "dsi" in display_df.columns:
            display_df["dsi"] = display_df["dsi"].apply(
                lambda x: f"{x:.1f}" if pd.notna(x) else "-"
            )
        if "cogs" in display_df.columns:
            display_df["cogs"] = display_df["cogs"].apply(
                lambda x: f"Rp {x:,.0f}" if pd.notna(x) and x > 0 else "-"
            )

        st.dataframe(
            display_df[[
                "barcode", "name", "category",
                "beginning_qty", "ending_qty", "avg_qty",
                "cogs", "dsi", "classification",
            ]],
            use_container_width=True,
            hide_index=True,
        )

        # Download button
        st.markdown("---")
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download CSV",
            data=csv,
            file_name=f"dsi_report_{params.get('date_from', 'export')}.csv",
            mime="text/csv",
        )

        # Help section
        st.markdown("---")
        with st.expander("ℹ️ Cara Membaca DSI Report"):
            st.markdown("""
            **DSI (Days Sales of Inventory)** = (Rata-rata Inventory / COGS) x Hari

            - **Very Fast (0-30 hr):** Barang laku cepat, stok habis <=1 bulan
            - **Fast (31-60 hr):** Barang laku dalam 1-2 bulan
            - **Normal (61-90 hr):** Perputaran sehat
            - **Slow (91-180 hr):** Lambat bergerak, perlu perhatian
            - **Dead (>180 hr):** Stok mati, pertimbangkan diskon atau write-off
            """)
