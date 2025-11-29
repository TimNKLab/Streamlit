"""BA Sales Report page UI"""

import streamlit as st
import pandas as pd
from datetime import datetime
from logic.sales_processor import SalesProcessor
from logic.excel_utils import sanitize_filename

class BASalesReportPage:
    """BA Sales Report page UI component"""
    
    def __init__(self):
        self.processor = SalesProcessor()
        self.init_session_state()
    
    def init_session_state(self):
        """Initialize session state variables"""
        if 'processed_workbooks' not in st.session_state:
            st.session_state.processed_workbooks = None
        if 'processed_zip' not in st.session_state:
            st.session_state.processed_zip = None
        if 'processing_summary' not in st.session_state:
            st.session_state.processing_summary = None
        if 'processing_error' not in st.session_state:
            st.session_state.processing_error = None
        if 'date_organization_option' not in st.session_state:
            st.session_state.date_organization_option = "Satukan tanggal"
    
    def render_date_organization_section(self):
        """Render date organization options"""
        st.subheader("📅 Date Organization")
        date_option = st.radio(
            "Pilih cara pengorganisasian tanggal:",
            ["Satukan tanggal", "Pisahkan per tanggal"],
            index=0 if st.session_state.date_organization_option == "Satukan tanggal" else 1,
            help="Satukan tanggal: Semua tanggal dalam satu tabel pivot. Pisahkan per tanggal: Setiap tanggal memiliki sheet terpisah."
        )
        st.session_state.date_organization_option = date_option
    
    def render_file_upload_section(self):
        """Render file upload section"""
        st.subheader("📤 Upload Excel File")
        uploaded_file = st.file_uploader(
            "Choose an Excel file",
            type=['xlsx', 'xls'],
            help="Upload Excel file with sales data. Required columns: Order Date, Product/Barcode, Product, Parent Brand, Brand, Quantity, Tax Incl."
        )
        
        if uploaded_file is not None:
            col1, col2 = st.columns(2)
            with col1:
                st.info(f"📄 File: {uploaded_file.name}")
            with col2:
                file_size = uploaded_file.size / 1024
                st.info(f"📊 Size: {file_size:.2f} KB")
            
            if st.button("🔄 Process File", type="primary", use_container_width=True):
                self.process_file(uploaded_file)
        
        return uploaded_file
    
    def process_file(self, uploaded_file):
        """Process the uploaded file"""
        with st.spinner("Tunggu bentar yak, sedang proses."):
            separate_by_date = (st.session_state.date_organization_option == "Pisahkan per tanggal")
            workbooks_dict, zip_file, summary, error = self.processor.process_sales_workbook(uploaded_file, separate_by_date=separate_by_date)
            
            if error:
                st.session_state.processing_error = error
                st.session_state.processed_workbooks = None
                st.session_state.processed_zip = None
                st.session_state.processing_summary = None
            else:
                st.session_state.processed_workbooks = workbooks_dict
                st.session_state.processed_zip = zip_file
                st.session_state.processing_summary = summary
                st.session_state.processing_error = None
                st.success("✅ File berhasil diproses!")
                st.rerun()
    
    def render_error_section(self):
        """Render error section if there's an error"""
        if st.session_state.processing_error:
            st.error(f"❌ Error: {st.session_state.processing_error}")
    
    def render_summary_section(self):
        """Render processing summary"""
        if st.session_state.processing_summary:
            st.markdown("---")
            st.subheader("📊 Processing Summary")
            
            summary = st.session_state.processing_summary
            col1, col2, col3, col4, col5 = st.columns(5)
            
            with col1:
                st.metric("Total Rows", f"{summary['total_rows']:,}")
            
            with col2:
                st.metric("Parent Brands", summary['parent_brands_count'])
            
            with col3:
                st.metric("Workbooks", summary.get('workbooks_count', summary['parent_brands_count']))
            
            with col4:
                st.metric("Start Date", summary['date_range']['start'])
            
            with col5:
                st.metric("End Date", summary['date_range']['end'])
    
    def render_download_section(self):
        """Render download section"""
        if st.session_state.processing_summary:
            st.markdown("---")
            st.subheader("📥 Download Reports")
            
            # Download ZIP button
            if st.session_state.processed_zip:
                zip_bytes = st.session_state.processed_zip.getvalue()
                st.download_button(
                    label="📦 Download All Workbooks (ZIP)",
                    data=zip_bytes,
                    file_name=f"Laporan Penjualan BA {datetime.now().strftime('%d%m%Y')}.zip",
                    mime="application/zip",
                    use_container_width=True,
                    type="primary"
                )
            
            # Individual workbook downloads
            st.markdown("---")
            st.subheader("📄 Individual Brand Downloads")
            
            if st.session_state.processed_workbooks:
                cols = st.columns(3)
                for idx, (workbook_key, workbook_bytes) in enumerate(st.session_state.processed_workbooks.items()):
                    col_idx = idx % 3
                    with cols[col_idx]:
                        sanitized_name = sanitize_filename(workbook_key)
                        filename = f"{sanitized_name}.xlsx"
                        workbook_data = workbook_bytes.getvalue()
                        
                        display_label = workbook_key.replace('_', ' ')[:40]
                        
                        st.download_button(
                            label=f"📥 {display_label}",
                            data=workbook_data,
                            file_name=filename,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True,
                            key=f"download_{sanitized_name}_{idx}"
                        )
            
            # Process new file button
            st.markdown("---")
            if st.button("🔄 Process New File", use_container_width=True):
                st.session_state.processed_workbooks = None
                st.session_state.processed_zip = None
                st.session_state.processing_summary = None
                st.session_state.processing_error = None
                st.rerun()
    
    def render_help_section(self):
        """Render help section"""
        if not st.session_state.processing_summary:
            st.markdown("---")
            st.info("👆 Upload Excel laporan penjualan ke sini.")
            
            st.markdown("---")
            st.subheader("📋 Expected File Format")
            st.text("The Excel file should contain the following columns:")
            st.code("""
- Order Date (datetime)
- Product/Barcode (text)
- Product (text)
- Parent Brand (text, can be empty)
- Brand (text)
- Quantity (numeric)
- Tax Incl. (numeric)
            """)
            
            st.markdown("---")
            st.subheader("ℹ️ Cara Penggunaan")
            st.markdown("""
            1. **Upload**: Upload your Excel file with sales data
            2. **Process**: Click "Process File" to sort and group the data
            3. **Sorting**: Data is sorted by Parent Brand (alphabetically), then by Order Date (earliest first)
            4. **Grouping**: Data is split into separate workbooks by Parent Brand (uses Brand if Parent Brand is empty)
            5. **Reports**: Each workbook contains:
               - **Pivoted Sheet**: Pivot table with barcode as rows, dates as columns (grouped by day)
               - **Detailed Report Sheet**: All transactions for that Parent Brand
            6. **Download**: Download individual workbooks or all workbooks as a ZIP file
            """)
    
    def render(self):
        """Render the complete BA Sales Report page"""
        st.title("💰 Laporan Sellout Beauty Advisor (BA)")
        st.markdown("### Pembuat Laporan Sellout untuk Beauty Advisor (BA) dengan data dari ERP.")
        
        self.render_date_organization_section()
        self.render_file_upload_section()
        self.render_error_section()
        self.render_summary_section()
        self.render_download_section()
        self.render_help_section()

def render_ba_sales_report_page():
    """Function to render BA Sales Report page (for backward compatibility)"""
    page = BASalesReportPage()
    page.render()
