"""Price Tag Generator Streamlit Page"""

import streamlit as st
import pandas as pd
from datetime import datetime
from logic.price_tag_service import PriceTagService


@st.cache_resource(ttl=3600)  # Cache for 1 hour across all rerenders
def get_price_tag_service() -> PriceTagService:
    """Get or create cached PriceTagService - expensive resource cached globally."""
    print("[CACHE_RESOURCE] Creating PriceTagService (one-time init)...")
    service = PriceTagService()
    # Load database once
    service.load_database()
    return service


class PriceTagPage:
    """Price Tag Generator page UI component."""
    
    MAX_ITEMS = 20
    
    def __init__(self):
        # Get cached service (database loaded once per session)
        self.service = get_price_tag_service()
        self.init_session_state()
    
    def init_session_state(self):
        """Initialize session state variables."""
        if 'price_tag_items' not in st.session_state:
            st.session_state.price_tag_items = []
        if 'price_tag_custom_db' not in st.session_state:
            st.session_state.price_tag_custom_db = None
        if 'price_tag_pdf_ready' not in st.session_state:
            st.session_state.price_tag_pdf_ready = False
        if 'price_tag_pdf_bytes' not in st.session_state:
            st.session_state.price_tag_pdf_bytes = None
        if 'price_tag_focus_idx' not in st.session_state:
            st.session_state.price_tag_focus_idx = 0  # Track which row to focus
        if 'price_tag_items_hash' not in st.session_state:
            st.session_state.price_tag_items_hash = None
        if 'price_tag_batch_mode' not in st.session_state:
            st.session_state.price_tag_batch_mode = True  # Default: batch lookup (faster)
        
        # Initialize with 20 empty rows for perceived speed
        if not st.session_state.price_tag_items:
            st.session_state.price_tag_items = [
                self._create_empty_row(i) for i in range(self.MAX_ITEMS)
            ]
        
        # Check if items changed since last PDF generation
        current_hash = self._get_items_hash()
        if (st.session_state.price_tag_pdf_ready and 
            st.session_state.price_tag_items_hash != current_hash):
            # Items changed, invalidate PDF
            st.session_state.price_tag_pdf_ready = False
            st.session_state.price_tag_pdf_bytes = None
            st.session_state.price_tag_items_hash = None
    
    def _get_items_hash(self) -> str:
        """Get hash of current items to detect changes."""
        items = self._collect_valid_items()
        if not items:
            return ""
        return "|".join(f"{i['barcode']}:{i['name']}" for i in items)
    
    def _create_empty_row(self, idx: int = None) -> dict:
        """Create an empty item row structure."""
        if idx is None:
            idx = len(st.session_state.price_tag_items)
        return {
            'barcode': '',
            'name': '',
            'het': '',
            'diskon': '',
            'status': '',
            'in_system': False,
            'key_prefix': f"row_{idx}_{datetime.now().strftime('%H%M%S')}"
        }
    
    def _format_price_input(self, value: any) -> str:
        """Format price value for input display."""
        if value is None or value == '':
            return ''
        try:
            # Remove decimal if it's a whole number
            val = float(value)
            if val == int(val):
                return str(int(val))
            return str(val)
        except (ValueError, TypeError):
            return str(value)
    
    def render_database_section(self):
        """Render database upload section."""
        st.subheader("📦 Database Produk")
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            uploaded_file = st.file_uploader(
                "Upload file Excel database produk (opsional)",
                type=['xlsx', 'xls'],
                key="price_tag_db_upload",
                help="Kolom wajib: barcode, name, het. Kolom opsional: diskon"
            )
        
        with col2:
            if uploaded_file:
                st.session_state.price_tag_custom_db = uploaded_file
                # Reload database with custom file (one-time load)
                self.service.load_database(uploaded_file)
                st.success(f"✅ {self.service.product_count} produk")
            else:
                # Show current loaded count (database already loaded in get_price_tag_service)
                st.info(f"📄 {self.service.product_count} produk")
        
        st.markdown("---")
    
    def _should_lookup(self, barcode: str, idx: int) -> bool:
        """Check if we should perform lookup (debounce logic)."""
        barcode = barcode.strip()
        if not barcode or len(barcode) < 8:  # Most barcodes are 8+ digits
            return False
        
        # Prevent duplicate lookups of same barcode
        last_lookup = st.session_state.price_tag_items[idx].get('_last_lookup')
        if last_lookup == barcode:
            return False
        
        return True
    
    def _lookup_barcode(self, barcode: str, idx: int) -> bool:
        """Lookup barcode and update row data. Returns True if found."""
        barcode = barcode.strip()
        
        # Mark as looked up
        st.session_state.price_tag_items[idx]['_last_lookup'] = barcode
        
        product = self.service.lookup_product(barcode)
        
        if product:
            st.session_state.price_tag_items[idx]['name'] = product['name']
            st.session_state.price_tag_items[idx]['het'] = self._format_price_input(product['het'])
            st.session_state.price_tag_items[idx]['diskon'] = self._format_price_input(product.get('diskon'))
            st.session_state.price_tag_items[idx]['status'] = '✅ Ditemukan'
            st.session_state.price_tag_items[idx]['in_system'] = True
            # Regenerate key to force widget refresh with new values
            st.session_state.price_tag_items[idx]['key_prefix'] = f"row_{idx}_{datetime.now().strftime('%H%M%S%f')}"
            return True
        else:
            # Not found - require manual entry
            st.session_state.price_tag_items[idx]['status'] = '⚠️ Isi manual'
            st.session_state.price_tag_items[idx]['in_system'] = False
            return False
    
    def _batch_lookup(self):
        """Lookup all barcodes at once (batch mode) - much faster than individual lookups."""
        import time
        start = time.time()
        
        found_count = 0
        not_found = []
        
        for idx, item in enumerate(st.session_state.price_tag_items):
            barcode = item['barcode'].strip()
            if not barcode or item.get('name'):  # Skip empty or already looked up
                continue
            
            product = self.service.lookup_product(barcode)
            
            if product:
                item['name'] = product['name']
                item['het'] = self._format_price_input(product['het'])
                item['diskon'] = self._format_price_input(product.get('diskon'))
                item['status'] = '✅ Ditemukan'
                item['in_system'] = True
                # Regenerate key to force widget refresh
                item['key_prefix'] = f"row_{idx}_{datetime.now().strftime('%H%M%S%f')}"
                found_count += 1
            else:
                item['status'] = '⚠️ Isi manual'
                item['in_system'] = False
                not_found.append((idx + 1, barcode))
        
        elapsed = time.time() - start
        
        if found_count > 0:
            st.success(f"✅ Found {found_count} products in {elapsed:.2f}s")
        if not_found:
            st.warning(f"⚠️ {len(not_found)} items not found in database")
        
        st.rerun()
    
    def _remove_row(self, idx: int):
        """Remove a row at given index - callback version."""
        if len(st.session_state.price_tag_items) > 1:
            st.session_state.price_tag_items.pop(idx)
            # Adjust focus index if needed
            if st.session_state.price_tag_focus_idx >= len(st.session_state.price_tag_items):
                st.session_state.price_tag_focus_idx = len(st.session_state.price_tag_items) - 1
    
    def _clear_all(self):
        """Clear all rows - callback version."""
        st.session_state.price_tag_items = [
            self._create_empty_row(i) for i in range(self.MAX_ITEMS)
        ]
        st.session_state.price_tag_pdf_ready = False
        st.session_state.price_tag_pdf_bytes = None
        st.session_state.price_tag_focus_idx = 0
    
    def _add_row(self):
        """Add a new empty row - callback version."""
        if len(st.session_state.price_tag_items) < self.MAX_ITEMS:
            st.session_state.price_tag_items.append(self._create_empty_row())
        else:
            st.toast(f"Maksimum {self.MAX_ITEMS} item!", icon="⚠️")
    
    def render_items_table(self):
        """Render the items input table."""
        st.subheader("🏷️ Item Label Harga")
        
        # Header row
        header_cols = st.columns([0.8, 2.5, 3, 1.5, 1.5, 1.5, 0.8])
        headers = ['#', 'Barcode', 'Nama Produk', 'HET (Rp)', 'Diskon (Rp)', 'Status', '']
        for col, header in zip(header_cols, headers):
            col.markdown(f"**{header}**")
        
        # Data rows
        items_to_remove = None
        
        for idx, item in enumerate(st.session_state.price_tag_items):
            key_prefix = item['key_prefix']
            
            cols = st.columns([0.8, 2.5, 3, 1.5, 1.5, 1.5, 0.8])
            
            # Row number - highlight current focus row
            with cols[0]:
                is_focused = (idx == st.session_state.price_tag_focus_idx)
                if is_focused:
                    st.markdown(f"**➤ {idx + 1:02d}**")  # Arrow indicator for current row
                else:
                    st.markdown(f"**{idx + 1:02d}**")
            
            # Barcode input with debounced lookup
            with cols[1]:
                barcode = st.text_input(
                    "Barcode",
                    value=item['barcode'],
                    key=f"{key_prefix}_barcode",
                    label_visibility="collapsed",
                    placeholder="Scan/ketik..."
                )
                # Update stored value
                if barcode != item['barcode']:
                    item['barcode'] = barcode
                
                # Individual lookup only in non-batch mode
                if not st.session_state.price_tag_batch_mode:
                    if barcode.strip() and self._should_lookup(barcode, idx):
                        found = self._lookup_barcode(barcode, idx)
                        if found and idx < self.MAX_ITEMS - 1:
                            st.session_state.price_tag_focus_idx = idx + 1
                        st.rerun()
            
            # Name input
            with cols[2]:
                name = st.text_input(
                    "Nama",
                    value=item['name'],
                    key=f"{key_prefix}_name",
                    label_visibility="collapsed",
                    placeholder="Nama produk"
                )
                if name != item['name']:
                    item['name'] = name
            
            # HET input
            with cols[3]:
                het = st.text_input(
                    "HET",
                    value=item['het'],
                    key=f"{key_prefix}_het",
                    label_visibility="collapsed",
                    placeholder="0"
                )
                if het != item['het']:
                    item['het'] = het
            
            # Diskon input
            with cols[4]:
                diskon = st.text_input(
                    "Diskon",
                    value=item['diskon'],
                    key=f"{key_prefix}_diskon",
                    label_visibility="collapsed",
                    placeholder="0"
                )
                if diskon != item['diskon']:
                    item['diskon'] = diskon
            
            # Status indicator
            with cols[5]:
                status = item.get('status', '—')
                if '✅' in status:
                    st.success(status, icon="✅")
                elif '⚠️' in status:
                    st.warning(status, icon="⚠️")
                else:
                    st.caption(status)
            
            # Delete button
            with cols[6]:
                if st.button("✕", key=f"{key_prefix}_del", help="Hapus baris"):
                    items_to_remove = idx
        
        # Handle deletion outside the loop (no rerun needed, callback handles it)
        if items_to_remove is not None:
            self._remove_row(items_to_remove)
            st.rerun()
        
        # Action buttons
        st.markdown("---")
        
        # Mode toggle and batch lookup
        mode_cols = st.columns([1, 1, 1, 1])
        with mode_cols[0]:
            batch_mode = st.toggle("Batch Mode", value=st.session_state.price_tag_batch_mode, 
                                   help="Scan all barcodes first, then lookup all at once (faster)")
            if batch_mode != st.session_state.price_tag_batch_mode:
                st.session_state.price_tag_batch_mode = batch_mode
                st.rerun()
        
        with mode_cols[1]:
            if st.session_state.price_tag_batch_mode:
                unscanned = sum(1 for item in st.session_state.price_tag_items 
                              if item['barcode'].strip() and not item.get('name'))
                if unscanned > 0:
                    if st.button(f"🔍 Lookup {unscanned} Items", type="primary", use_container_width=True):
                        self._batch_lookup()
        
        with mode_cols[2]:
            st.button("➕ Tambah Baris", on_click=self._add_row, use_container_width=True)
        
        with mode_cols[3]:
            st.button("🗑️ Kosongkan", on_click=self._clear_all, type="secondary", use_container_width=True)
        
        # Item count
        filled_count = sum(1 for item in st.session_state.price_tag_items 
                         if item['barcode'].strip())
        st.metric("Item Scanned", f"{filled_count} / {self.MAX_ITEMS}")
    
    def _collect_valid_items(self) -> list:
        """Collect and validate items for PDF generation."""
        items = []
        
        for item in st.session_state.price_tag_items:
            barcode = item['barcode'].strip()
            if not barcode:
                continue
            
            name = item['name'].strip()
            
            # Parse prices
            try:
                het_val = item['het'].strip()
                het = int(float(het_val)) if het_val else None
            except (ValueError, TypeError):
                het = None
            
            try:
                diskon_val = item['diskon'].strip()
                diskon = int(float(diskon_val)) if diskon_val else None
            except (ValueError, TypeError):
                diskon = None
            
            # Debug logging
            print(f"[DEBUG] Item: barcode={barcode}, name={name[:20] if name else 'EMPTY'}, het={het}")
            
            # Require at least name and barcode
            if not name:
                print(f"[DEBUG] SKIPPED: no name for barcode {barcode}")
                continue
            
            items.append({
                'barcode': barcode,
                'name': name,
                'het': het,
                'diskon': diskon,
            })
        
        print(f"[DEBUG] Total valid items: {len(items)}")
        return items
    
    def generate_pdf(self):
        """Generate PDF from current items."""
        print(f"[DEBUG] generate_pdf called")
        items = self._collect_valid_items()
        print(f"[DEBUG] Collected {len(items)} items for PDF")
        
        if not items:
            st.error("❌ Tidak ada item valid untuk dicetak. Isi barcode dan nama produk terlebih dahulu.")
            return
        
        # Clear previous PDF before generating new one
        st.session_state.price_tag_pdf_ready = False
        st.session_state.price_tag_pdf_bytes = None
        
        try:
            with st.spinner("🔄 Membuat PDF..."):
                print(f"[DEBUG] Calling service.generate_pdf with {len(items)} items")
                pdf_bytes = self.service.generate_pdf(items)
                print(f"[DEBUG] PDF generated: {len(pdf_bytes)} bytes")
                
                # Validate PDF was created
                if not pdf_bytes or len(pdf_bytes) < 100:
                    st.error("❌ PDF yang dihasilkan kosong atau tidak valid")
                    return
                
                # Store in session state
                st.session_state.price_tag_pdf_bytes = pdf_bytes
                st.session_state.price_tag_pdf_ready = True
                st.session_state.price_tag_items_hash = self._get_items_hash()
                st.toast(f"✅ {len(items)} label berhasil dibuat!", icon="✅")
                
        except ImportError as e:
            st.error(f"❌ Library PDF tidak ditemukan: {str(e)}")
            st.info("💡 Install reportlab: `pip install reportlab`")
        except Exception as e:
            st.error(f"❌ Gagal membuat PDF: {str(e)}")
            import traceback
            st.error(traceback.format_exc())
    
    def render_pdf_section(self):
        """Render PDF generation and download section."""
        st.markdown("---")
        
        # Show item summary before generating
        items = self._collect_valid_items()
        if items:
            with st.expander(f"📋 Preview: {len(items)} item siap dicetak", expanded=False):
                preview_data = []
                for item in items:
                    preview_data.append({
                        'Barcode': item['barcode'],
                        'Nama': item['name'][:30] + '...' if len(item['name']) > 30 else item['name'],
                        'HET': self.service.format_price(item['het']),
                        'Diskon': self.service.format_price(item['diskon']) if item['diskon'] else '-'
                    })
                st.dataframe(preview_data, use_container_width=True, hide_index=True)
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            btn_text = f"🖨️ Generate PDF ({len(items)} item)" if items else "🖨️ Generate PDF"
            if st.button(btn_text, type="primary", use_container_width=True, disabled=not items):
                self.generate_pdf()
        
        # Download button - show when PDF is ready
        if st.session_state.get('price_tag_pdf_ready') and st.session_state.get('price_tag_pdf_bytes'):
            with col2:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                pdf_bytes = st.session_state.price_tag_pdf_bytes
                
                st.download_button(
                    label=f"⬇️ Download ({len(pdf_bytes)//1024} KB)",
                    data=pdf_bytes,
                    file_name=f"label_harga_{timestamp}.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True
                )
            
            st.caption(f"📄 PDF berisi {len(items)} label (6cm x 4cm) siap cetak")
            
            # Add clear PDF button
            if st.button("🗑️ Clear PDF", type="secondary"):
                st.session_state.price_tag_pdf_ready = False
                st.session_state.price_tag_pdf_bytes = None
                st.rerun()
        elif st.session_state.get('price_tag_pdf_ready'):
            # PDF marked ready but no bytes - error state
            st.error("❌ Error: PDF state corrupt. Click Generate again.")
            st.session_state.price_tag_pdf_ready = False
    
    def render(self):
        """Render the complete Price Tag Generator page."""
        st.title("🏷️ Price Tag Generator")
        st.markdown("Generator label harga 6cm x 4cm dengan auto-lookup database produk")
        
        self.render_database_section()
        self.render_items_table()
        self.render_pdf_section()


def render_price_tag_page():
    """Function to render Price Tag page (for app.py integration)."""
    page = PriceTagPage()
    page.render()
