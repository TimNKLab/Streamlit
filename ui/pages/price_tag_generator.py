"""Price Tag Generator Streamlit Page"""

import streamlit as st
import pandas as pd
import math
import base64
from datetime import datetime
from logic.price_tag_service import PriceTagService
from utils.persistence import save_session, restore_session, clear_session, has_saved_session
from odoo.vendor_bill_services import get_vendor_bill_lines_by_number
from utils.indexeddb_bridge import IndexedDBBridge


@st.cache_resource(ttl=3600, hash_funcs={PriceTagService: lambda x: "v3"})  # Cache for 1 hour, v3 with barcode_suffix column
def get_price_tag_service() -> PriceTagService:
    """Get or create cached PriceTagService - expensive resource cached globally."""
    print("[CACHE_RESOURCE] Creating PriceTagService (one-time init)...")
    service = PriceTagService()
    # Load database once
    service.load_database()
    return service


class PriceTagPage:
    """Price Tag Generator page UI component."""
    
    MAX_ITEMS = 32
    
    
    def __init__(self):
        # Get cached service (database loaded once per session)
        self.service = get_price_tag_service()
        self.init_session_state()
    
    def init_session_state(self):
        """Initialize session state variables with localStorage persistence."""
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
        if '_pending_focus_target' not in st.session_state:
            st.session_state._pending_focus_target = None  # For auto-focus after rerun
        if 'price_tag_items_hash' not in st.session_state:
            st.session_state.price_tag_items_hash = None
        if 'price_tag_batch_mode' not in st.session_state:
            st.session_state.price_tag_batch_mode = False  # Default: single lookup (slower but more accurate)
        if 'price_tag_restored' not in st.session_state:
            st.session_state.price_tag_restored = False

        if 'thermal_vendor_bill_number' not in st.session_state:
            st.session_state.thermal_vendor_bill_number = ""
        if 'thermal_lines' not in st.session_state:
            st.session_state.thermal_lines = []
        if 'thermal_manual_lines' not in st.session_state:
            st.session_state.thermal_manual_lines = []
        if 'thermal_pdf_ready' not in st.session_state:
            st.session_state.thermal_pdf_ready = False
        if 'thermal_pdf_bytes' not in st.session_state:
            st.session_state.thermal_pdf_bytes = None
        if 'thermal_rotate' not in st.session_state:
            st.session_state.thermal_rotate = True  # Default: landscape (28×18) - works for this printer
        # Try to restore from localStorage on first load
        if not st.session_state.price_tag_restored:
            restored_items = restore_session()
            if restored_items:
                # Restore saved items, filling up to MAX_ITEMS
                saved_count = len(restored_items)
                if saved_count > 0:
                    # Create empty rows to fill
                    st.session_state.price_tag_items = restored_items[:self.MAX_ITEMS]
                    # Pad with empty rows if needed
                    while len(st.session_state.price_tag_items) < self.MAX_ITEMS:
                        st.session_state.price_tag_items.append(
                            self._create_empty_row(len(st.session_state.price_tag_items))
                        )
                    st.toast(f"Kembalikan {saved_count} SKU dari sesi sebelumnya")
            st.session_state.price_tag_restored = True
        
        # Initialize with empty rows if still empty (first time, no restore)
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
        if value is None or value == '' or (isinstance(value, float) and math.isnan(value)):
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
        """Render database upload section with barcode file upload."""
        with st.expander("📁 Upload File Barcode (Excel/CSV)", expanded=False):
            st.caption("Upload file dengan kolom 'barcode' untuk generate price tag otomatis")
            uploaded_file = st.file_uploader(
                "Pilih file Excel atau CSV",
                type=['csv', 'xlsx', 'xls'],
                key="barcode_file_uploader"
            )
            
            if uploaded_file is not None:
                col1, col2 = st.columns([1, 1])
                with col1:
                    if st.button("🚀 Proses & Generate PDF", type="primary", use_container_width=True):
                        self._process_barcode_file(uploaded_file)
                with col2:
                    if st.button("🧹 Clear Items", type="secondary", use_container_width=True):
                        st.session_state.price_tag_items = []
                        st.session_state.price_tag_pdf_ready = False
                        st.session_state.price_tag_pdf_bytes = None
                        st.rerun()

    def _process_barcode_file(self, uploaded_file):
        """Process uploaded barcode file and generate PDF."""
        try:
            # Read file based on extension
            file_ext = uploaded_file.name.split('.')[-1].lower()
            if file_ext in ['xlsx', 'xls']:
                df = pd.read_excel(uploaded_file)
            else:
                df = pd.read_csv(uploaded_file)
            
            # Validate required column
            barcode_col = None
            for col in df.columns:
                if col.lower().strip() in ['barcode', 'barcodes', 'kode', 'sku', 'code']:
                    barcode_col = col
                    break
            
            if barcode_col is None:
                st.error(f"❌ Kolom 'barcode' tidak ditemukan. Kolom tersedia: {list(df.columns)}")
                return
            
            # Get barcodes (drop empty values)
            barcodes = df[barcode_col].dropna().astype(str).str.strip()
            barcodes = barcodes[barcodes != ''].tolist()
            
            if not barcodes:
                st.warning("⚠️ Tidak ada barcode valid di file")
                return
            
            st.info(f"📊 Memproses {len(barcodes)} barcode...")
            
            # Clear existing items and add new ones
            st.session_state.price_tag_items = []
            found_count = 0
            not_found_barcodes = []
            
            # Process ALL barcodes from file (NO LIMIT - unlimited batch PDF generation)
            total_barcodes = len(barcodes)
            st.info(f"📊 Memproses {total_barcodes} barcode...")
            
            for idx, barcode in enumerate(barcodes):
                # Create item with barcode
                item = {
                    'barcode': barcode,
                    'name': '',
                    'het': '',
                    'diskon': '',
                    'status': 'Menunggu...',
                    'in_system': False,
                    '_last_lookup': None,
                    'key_prefix': f"file_row_{idx}_{datetime.now().strftime('%H%M%S%f')}"
                }
                
                # Lookup product - try multiple strategies
                product = None
                barcode_clean = barcode.strip()
                
                # Strategy 1: Try full barcode exact match first (most reliable)
                product = self.service.lookup_product(barcode_clean)
                
                # Strategy 2: If not found and barcode is 6+ chars, try last 6 digits
                if not product and len(barcode_clean) >= 6:
                    suffix = barcode_clean[-6:]
                    product = self.service.lookup_product_by_suffix(suffix)
                    if product and product.get("_status") == "AMBIGUOUS":
                        product = None  # Don't use ambiguous matches
                
                # Strategy 3: If barcode is longer than 6, also try checking if the full barcode IS the suffix
                if not product and len(barcode_clean) > 6:
                    # Some systems store full barcode, some store last 6 - try both
                    product = self.service.lookup_product_by_suffix(barcode_clean)
                    if product and product.get("_status") == "AMBIGUOUS":
                        product = None
                
                if product and product.get("_status") != "AMBIGUOUS":
                    item['name'] = product.get('name', '')
                    item['het'] = self._format_price_input(product.get('het'))
                    item['diskon'] = self._format_price_input(product.get('diskon'))
                    item['status'] = 'Ditemukan'
                    item['in_system'] = True
                    found_count += 1
                else:
                    item['status'] = 'Tidak ditemukan'
                    not_found_barcodes.append(barcode)
                
                item['_last_lookup'] = barcode
                st.session_state.price_tag_items.append(item)
            
            # Show results
            if found_count > 0:
                st.success(f"✅ {found_count} dari {len(barcodes)} produk ditemukan")
                if not_found_barcodes:
                    st.warning(f"⚠️ {len(not_found_barcodes)} barcode tidak ditemukan: {', '.join(not_found_barcodes[:10])}{'...' if len(not_found_barcodes) > 10 else ''}")
                
                # Auto-generate PDF
                with st.spinner("🔄 Membuat PDF..."):
                    items = self._collect_valid_items()
                    if items:
                        pdf_bytes = self.service.generate_pdf(items)
                        st.session_state.price_tag_pdf_bytes = pdf_bytes
                        st.session_state.price_tag_pdf_ready = True
                        st.success(f"✅ PDF berhasil dibuat: {len(items)} item ({len(pdf_bytes):,} bytes)")
                    else:
                        st.error("❌ Tidak ada item valid untuk dicetak")
            else:
                st.error("❌ Tidak ada produk yang ditemukan di database")
                
        except Exception as e:
            st.error(f"❌ Error memproses file: {str(e)}")
            import traceback
            print(f"[ERROR] _process_barcode_file: {traceback.format_exc()}")

    def _should_lookup(self, barcode: str, idx: int) -> bool:
        """Check if we should perform lookup (debounce logic)."""
        barcode = barcode.strip()
        if not barcode:
            return False

        # Allow 6-char suffix lookups OR full barcodes (8+ chars)
        is_6_char_suffix = len(barcode) == 6
        is_full_barcode = len(barcode) >= 8
        if not (is_6_char_suffix or is_full_barcode):
            print(f"[SHOULD_LOOKUP] Row {idx}: BLOCKED - length not 6 or 8+ (len={len(barcode)})")
            return False

        # Prevent duplicate lookups of same barcode
        last_lookup = st.session_state.price_tag_items[idx].get('_last_lookup')
        if last_lookup == barcode:
            print(f"[SHOULD_LOOKUP] Row {idx}: BLOCKED - already looked up '{barcode}'")
            return False

        print(f"[SHOULD_LOOKUP] Row {idx}: ALLOW lookup for '{barcode}'")
        return True
    
    def _lookup_barcode(self, barcode: str, idx: int) -> bool:
        """Lookup barcode using fuzzy suffix matching. Returns True if found."""
        barcode = barcode.strip()

        # Mark as looked up
        st.session_state.price_tag_items[idx]['_last_lookup'] = barcode

        # Use fuzzy lookup (expects last 6 chars of barcode)
        if len(barcode) == 6:
            print(f"[UI_LOOKUP] Calling lookup_product_by_suffix('{barcode}')")
            product = self.service.lookup_product_by_suffix(barcode)
            print(f"[UI_LOOKUP] Got product: {product is not None}, type={type(product)}, keys={list(product.keys()) if product else 'N/A'}")

            if product and product.get("_status") == "AMBIGUOUS":
                # Ambiguous match - clear barcode, show manual entry required
                st.session_state.price_tag_items[idx]['barcode'] = ''
                st.session_state.price_tag_items[idx]['name'] = ''
                st.session_state.price_tag_items[idx]['het'] = ''
                st.session_state.price_tag_items[idx]['diskon'] = ''
                st.session_state.price_tag_items[idx]['status'] = 'Isi manual'
                st.session_state.price_tag_items[idx]['in_system'] = False
                st.toast(f"⚠️ Baris {idx+1}: Multiple SKUs dengan 6 digit akhir {barcode}", icon="⚠️")
                # Regenerate key to force widget refresh (clear the input)
                st.session_state.price_tag_items[idx]['key_prefix'] = f"row_{idx}_{datetime.now().strftime('%H%M%S%f')}"
                return False

            if product:
                print(f"[UI_LOOKUP] Found product: {product['name'][:20]}")
                st.session_state.price_tag_items[idx]['barcode'] = barcode  # Keep the 6-digit input
                st.session_state.price_tag_items[idx]['name'] = product['name']
                st.session_state.price_tag_items[idx]['het'] = self._format_price_input(product['het'])
                st.session_state.price_tag_items[idx]['diskon'] = self._format_price_input(product.get('diskon'))
                st.session_state.price_tag_items[idx]['status'] = 'Ditemukan'
                st.session_state.price_tag_items[idx]['in_system'] = True
                # Regenerate key to force widget refresh with new values
                st.session_state.price_tag_items[idx]['key_prefix'] = f"row_{idx}_{datetime.now().strftime('%H%M%S%f')}"
                print(f"[UI_LOOKUP] Set item[{idx}].name = '{product['name'][:20]}'")
                return True

        # Fallback: try exact match for backward compatibility (non-6-digit inputs)
        product = self.service.lookup_product(barcode)

        if product:
            st.session_state.price_tag_items[idx]['name'] = product['name']
            st.session_state.price_tag_items[idx]['het'] = self._format_price_input(product['het'])
            st.session_state.price_tag_items[idx]['diskon'] = self._format_price_input(product.get('diskon'))
            st.session_state.price_tag_items[idx]['status'] = 'Ditemukan'
            st.session_state.price_tag_items[idx]['in_system'] = True
            st.session_state.price_tag_items[idx]['key_prefix'] = f"row_{idx}_{datetime.now().strftime('%H%M%S%f')}"
            return True
        else:
            # Not found - require manual entry
            st.session_state.price_tag_items[idx]['status'] = 'Isi manual'
            st.session_state.price_tag_items[idx]['in_system'] = False
            return False
    
    def _batch_lookup(self):
        """Lookup all barcodes at once (batch mode) - much faster than individual lookups."""
        import time
        start = time.time()

        found_count = 0
        not_found = []
        ambiguous = []

        for idx, item in enumerate(st.session_state.price_tag_items):
            barcode = item['barcode'].strip()
            if not barcode or item.get('name'):  # Skip empty or already looked up
                continue

            # Use fuzzy lookup for 6-char suffix inputs
            if len(barcode) == 6:
                product = self.service.lookup_product_by_suffix(barcode)

                if product and product.get("_status") == "AMBIGUOUS":
                    item['barcode'] = ''
                    item['name'] = ''
                    item['het'] = ''
                    item['diskon'] = ''
                    item['status'] = 'Isi manual'
                    item['in_system'] = False
                    item['key_prefix'] = f"row_{idx}_{datetime.now().strftime('%H%M%S%f')}"
                    ambiguous.append((idx + 1, barcode))
                    continue
            else:
                product = self.service.lookup_product(barcode)

            if product:
                item['name'] = product['name']
                item['het'] = self._format_price_input(product['het'])
                item['diskon'] = self._format_price_input(product.get('diskon'))
                item['status'] = 'Ditemukan'
                item['in_system'] = True
                # Regenerate key to force widget refresh
                item['key_prefix'] = f"row_{idx}_{datetime.now().strftime('%H%M%S%f')}"
                found_count += 1
            else:
                item['status'] = 'Isi manual'
                item['in_system'] = False
                not_found.append((idx + 1, barcode))

        elapsed = time.time() - start

        if found_count > 0:
            st.success(f"✅ Found {found_count} products in {elapsed:.2f}s")
        if ambiguous:
            st.warning(f"⚠️ {len(ambiguous)} items ambiguous (multiple SKUs with same last 6 digits)")
        if not_found:
            st.warning(f"⚠️ {len(not_found)} items not found in database")

        # NK_PR_AUTOFOCUS: After batch lookup, focus first empty row for continued scanning
        first_empty_idx = None
        for idx, item in enumerate(st.session_state.price_tag_items):
            if not item['barcode'].strip():
                first_empty_idx = idx
                break
        
        if first_empty_idx is not None:
            st.session_state.price_tag_focus_idx = first_empty_idx
            # NK_PR_AUTOFOCUS: Queue focus for first empty row (processed after rerun)
            st.session_state._pending_focus_target = first_empty_idx

        st.rerun()
    
    def _remove_row(self, idx: int):
        """Remove a row at given index - callback version."""
        if len(st.session_state.price_tag_items) > 1:
            st.session_state.price_tag_items.pop(idx)
            # Adjust focus index if needed
            if st.session_state.price_tag_focus_idx >= len(st.session_state.price_tag_items):
                st.session_state.price_tag_focus_idx = len(st.session_state.price_tag_items) - 1
    
    def _clear_all(self):
        """Clear all rows and localStorage - callback version."""
        st.session_state.price_tag_items = [
            self._create_empty_row(i) for i in range(self.MAX_ITEMS)
        ]
        st.session_state.price_tag_pdf_ready = False
        st.session_state.price_tag_pdf_bytes = None
        st.session_state.price_tag_focus_idx = 0
        st.session_state._pending_focus_target = None
        # Clear persisted session
        clear_session()
    
    def _add_row(self):
        """Add a new empty row - callback version."""
        if len(st.session_state.price_tag_items) < self.MAX_ITEMS:
            st.session_state.price_tag_items.append(self._create_empty_row())
        else:
            st.toast(f"Maksimal {self.MAX_ITEMS} item!")
    
    def render_items_table(self):
        """Render the items input table."""
       
        # Header row
        header_cols = st.columns([0.8, 2.5, 3, 1.5, 1.5, 1.5, 0.8])
        headers = ['#', 'Barcode', 'Nama Produk', 'HET (Rp)', 'Diskon (Rp)', 'Status', '']
        for col, header in zip(header_cols, headers):
            col.markdown(f"**{header}**")
        
        # Data rows
        items_to_remove = None
        
        # Debug: Check first few items
        for i, debug_item in enumerate(st.session_state.price_tag_items[:3]):
            if debug_item['barcode'].strip():
                print(f"[RENDER] Row {i}: barcode={debug_item['barcode']}, name={debug_item['name'][:15] if debug_item['name'] else 'EMPTY'}")
        
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
                # Highlight focused row with border
                is_focused = (idx == st.session_state.price_tag_focus_idx)
                border_style = "border: 2px solid #FF6B35; border-radius: 4px; padding: 2px;" if is_focused else ""

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
                        print(f"[RENDER] About to call _lookup_barcode('{barcode}', {idx})")
                        found = self._lookup_barcode(barcode, idx)
                        print(f"[RENDER] _lookup_barcode returned: {found}")
                        if found and idx < self.MAX_ITEMS - 1:
                            st.session_state.price_tag_focus_idx = idx + 1
                            # NK_PR_AUTOFOCUS: Queue focus for next row (processed after rerun)
                            st.session_state._pending_focus_target = idx + 1
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
        
        # Auto-save to localStorage (best-effort, doesn't block UI)
        try:
            save_session(st.session_state.price_tag_items)
        except Exception:
            pass  # Silently fail - persistence is best-effort

        # Auto-focus indicator - visual (➤ arrow) + JavaScript focus injection
        # Programmatic focus is implemented via components.v1.html() forum hack
    
    def _inject_focus_js(self, target_idx: int):
        """Inject JavaScript to focus barcode input at target_idx.
        
        Uses the forum hack: https://discuss.streamlit.io/t/set-focus-to-a-text-input/34778
        Each row has 4 text inputs (barcode, name, het, diskon), so barcode is at index target_idx * 4.
        """
        try:
            import streamlit.components.v1 as components
            # Calculate the input index: 4 inputs per row, barcode is first
            input_index = target_idx * 4
            
            # Single execution with delay - runs after DOM is ready
            # Try window.top first (may work better with CSP), fallback to window.parent
            html_content = f"""<div></div><script>
                setTimeout(function() {{
                    try {{
                        var doc = window.top.document || window.parent.document;
                        var inputs = doc.querySelectorAll('input[type="text"]');
                        var target = inputs[{input_index}];
                        if (target) {{
                            target.focus();
                            target.select();
                            console.log('[AutoFocus] SUCCESS row {target_idx}');
                        }} else {{
                            console.log('[AutoFocus] FAIL: no input at {input_index} (found ' + inputs.length + ')');
                        }}
                    }} catch(e) {{
                        console.log('[AutoFocus] ERROR: ' + e.message);
                    }}
                }}, 500);
            </script>"""
            
            components.html(html_content, height=0)
            print(f"[AutoFocus] Injected for row {target_idx}")
        except Exception as e:
            print(f"[AutoFocus] Error: {e}")
    
    def _process_pending_focus(self):
        """Process any pending auto-focus request after page render."""
        focus_target = st.session_state.get('_pending_focus_target')
        if focus_target is not None:
            print(f"[AutoFocus] Processing pending focus for row {focus_target}")
            self._inject_focus_js(focus_target)
            # Clear it so we don't focus again on next rerun
            st.session_state._pending_focus_target = None
    
    def _collect_valid_items(self) -> list:
        """Collect and validate items for PDF generation."""
        items = []
        
        for item in st.session_state.price_tag_items:
            barcode = item['barcode'].strip()
            if not barcode:
                continue
            
            name = item['name'].strip()
            
            # Parse prices - handle both string and numeric types
            try:
                het_val = item['het']
                if isinstance(het_val, str):
                    het_val = het_val.strip()
                het = int(float(het_val)) if het_val else None
            except (ValueError, TypeError, AttributeError):
                het = None
            
            try:
                diskon_val = item['diskon']
                if isinstance(diskon_val, str):
                    diskon_val = diskon_val.strip()
                diskon = int(float(diskon_val)) if diskon_val else None
            except (ValueError, TypeError, AttributeError):
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

    def _resolve_het_from_indexeddb(self, barcode: str, fallback_het: float | None) -> float | None:
        try:
            indexeddb = IndexedDBBridge()
            cached = indexeddb.get_product(barcode)
            if cached and cached.get("het") is not None:
                return float(cached["het"])
        except Exception:
            pass
        if fallback_het is None:
            return None
        try:
            return float(fallback_het)
        except (TypeError, ValueError):
            return None

    def _build_thermal_items(self, lines: list[dict]) -> list[dict]:
        items: list[dict] = []
        for line in lines:
            barcode = str(line.get("barcode") or "").strip()
            name = str(line.get("name") or "").strip()
            qty_val = line.get("qty")
            het_val = line.get("het")

            if not barcode or not name:
                continue

            try:
                qty = int(float(qty_val))
            except (TypeError, ValueError):
                qty = 0

            if qty <= 0:
                continue

            het = self._resolve_het_from_indexeddb(barcode, het_val)

            for _ in range(qty):
                items.append({"barcode": barcode, "name": name, "het": het})
        return items

    def _fetch_vendor_bill(self):
        bill_number = (st.session_state.thermal_vendor_bill_number or "").strip()
        if not bill_number:
            st.warning("Masukkan nomor vendor bill")
            return

        with st.spinner("Mengambil vendor bill dari Odoo..."):
            lines = get_vendor_bill_lines_by_number(bill_number)

        if not lines:
            st.error("Vendor bill tidak ditemukan / tidak ada line dengan barcode")
            st.session_state.thermal_lines = []
            return

        st.session_state.thermal_lines = [
            {"Print": True, "barcode": l.barcode, "name": l.name, "qty": l.qty, "het": l.het}
            for l in lines
        ]
        st.session_state.thermal_pdf_ready = False
        st.session_state.thermal_pdf_bytes = None

    def _init_manual_lines(self):
        if st.session_state.thermal_manual_lines:
            return
        st.session_state.thermal_manual_lines = [
            {"barcode": "", "qty": 1} for _ in range(12)
        ]

    def _generate_thermal_pdf(self, source_lines: list[dict]):
        items = self._build_thermal_items(source_lines)
        if not items:
            st.error("Tidak ada item untuk dicetak")
            return

        st.session_state.thermal_pdf_ready = False
        st.session_state.thermal_pdf_bytes = None

        try:
            with st.spinner("Membuat PDF thermal..."):
                # Default: portrait 18x28 (18mm wide, 28mm tall) - feeds vertically
                # Rotated: landscape 28x18 (28mm wide, 18mm tall) - feeds horizontally
                if st.session_state.thermal_rotate:
                    pdf_bytes = self.service.generate_thermal_labels_pdf(items, width_mm=28.0, height_mm=18.0)
                else:
                    pdf_bytes = self.service.generate_thermal_labels_pdf(items, width_mm=18.0, height_mm=28.0)

            if not pdf_bytes or len(pdf_bytes) < 100:
                st.error("PDF yang dihasilkan kosong atau tidak valid")
                return

            st.session_state.thermal_pdf_bytes = pdf_bytes
            st.session_state.thermal_pdf_ready = True
            st.toast(f"✅ {len(items)} label thermal dibuat!", icon="✅")
        except Exception as e:
            st.error(f"Gagal membuat PDF thermal: {e}")

    def render_thermal_section(self):
        st.subheader("Thermal Label Generator (18mm x 28mm)")

        st.checkbox("Rotate to landscape (28×18 horizontal)", key="thermal_rotate", help="Default is portrait 18×28. Check this if your printer feeds labels horizontally.")

        with st.expander("🧾 Ambil dari Vendor Bill (Odoo)", expanded=True):
            st.text_input("Nomor Vendor Bill", key="thermal_vendor_bill_number")
            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("Fetch Vendor Bill", type="primary", use_container_width=True):
                    self._fetch_vendor_bill()
            with col2:
                if st.button("Clear Vendor Bill", type="secondary", use_container_width=True):
                    st.session_state.thermal_lines = []
                    st.session_state.thermal_pdf_ready = False
                    st.session_state.thermal_pdf_bytes = None

            if st.session_state.thermal_lines:
                thermal_df = pd.DataFrame(st.session_state.thermal_lines)
                edited = st.data_editor(
                    thermal_df,
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Print": st.column_config.CheckboxColumn("Print", default=True),
                        "barcode": st.column_config.TextColumn("Barcode"),
                        "name": st.column_config.TextColumn("Name", width="large"),
                        "qty": st.column_config.NumberColumn("Qty", min_value=0, step=1),
                        "het": st.column_config.NumberColumn("HET"),
                    },
                    key="thermal_vendor_bill_editor",
                )
                st.session_state.thermal_lines = edited.to_dict("records")

                if st.button("Generate Thermal PDF (Vendor Bill)", type="primary"):
                    selected = [r for r in st.session_state.thermal_lines if r.get("Print")]
                    self._generate_thermal_pdf(selected)

        with st.expander("⌨️ Input Manual Barcode + Qty", expanded=False):
            self._init_manual_lines()
            manual_df = pd.DataFrame(st.session_state.thermal_manual_lines)
            edited = st.data_editor(
                manual_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "barcode": st.column_config.TextColumn("Barcode"),
                    "qty": st.column_config.NumberColumn("Qty", min_value=0, step=1),
                },
                key="thermal_manual_editor",
            )
            st.session_state.thermal_manual_lines = edited.to_dict("records")

            if st.button("Generate Thermal PDF (Manual)", type="primary"):
                manual_lines = []
                for row in st.session_state.thermal_manual_lines:
                    barcode = str(row.get("barcode") or "").strip()
                    if not barcode:
                        continue
                    product = self.service.lookup_product(barcode)
                    if not product:
                        continue
                    manual_lines.append(
                        {
                            "barcode": barcode,
                            "name": product.get("name", ""),
                            "qty": row.get("qty", 0),
                            "het": product.get("het"),
                        }
                    )
                self._generate_thermal_pdf(manual_lines)

        if st.session_state.get("thermal_pdf_ready") and st.session_state.get("thermal_pdf_bytes"):
            # Print settings guide
            with st.expander("⚠️ Pengaturan Print (WAJIB di Edge/Windows)", expanded=True):
                st.markdown("""
                **Label: 28mm × 18mm (Landscape)** ← Default (check "Rotate" untuk 18×28)

                Saat dialog print Edge terbuka, atur:
                1. **More settings** → **Paper Size** → Pilih/buat **"28×18mm"** atau **"User Defined"**
                2. **Scale** → Pilih **"Actual size"** atau **"100%"** (bukan "Fit to page")
                3. **Margins** → Pilih **"None"** atau minimum
                4. **Options** → **Auto-rotate pages** → **OFF**

                Jika tidak diatur, printer akan scale ke ukuran A4/half A4 dan label jadi terlalu besar.
                """)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            col_print, col_dl = st.columns([1, 1])

            with col_print:
                if st.button("🖨️ Print Thermal", type="primary", use_container_width=True):
                    try:
                        import streamlit.components.v1 as components

                        pdf_b64 = base64.b64encode(st.session_state.thermal_pdf_bytes).decode("ascii")
                        components.html(
                            f"""
                            <script>
                              (function() {{
                                try {{
                                  const b64 = "{pdf_b64}";
                                  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
                                  const blob = new Blob([bytes], {{ type: 'application/pdf' }});
                                  const url = URL.createObjectURL(blob);
                                  const w = window.open(url, '_blank');
                                  if (!w) {{
                                    alert('Popup blocked. Allow popups for this site, then click Print again.');
                                    return;
                                  }}
                                  const t = setInterval(() => {{
                                    try {{
                                      if (w.document && w.document.readyState === 'complete') {{
                                        clearInterval(t);
                                        w.focus();
                                        w.print();
                                      }}
                                    }} catch (e) {{
                                      // cross-origin not expected for blob, but keep retrying
                                    }}
                                  }}, 250);
                                }} catch (e) {{
                                  console.error(e);
                                  alert('Failed to open print window: ' + (e.message || e));
                                }}
                              }})();
                            </script>
                            """,
                            height=0,
                        )
                    except Exception as e:
                        st.error(f"Gagal membuka print dialog: {e}")

            with col_dl:
                st.download_button(
                    label="⬇️ Download Thermal PDF",
                    data=st.session_state.thermal_pdf_bytes,
                    file_name=f"thermal_labels_{timestamp}.pdf",
                    mime="application/pdf",
                    type="secondary",
                    use_container_width=True,
                )

<<<<<<< HEAD
=======
            with col_escpos:
                # Generate ESC/POS on button click
                if st.button("🔌 Generate ESC/POS", type="secondary", use_container_width=True):
                    try:
                        items = self._build_thermal_items(st.session_state.thermal_lines if st.session_state.get('thermal_lines') else [])
                        if items:
                            escpos_bytes = self.service.generate_escpos_labels(
                                items,
                                width_mm=18.0 if st.session_state.thermal_rotate else 28.0,
                                height_mm=28.0 if st.session_state.thermal_rotate else 18.0,
                            )
                            st.session_state.thermal_escpos_ready = True
                            st.session_state.thermal_escpos_bytes = escpos_bytes
                            st.toast(f"✅ ESC/POS commands generated: {len(escpos_bytes)} bytes", icon="🔌")
                        else:
                            st.error("Tidak ada item untuk generate ESC/POS")
                    except ImportError as e:
                        st.error(f"Library ESC/POS tidak tersedia: {e}")
                        st.info("Install: `pip install python-escpos pyusb`")
                    except Exception as e:
                        st.error(f"Gagal generate ESC/POS: {e}")

        # ESC/POS Download Section
        if st.session_state.get("thermal_escpos_ready") and st.session_state.get("thermal_escpos_bytes"):
            st.divider()
            st.caption("📟 ESC/POS Direct Printing (bypass PDF rasterization)")
            
            escpos_col1, escpos_col2, escpos_col3 = st.columns([1, 1, 1])
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            with escpos_col1:
                st.download_button(
                    label="⬇️ Download .bin (raw)",
                    data=st.session_state.thermal_escpos_bytes,
                    file_name=f"thermal_labels_{timestamp}.bin",
                    mime="application/octet-stream",
                    type="primary",
                    use_container_width=True,
                )
            
            with escpos_col2:
                if st.button("💾 Save to session_data/", type="secondary", use_container_width=True):
                    try:
                        save_path = f"session_data/thermal_labels_{timestamp}.bin"
                        self.service.save_escpos_to_file(st.session_state.thermal_escpos_bytes, save_path)
                        st.success(f"Saved to {save_path}")
                    except Exception as e:
                        st.error(f"Gagal save: {e}")
            
            with escpos_col3:
                # USB Direct Print (requires pyusb and proper driver - LOCAL ONLY)
                if st.button("🔌 Print USB Direct", type="secondary", use_container_width=True):
                    try:
                        success = self.service.print_escpos_to_usb(st.session_state.thermal_escpos_bytes)
                        if success:
                            st.success("✅ Data sent to printer!")
                        else:
                            st.error("❌ Failed to send to printer. Check USB connection and drivers.")
                            st.info("Tip: Install libusbK driver for Xprinter on Windows")
                    except Exception as e:
                        st.error(f"USB print error: {e}")
            
            # Cloud Print via Web Serial API (works from anywhere)
            escpos_cloud_col1, escpos_cloud_col2 = st.columns([1, 1])
            with escpos_cloud_col1:
                if st.button("☁️ Print via Browser (Cloud)", type="primary", use_container_width=True):
                    try:
                        from utils.escpos_cloud_bridge import ESCPOSCloudBridge
                        bridge = ESCPOSCloudBridge()
                        result = bridge.print_direct(st.session_state.thermal_escpos_bytes)
                        if result.get('success'):
                            st.success("🖨️ Check your browser for USB printer selection!")
                            st.info("Your browser will send ESC/POS commands directly to the printer.")
                        else:
                            st.error(f"❌ {result.get('error', 'Failed to open print dialog')}")
                    except Exception as e:
                        st.error(f"Cloud print error: {e}")
            
            with escpos_cloud_col2:
                with st.expander("ℹ️ About Cloud Printing"):
                    st.markdown("""
                    **Browser Direct Printing**
                    
                    This uses the **Web Serial API** to send ESC/POS commands directly from your browser to the USB printer.
                    
                    **Benefits:**
                    - ✅ Works from Streamlit Cloud (no local Python needed)
                    - ✅ No driver changes required
                    - ✅ Chrome/Edge native support
                    
                    **Requirements:**
                    - Chrome or Edge browser (v89+)
                    - HTTPS or localhost connection
                    - Grant USB permission when prompted
                    """)
>>>>>>> 0c6e432 (rollup)
    
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
        st.title("Price Tag Generator 😸")
        
        # Show database status and refresh button
        col1, col2 = st.columns([4, 1])
        with col1:
            st.caption(f"📦 Database: {self.service.product_count:,} harga sudah terupdate")
        with col2:
            if st.button("🔄 Update harga", type="secondary", help="Force reload price data from file"):
                # Clear the mtime to force reload on next lookup
                self.service._last_load_mtime = None
                self.service._load_parquet_to_memory()
                st.success("Harga sudah terupdate!")
             
        tab_a4, tab_thermal = st.tabs(["A4 Price Tag", "Thermal 18x28mm"])
        with tab_a4:
            self.render_database_section()
            self.render_items_table()
            self.render_pdf_section()
        with tab_thermal:
            self.render_thermal_section()
        
        # NK_PR_AUTOFOCUS: Process any pending auto-focus after full page render
        self._process_pending_focus()


def render_price_tag_page():
    """Function to render Price Tag page (for app.py integration)."""
    page = PriceTagPage()
    page.render()
