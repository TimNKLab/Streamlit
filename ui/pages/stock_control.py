"""Stock Control page UI"""

import streamlit as st
import pandas as pd
import io
from datetime import datetime
from logic.stock_processor import StockProcessor

class StockControlPage:
    """Stock Control page UI component"""
    
    def __init__(self):
        self.processor = StockProcessor()
        self.init_session_state()
    
    def init_session_state(self):
        """Initialize session state variables"""
        if 'selected_files' not in st.session_state:
            st.session_state.selected_files = []
        if 'reference_file' not in st.session_state:
            st.session_state.reference_file = None
        if 'combined_data' not in st.session_state:
            st.session_state.combined_data = None
    
    def render_file_upload_section(self):
        """Render file upload section"""
        # Stock files upload
        col1, col2 = st.columns([4, 1])
        
        with col1:
            uploaded_files = st.file_uploader(
                "Masukkan file stock dari inventory adjustment di sini",
                type=['xlsx', 'xls'],
                accept_multiple_files=True,
                key="excel_files"
            )
        
        with col2:
            if st.session_state.selected_files:
                st.metric("Files", len(st.session_state.selected_files))
        
        # Reference file upload
        col1, col2 = st.columns([4, 1])
        
        with col1:
            reference_file = st.file_uploader(
                "Masukkan file penjualan 2 minggu terakhir di sini",
                type=['xlsx', 'xls'],
                key="reference_file_upload"
            )
        
        with col2:
            if reference_file:
                st.session_state.reference_file = reference_file
            if st.session_state.reference_file:
                st.metric("Ref", "✅")
        
        return uploaded_files, reference_file
    
    def render_options_section(self):
        """Render processing options"""
        col1, col2 = st.columns(2)
        
        with col1:
            include_source = st.checkbox("Add source filename", value=True)
        
        with col2:
            sort_option = st.radio(
                "Sortir :",
                options=["Urgency", "Brand/Name"],
                index=0,  # Default to Urgency
                horizontal=True
            )
        
        return include_source, sort_option
    
    def process_files(self, uploaded_files, include_source, sort_option):
        """Process the uploaded files"""
        if not uploaded_files and not st.session_state.selected_files:
            st.warning("⚠️ Belum upload file!")
            return
        
        if uploaded_files:
            st.session_state.selected_files = uploaded_files
        
        if not st.session_state.selected_files:
            st.error("❌ No files to process")
            return
        
        # Process files
        with st.spinner("Processing..."):
            try:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                total_files = len(st.session_state.selected_files)
                
                # Process stock files
                status_text.text("🔗 Merging files...")
                final_df = self.processor.process_stock_files(st.session_state.selected_files, include_source)
                
                status_text.text("🔄 Transforming...")
                
                # Sort data if requested
                if sort_option:
                    status_text.text("🔤 Sorting...")
                    final_df = self.processor.sort_stock_data(final_df, sort_option)
                
                # Process reference file lookup if provided
                if st.session_state.reference_file:
                    status_text.text("🔍 Reference lookup...")
                    final_df = self.processor.process_reference_lookup(final_df, st.session_state.reference_file)
                
                # Apply urgency sorting after status column is created
                if sort_option == "Urgency":
                    status_text.text("🔤 Sorting by urgency...")
                    final_df = self.processor.apply_urgency_sorting(final_df)
                
                st.session_state.combined_data = final_df
                
                progress_bar.progress(1.0)
                status_text.text("✅ Done!")
                
                st.success(f"🎉 Combined {len(st.session_state.selected_files)} files!")
                
                # Display metrics
                self.render_metrics(final_df)
                
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")
    
    def render_metrics(self, df):
        """Render metrics for processed data"""
        metrics = self.processor.get_stock_metrics(df)
        
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Rows", f"{metrics['total_rows']:,}")
        with col2:
            st.metric("Cols", metrics['total_columns'])
        with col3:
            if metrics['max_area'] is not None:
                st.metric("Max Area", metrics['max_area'])
        with col4:
            if metrics['urgent_count'] is not None:
                st.metric("URGENT", metrics['urgent_count'])
    
    def render_download_section(self):
        """Render download section"""
        if st.session_state.combined_data is not None:
            df = st.session_state.combined_data
            
            st.markdown("---")
            col1, col2 = st.columns(2)
            
            with col1:
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df.to_excel(writer, index=False, sheet_name='Combined Data')
                output.seek(0)
                
                st.download_button(
                    label="📥 Download Excel",
                    data=output,
                    file_name=f"combined_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                    type="primary"
                )
            
            with col2:
                csv = df.to_csv(index=False).encode('utf-8')
                
                st.download_button(
                    label="📄 Download CSV",
                    data=csv,
                    file_name=f"combined_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )
    
    def render_status_analysis(self):
        """Render status analysis if Status column exists"""
        if st.session_state.combined_data is not None:
            df = st.session_state.combined_data
            
            if 'Status' in df.columns:
                st.markdown("---")
                st.subheader("📈 Status Analysis")
                
                analysis = self.processor.get_status_analysis(df)
                
                if analysis:
                    col1, col2 = st.columns([1, 2])
                    
                    with col1:
                        st.write("**Summary:**")
                        for item in analysis:
                            st.metric(item['status'], f"{item['count']} ({item['percentage']:.1f}%)")
                    
                    with col2:
                        import plotly.express as px
                        
                        status_labels = [item['status'] for item in analysis]
                        status_values = [item['count'] for item in analysis]
                        
                        fig = px.pie(
                            values=status_values,
                            names=status_labels,
                            title="Status Distribution"
                        )
                        fig.update_traces(textposition='inside', textinfo='percent+label')
                        fig.update_layout(height=350, showlegend=False)
                        
                        st.plotly_chart(fig, use_container_width=True)
    
    def render(self):
        """Render the complete Stock Control page"""
        st.title("NK Stock Control")
        st.markdown("### Pembuat Laporan Stock Control")
        
        uploaded_files, reference_file = self.render_file_upload_section()
        include_source, sort_option = self.render_options_section()
        
        if st.button("Proses Data", type="primary", use_container_width=True):
            self.process_files(uploaded_files, include_source, sort_option)
        
        self.render_download_section()
        self.render_status_analysis()

def render_stock_control_page():
    """Function to render Stock Control page (for backward compatibility)"""
    page = StockControlPage()
    page.render()
