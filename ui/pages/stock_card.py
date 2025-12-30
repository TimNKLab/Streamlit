"""Streamlit page for the Stock Card generator."""

from __future__ import annotations

import calendar
from datetime import datetime
from typing import Dict, Optional

import streamlit as st

from logic.stock_card import StockCardGenerator


class StockCardPage:
    """Stock Card page UI component."""

    def __init__(self) -> None:
        self.generator = StockCardGenerator()
        self.init_session_state()

    def init_session_state(self) -> None:
        """Initialize session state variables for this page."""
        defaults = {
            "stock_card_workbooks": None,
            "stock_card_zip": None,
            "stock_card_summary": None,
            "stock_card_error": None,
        }
        for key, value in defaults.items():
            st.session_state.setdefault(key, value)

    def render(self) -> None:
        """Render the Stock Card Streamlit page."""
        st.title("📇 Stock Card Generator")
        st.caption("Buat kartu stok per brand dalam format Excel siap cetak.")

        uploaded_file = self.render_upload_section()
        month, year = self.render_period_inputs()
        generate_all, generate_zip = self.render_output_options()

        if st.button("Generate Stock Cards", type="primary", use_container_width=True):
            self.generate_stock_cards(uploaded_file, month, year)

        self.render_feedback()

        if st.session_state.stock_card_summary and st.session_state.stock_card_workbooks:
            self.render_summary(st.session_state.stock_card_summary)
            self.render_download_section(
                st.session_state.stock_card_workbooks,
                st.session_state.stock_card_zip if generate_zip else None,
                st.session_state.stock_card_summary,
                allow_individual=generate_all,
                allow_zip=generate_zip,
            )

    def render_upload_section(self):
        """Render file upload control."""
        st.markdown("#### 1. Upload Data")
        uploaded_file = st.file_uploader(
            "Pilih file Excel (inventory adjustment export)",
            type=["xlsx", "xls"],
            key="stock_card_excel",
        )
        return uploaded_file

    def render_period_inputs(self) -> tuple[int, int]:
        """Render month and year inputs."""
        st.markdown("#### 2. Kartu Stok untuk Bulan Apa?")
        col1, col2 = st.columns(2)

        with col1:
            month = st.selectbox(
                "Bulan",
                options=list(range(1, 13)),
                format_func=lambda x: calendar.month_name[x],
                index=datetime.now().month - 1,
                key="stock_card_month",
            )

        with col2:
            year = st.number_input(
                "Tahun",
                min_value=2020,
                max_value=2050,
                value=datetime.now().year,
                step=1,
                key="stock_card_year",
            )

        return month, int(year)

    def render_output_options(self) -> tuple[bool, bool]:
        """Render output download toggles."""
        st.markdown("#### 3. Opsi Output")
        col1, col2 = st.columns(2)
        with col1:
            allow_individual = st.checkbox(
                "Sediakan download tiap brand",
                value=True,
                key="stock_card_individual",
            )
        with col2:
            allow_zip = st.checkbox(
                "Sediakan download ZIP keseluruhan",
                value=True,
                key="stock_card_zip_option",
            )
        return allow_individual, allow_zip

    def generate_stock_cards(self, uploaded_file, month: int, year: int) -> None:
        """Handle Stock Card generation."""
        if not uploaded_file:
            st.warning("⚠️ Silakan upload file Excel terlebih dahulu.")
            return

        with st.spinner("Mengolah data..."):
            try:
                workbooks, zip_bytes, summary = self.generator.process_stock_data(
                    uploaded_file, year=year, month=month
                )
                st.session_state.stock_card_workbooks = workbooks
                st.session_state.stock_card_zip = zip_bytes
                st.session_state.stock_card_summary = summary
                st.session_state.stock_card_error = None
                st.success(
                    f"✅ Berhasil membuat {summary['groups_count']} file stock card untuk "
                    f"{summary['month_name']} {summary['year']}."
                )
            except Exception as exc:
                st.session_state.stock_card_workbooks = None
                st.session_state.stock_card_zip = None
                st.session_state.stock_card_summary = None
                st.session_state.stock_card_error = str(exc)

    def render_feedback(self) -> None:
        """Render feedback messages after generation."""
        if st.session_state.stock_card_error:
            st.error(f"❌ Gagal memproses file: {st.session_state.stock_card_error}")

    def render_summary(self, summary: Dict) -> None:
        """Render summary metrics."""
        st.markdown("#### Ringkasan")
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Produk", f"{summary['total_products']:,}")
        with col2:
            st.metric("Groups", summary["groups_count"])
        with col3:
            st.metric("Sheets/Workbook", summary["sheets_per_workbook"])

        st.info(
            f"Periode: **{summary['month_name']} {summary['year']}** &nbsp;•&nbsp; "
            f"Total groups: **{summary['groups_count']}**"
        )

        with st.expander("Lihat daftar groups"):
            groups = summary.get("groups", [])
            if groups:
                st.write(", ".join(groups))
            else:
                st.write("Tidak ada group yang terbentuk.")

    def render_download_section(
        self,
        workbooks: Dict[str, bytes],
        zip_bytes: Optional[bytes],
        summary: Dict,
        allow_individual: bool,
        allow_zip: bool,
    ) -> None:
        """Render download buttons for generated files."""
        st.markdown("#### Unduhan")

        if allow_zip and zip_bytes:
            zip_name = f"StockCards_{summary['month']:02d}{summary['year']}.zip"
            st.download_button(
                label="⬇️ Download Semua (ZIP)",
                data=zip_bytes,
                file_name=zip_name,
                mime="application/zip",
                use_container_width=True,
                type="primary",
            )

        if allow_individual and workbooks:
            with st.expander("Download per brand", expanded=False):
                for filename, file_bytes in sorted(workbooks.items()):
                    st.download_button(
                        label=f"📄 {filename}",
                        data=file_bytes,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                    )


def render_stock_card_page() -> None:
    """Function to render Stock Card page (for backward compatibility)."""
    page = StockCardPage()
    page.render()


__all__ = ["StockCardPage", "render_stock_card_page"]
