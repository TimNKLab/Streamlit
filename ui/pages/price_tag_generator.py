"""Price Tag Generator Streamlit Page"""

import streamlit as st
import pandas as pd
import math
from datetime import datetime
from logic.price_tag_service import PriceTagService
from utils.persistence import save_session, restore_session, clear_session, has_saved_session


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
        """Render database upload section."""

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
        st.title("Price Tag Generator 😸")
             
        self.render_database_section()
        self.render_items_table()
        self.render_pdf_section()
        
        # NK_PR_AUTOFOCUS: Process any pending auto-focus after full page render
        self._process_pending_focus()


def render_price_tag_page():
    """Function to render Price Tag page (for app.py integration)."""
    page = PriceTagPage()
    page.render()
