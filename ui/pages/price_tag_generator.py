"""Price Tag Generator Streamlit Page"""

import streamlit as st
import pandas as pd
import math
import base64
import time
import traceback
import streamlit.components.v1 as components  # Import once at module level
from datetime import datetime
from logic.price_tag_service import PriceTagService
from utils.persistence import save_session, restore_session, clear_session
from odoo.vendor_bill_services import get_vendor_bill_lines_by_number
from utils.indexeddb_bridge import IndexedDBBridge

# Module-level constants
_BARCODE_COLUMN_NAMES = frozenset(['barcode', 'barcodes', 'kode', 'sku', 'code'])
_EMPTY_PDF_THRESHOLD = 100
_KEY_TS_FORMAT = '%H%M%S%f'


@st.cache_resource(
    ttl=3600,
    hash_funcs={PriceTagService: lambda x: "v3"}
)
def get_price_tag_service() -> PriceTagService:
    """Get or create cached PriceTagService - expensive resource cached globally."""
    service = PriceTagService()
    service.load_database()
    return service


def _now_key() -> str:
    """Cheap key suffix from current time."""
    return datetime.now().strftime(_KEY_TS_FORMAT)


def _parse_price(value) -> int | None:
    """Parse price value to int, returning None on failure."""
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        f = float(value)
        if math.isnan(f):
            return None
        return int(f)
    except (ValueError, TypeError):
        return None


def _format_price_input(value) -> str:
    """Format price value for input display."""
    if value is None or value == '':
        return ''
    try:
        if isinstance(value, float) and math.isnan(value):
            return ''
        val = float(value)
        return str(int(val)) if val == int(val) else str(val)
    except (ValueError, TypeError):
        return str(value)


class PriceTagPage:
    """Price Tag Generator page UI component."""

    MAX_ITEMS = 32

    def __init__(self):
        self.service = get_price_tag_service()
        # Cache for valid items within a single render cycle
        self._valid_items_cache: list | None = None
        self._init_session_state()

    # ------------------------------------------------------------------
    # Session state
    # ------------------------------------------------------------------

    def _init_session_state(self):
        """Initialize session state variables with localStorage persistence."""
        ss = st.session_state
        defaults = {
            'price_tag_items': [],
            'price_tag_custom_db': None,
            'price_tag_pdf_ready': False,
            'price_tag_pdf_bytes': None,
            'price_tag_focus_idx': 0,
            '_pending_focus_target': None,
            'price_tag_items_hash': None,
            'price_tag_batch_mode': False,
            'price_tag_restored': False,
            'thermal_vendor_bill_number': "",
            'thermal_lines': [],
            'thermal_manual_lines': [],
            'thermal_pdf_ready': False,
            'thermal_pdf_bytes': None,
            'thermal_rotate': True,
            'price_tag_size_preset': 'standard',  # 'standard' or 'mini'
            'price_tag_pdf_size_preset': None,
        }
        for key, val in defaults.items():
            if key not in ss:
                ss[key] = val

        # Restore from localStorage once
        if not ss.price_tag_restored:
            restored_items = restore_session()
            if restored_items:
                saved_count = len(restored_items)
                ss.price_tag_items = list(restored_items[:self.MAX_ITEMS])
                while len(ss.price_tag_items) < self.MAX_ITEMS:
                    ss.price_tag_items.append(
                        self._create_empty_row(len(ss.price_tag_items))
                    )
                st.toast(f"Kembalikan {saved_count} SKU dari sesi sebelumnya")
            ss.price_tag_restored = True

        # First-time initialization
        if not ss.price_tag_items:
            ss.price_tag_items = [
                self._create_empty_row(i) for i in range(self.MAX_ITEMS)
            ]

        # Invalidate PDF if items changed
        if ss.price_tag_pdf_ready:
            current_hash = self._get_items_hash()
            if ss.price_tag_items_hash != current_hash or ss.price_tag_pdf_size_preset != ss.price_tag_size_preset:
                ss.price_tag_pdf_ready = False
                ss.price_tag_pdf_bytes = None
                ss.price_tag_items_hash = None
                ss.price_tag_pdf_size_preset = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_items_hash(self) -> str:
        """Lightweight hash of current filled items."""
        parts = []
        for i in st.session_state.price_tag_items:
            if i['barcode']:
                parts.append(f"{i['barcode']}:{i['name']}")
        return "|".join(parts)

    def _create_empty_row(self, idx: int | None = None) -> dict:
        if idx is None:
            idx = len(st.session_state.price_tag_items)
        return {
            'barcode': '',
            'name': '',
            'het': '',
            'diskon': '',
            'status': '',
            'in_system': False,
            'key_prefix': f"row_{idx}_{_now_key()}",
        }

    # ------------------------------------------------------------------
    # Barcode lookup
    # ------------------------------------------------------------------

    def _should_lookup(self, barcode: str, idx: int) -> bool:
        """Check if lookup should be performed (debounce guard)."""
        n = len(barcode)
        if n != 6 and n < 8:
            return False
        return st.session_state.price_tag_items[idx].get('_last_lookup') != barcode

    def _apply_product_to_item(self, item: dict, product: dict, barcode_key: str):
        """Write product data into an item dict and refresh its key."""
        item['name'] = product['name']
        item['het'] = _format_price_input(product['het'])
        item['diskon'] = _format_price_input(product.get('diskon'))
        item['status'] = 'Ditemukan'
        item['in_system'] = True
        item['key_prefix'] = f"{barcode_key}_{_now_key()}"

    def _lookup_barcode(self, barcode: str, idx: int) -> bool:
        """Lookup barcode; returns True if found."""
        item = st.session_state.price_tag_items[idx]
        item['_last_lookup'] = barcode

        if len(barcode) == 6:
            product = self.service.lookup_product_by_suffix(barcode)
            if product and product.get("_status") == "AMBIGUOUS":
                item.update({
                    'barcode': '', 'name': '', 'het': '', 'diskon': '',
                    'status': 'Isi manual', 'in_system': False,
                    'key_prefix': f"row_{idx}_{_now_key()}",
                })
                st.toast(f"⚠️ Baris {idx+1}: Multiple SKUs dengan 6 digit akhir {barcode}", icon="⚠️")
                return False
            if product:
                item['barcode'] = barcode
                self._apply_product_to_item(item, product, f"row_{idx}")
                return True
        else:
            product = self.service.lookup_product(barcode)
            if product:
                self._apply_product_to_item(item, product, f"row_{idx}")
                return True

        item['status'] = 'Isi manual'
        item['in_system'] = False
        return False

    def _batch_lookup(self):
        """Lookup all unlookedup barcodes at once."""
        t0 = time.perf_counter()
        found_count = ambiguous = not_found = 0

        for idx, item in enumerate(st.session_state.price_tag_items):
            barcode = item['barcode'].strip()
            if not barcode or item.get('name'):
                continue

            if len(barcode) == 6:
                product = self.service.lookup_product_by_suffix(barcode)
                if product and product.get("_status") == "AMBIGUOUS":
                    item.update({
                        'barcode': '', 'name': '', 'het': '', 'diskon': '',
                        'status': 'Isi manual', 'in_system': False,
                        'key_prefix': f"row_{idx}_{_now_key()}",
                    })
                    ambiguous += 1
                    continue
            else:
                product = self.service.lookup_product(barcode)

            if product:
                self._apply_product_to_item(item, product, f"row_{idx}")
                found_count += 1
            else:
                item['status'] = 'Isi manual'
                item['in_system'] = False
                not_found += 1

        elapsed = time.perf_counter() - t0
        if found_count:
            st.success(f"✅ Found {found_count} products in {elapsed:.2f}s")
        if ambiguous:
            st.warning(f"⚠️ {ambiguous} items ambiguous (multiple SKUs with same last 6 digits)")
        if not_found:
            st.warning(f"⚠️ {not_found} items not found in database")

        # Focus first empty row
        for idx, item in enumerate(st.session_state.price_tag_items):
            if not item['barcode'].strip():
                st.session_state.price_tag_focus_idx = idx
                st.session_state._pending_focus_target = idx
                break

        st.rerun()

    # ------------------------------------------------------------------
    # Item collection (cached per render cycle)
    # ------------------------------------------------------------------

    def _collect_valid_items(self) -> list:
        """Collect valid items; cached for the current render cycle."""
        if self._valid_items_cache is not None:
            return self._valid_items_cache

        items = []
        for item in st.session_state.price_tag_items:
            barcode = item['barcode'].strip()
            name = item['name'].strip()
            if not barcode or not name:
                continue
            het = _parse_price(item['het'])
            diskon = _parse_price(item['diskon'])
            items.append({'barcode': barcode, 'name': name, 'het': het, 'diskon': diskon})

        self._valid_items_cache = items
        return items

    # ------------------------------------------------------------------
    # Row / state mutations
    # ------------------------------------------------------------------

    def _remove_row(self, idx: int):
        items = st.session_state.price_tag_items
        if len(items) > 1:
            items.pop(idx)
            if st.session_state.price_tag_focus_idx >= len(items):
                st.session_state.price_tag_focus_idx = len(items) - 1

    def _clear_all(self):
        st.session_state.price_tag_items = [
            self._create_empty_row(i) for i in range(self.MAX_ITEMS)
        ]
        st.session_state.price_tag_pdf_ready = False
        st.session_state.price_tag_pdf_bytes = None
        st.session_state.price_tag_focus_idx = 0
        st.session_state._pending_focus_target = None
        self._valid_items_cache = None
        clear_session()

    def _add_row(self):
        if len(st.session_state.price_tag_items) < self.MAX_ITEMS:
            st.session_state.price_tag_items.append(self._create_empty_row())
        else:
            st.toast(f"Maksimal {self.MAX_ITEMS} item!")

    # ------------------------------------------------------------------
    # Database / file upload section
    # ------------------------------------------------------------------

    def render_database_section(self):
        with st.expander("📁 Upload File Barcode (Excel/CSV)", expanded=False):
            st.caption("Upload file dengan kolom 'barcode' untuk generate price tag otomatis")
            uploaded_file = st.file_uploader(
                "Pilih file Excel atau CSV",
                type=['csv', 'xlsx', 'xls'],
                key="barcode_file_uploader",
            )
            if uploaded_file is not None:
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🚀 Proses & Generate PDF", type="primary", use_container_width=True):
                        self._process_barcode_file(uploaded_file)
                with col2:
                    if st.button("🧹 Clear Items", type="secondary", use_container_width=True):
                        st.session_state.price_tag_items = []
                        st.session_state.price_tag_pdf_ready = False
                        st.session_state.price_tag_pdf_bytes = None
                        self._valid_items_cache = None
                        st.rerun()

    def _process_barcode_file(self, uploaded_file):
        try:
            ext = uploaded_file.name.rsplit('.', 1)[-1].lower()
            df = pd.read_excel(uploaded_file) if ext in ('xlsx', 'xls') else pd.read_csv(uploaded_file)

            # Find barcode column
            barcode_col = next(
                (c for c in df.columns if c.lower().strip() in _BARCODE_COLUMN_NAMES),
                None,
            )
            if barcode_col is None:
                st.error(f"❌ Kolom 'barcode' tidak ditemukan. Kolom tersedia: {list(df.columns)}")
                return

            barcodes = df[barcode_col].dropna().astype(str).str.strip()
            barcodes = barcodes[barcodes != ''].tolist()
            if not barcodes:
                st.warning("⚠️ Tidak ada barcode valid di file")
                return

            total = len(barcodes)
            st.info(f"📊 Memproses {total} barcode...")

            items_list = []
            found_count = 0
            not_found_barcodes = []
            ts = _now_key()

            for idx, barcode in enumerate(barcodes):
                item = {
                    'barcode': barcode,
                    'name': '',
                    'het': '',
                    'diskon': '',
                    'status': 'Menunggu...',
                    'in_system': False,
                    '_last_lookup': barcode,  # Pre-mark as looked-up
                    'key_prefix': f"file_row_{idx}_{ts}",
                }

                product = (
                    self.service.lookup_product(barcode)
                    or self._try_suffix_lookup(barcode)
                )

                if product and product.get("_status") != "AMBIGUOUS":
                    item['name'] = product.get('name', '')
                    item['het'] = _format_price_input(product.get('het'))
                    item['diskon'] = _format_price_input(product.get('diskon'))
                    item['status'] = 'Ditemukan'
                    item['in_system'] = True
                    found_count += 1
                else:
                    item['status'] = 'Tidak ditemukan'
                    not_found_barcodes.append(barcode)

                items_list.append(item)

            st.session_state.price_tag_items = items_list
            self._valid_items_cache = None

            if found_count > 0:
                st.success(f"✅ {found_count} dari {total} produk ditemukan")
                if not_found_barcodes:
                    preview = ', '.join(not_found_barcodes[:10])
                    ellipsis = '...' if len(not_found_barcodes) > 10 else ''
                    st.warning(f"⚠️ {len(not_found_barcodes)} barcode tidak ditemukan: {preview}{ellipsis}")

                with st.spinner("🔄 Membuat PDF..."):
                    valid = self._collect_valid_items()
                    if valid:
                        size_preset = st.session_state.price_tag_size_preset
                        pdf_bytes = self.service.generate_pdf(valid, size_preset=size_preset)
                        st.session_state.price_tag_pdf_bytes = pdf_bytes
                        st.session_state.price_tag_pdf_ready = True
                        size_name = "48mm × 30mm" if size_preset == "standard" else "7mm × 2mm"
                        st.success(f"✅ PDF berhasil dibuat: {len(valid)} item ({size_name}, {len(pdf_bytes):,} bytes)")
                    else:
                        st.error("❌ Tidak ada item valid untuk dicetak")
            else:
                st.error("❌ Tidak ada produk yang ditemukan di database")

        except Exception as e:
            st.error(f"❌ Error memproses file: {e}")
            st.error(traceback.format_exc())

    def _try_suffix_lookup(self, barcode: str):
        """Try suffix-based lookup strategies; returns product or None."""
        if len(barcode) >= 6:
            suffix = barcode[-6:]
            product = self.service.lookup_product_by_suffix(suffix)
            if product and product.get("_status") != "AMBIGUOUS":
                return product
        # Try full barcode as suffix
        if len(barcode) > 6:
            product = self.service.lookup_product_by_suffix(barcode)
            if product and product.get("_status") != "AMBIGUOUS":
                return product
        return None

    # ------------------------------------------------------------------
    # Items table
    # ------------------------------------------------------------------

    def render_items_table(self):
        # Header
        header_cols = st.columns([0.8, 2.5, 3, 1.5, 1.5, 1.5, 0.8])
        for col, header in zip(
            header_cols,
            ['#', 'Barcode', 'Nama Produk', 'HET (Rp)', 'Diskon (Rp)', 'Status', ''],
        ):
            col.markdown(f"**{header}**")

        focus_idx = st.session_state.price_tag_focus_idx
        batch_mode = st.session_state.price_tag_batch_mode
        items_to_remove = None
        filled_count = 0

        for idx, item in enumerate(st.session_state.price_tag_items):
            key_prefix = item['key_prefix']
            is_focused = idx == focus_idx
            cols = st.columns([0.8, 2.5, 3, 1.5, 1.5, 1.5, 0.8])

            with cols[0]:
                st.markdown(f"**➤ {idx+1:02d}**" if is_focused else f"**{idx+1:02d}**")

            with cols[1]:
                barcode = st.text_input(
                    "Barcode", value=item['barcode'],
                    key=f"{key_prefix}_barcode",
                    label_visibility="collapsed",
                    placeholder="Scan/ketik...",
                )
                if barcode != item['barcode']:
                    item['barcode'] = barcode
                    self._valid_items_cache = None

                if not batch_mode and barcode.strip() and self._should_lookup(barcode, idx):
                    found = self._lookup_barcode(barcode, idx)
                    if found and idx < self.MAX_ITEMS - 1:
                        st.session_state.price_tag_focus_idx = idx + 1
                        st.session_state._pending_focus_target = idx + 1
                    self._valid_items_cache = None
                    st.rerun()

            with cols[2]:
                name = st.text_input(
                    "Nama", value=item['name'],
                    key=f"{key_prefix}_name",
                    label_visibility="collapsed",
                    placeholder="Nama produk",
                )
                if name != item['name']:
                    item['name'] = name
                    self._valid_items_cache = None

            with cols[3]:
                het = st.text_input(
                    "HET", value=item['het'],
                    key=f"{key_prefix}_het",
                    label_visibility="collapsed",
                    placeholder="0",
                )
                if het != item['het']:
                    item['het'] = het
                    self._valid_items_cache = None

            with cols[4]:
                diskon = st.text_input(
                    "Diskon", value=item['diskon'],
                    key=f"{key_prefix}_diskon",
                    label_visibility="collapsed",
                    placeholder="0",
                )
                if diskon != item['diskon']:
                    item['diskon'] = diskon
                    self._valid_items_cache = None

            with cols[5]:
                status = item.get('status', '—')
                if '✅' in status:
                    st.success(status, icon="✅")
                elif '⚠️' in status:
                    st.warning(status, icon="⚠️")
                else:
                    st.caption(status)

            with cols[6]:
                if st.button("✕", key=f"{key_prefix}_del", help="Hapus baris"):
                    items_to_remove = idx

            if item['barcode'].strip():
                filled_count += 1

        if items_to_remove is not None:
            self._remove_row(items_to_remove)
            self._valid_items_cache = None
            st.rerun()

        st.markdown("---")

        mode_cols = st.columns([1, 1, 1, 1])
        with mode_cols[0]:
            batch_mode_new = st.toggle(
                "Batch Mode", value=batch_mode,
                help="Scan all barcodes first, then lookup all at once (faster)",
            )
            if batch_mode_new != batch_mode:
                st.session_state.price_tag_batch_mode = batch_mode_new
                st.rerun()

        with mode_cols[1]:
            if batch_mode:
                unscanned = sum(
                    1 for it in st.session_state.price_tag_items
                    if it['barcode'].strip() and not it.get('name')
                )
                if unscanned > 0 and st.button(
                    f"🔍 Lookup {unscanned} Items", type="primary", use_container_width=True
                ):
                    self._batch_lookup()

        with mode_cols[2]:
            st.button("➕ Tambah Baris", on_click=self._add_row, use_container_width=True)

        with mode_cols[3]:
            st.button("🗑️ Kosongkan", on_click=self._clear_all, type="secondary", use_container_width=True)

        st.metric("Item Scanned", f"{filled_count} / {self.MAX_ITEMS}")

        # Best-effort session persistence
        try:
            save_session(st.session_state.price_tag_items)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # PDF generation
    # ------------------------------------------------------------------

    def generate_pdf(self):
        items = self._collect_valid_items()
        if not items:
            st.error("❌ Tidak ada item valid untuk dicetak.")
            return

        st.session_state.price_tag_pdf_ready = False
        st.session_state.price_tag_pdf_bytes = None

        try:
            with st.spinner("🔄 Membuat PDF..."):
                size_preset = st.session_state.price_tag_size_preset
                pdf_bytes = self.service.generate_pdf(items, size_preset=size_preset)

            if not pdf_bytes or len(pdf_bytes) < _EMPTY_PDF_THRESHOLD:
                st.error("❌ PDF yang dihasilkan kosong atau tidak valid")
                return

            st.session_state.price_tag_pdf_bytes = pdf_bytes
            st.session_state.price_tag_pdf_ready = True
            st.session_state.price_tag_items_hash = self._get_items_hash()
            st.session_state.price_tag_pdf_size_preset = size_preset
            st.toast(f"✅ {len(items)} label berhasil dibuat!", icon="✅")

        except ImportError as e:
            st.error(f"❌ Library PDF tidak ditemukan: {e}")
            st.info("💡 Install reportlab: `pip install reportlab`")
        except Exception as e:
            st.error(f"❌ Gagal membuat PDF: {e}")
            st.error(traceback.format_exc())

    # ------------------------------------------------------------------
    # PDF section (A4)
    # ------------------------------------------------------------------

    def render_pdf_section(self):
        st.markdown("---")
        
        # Tag size selector
        size_preset = st.selectbox(
            "📏 Ukuran Tag",
            options=["standard", "mini"],
            format_func=lambda x: "Standard (48mm × 30mm)" if x == "standard" else "Mini (7mm × 2mm)",
            index=0 if st.session_state.price_tag_size_preset == "standard" else 1,
            key="price_tag_size_selector",
        )
        if size_preset != st.session_state.price_tag_size_preset:
            st.session_state.price_tag_size_preset = size_preset
            st.session_state.price_tag_pdf_ready = False
            st.session_state.price_tag_pdf_bytes = None
            st.rerun()
        
        items = self._collect_valid_items()

        if items:
            with st.expander(f"📋 Preview: {len(items)} item siap dicetak", expanded=False):
                preview_data = [
                    {
                        'Barcode': it['barcode'],
                        'Nama': it['name'][:30] + ('...' if len(it['name']) > 30 else ''),
                        'HET': self.service.format_price(it['het']),
                        'Diskon': self.service.format_price(it['diskon']) if it['diskon'] else '-',
                    }
                    for it in items
                ]
                st.dataframe(preview_data, use_container_width=True, hide_index=True)

        col1, col2 = st.columns([3, 1])
        with col1:
            label = f"🖨️ Generate PDF ({len(items)} item)" if items else "🖨️ Generate PDF"
            if st.button(label, type="primary", use_container_width=True, disabled=not items):
                self.generate_pdf()

        ss = st.session_state
        if ss.get('price_tag_pdf_ready') and ss.get('price_tag_pdf_bytes'):
            with col2:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                pdf_bytes = ss.price_tag_pdf_bytes
                size_name = "48mm × 30mm" if ss.price_tag_size_preset == "standard" else "7mm × 2mm"
                st.download_button(
                    label=f"⬇️ Download ({len(pdf_bytes) // 1024} KB)",
                    data=pdf_bytes,
                    file_name=f"label_harga_{timestamp}.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )
            st.caption(f"📄 PDF berisi {len(items)} label ({size_name}) siap cetak")
            if st.button("🗑️ Clear PDF", type="secondary"):
                ss.price_tag_pdf_ready = False
                ss.price_tag_pdf_bytes = None
                st.rerun()
        elif ss.get('price_tag_pdf_ready'):
            st.error("❌ Error: PDF state corrupt. Click Generate again.")
            ss.price_tag_pdf_ready = False

    # ------------------------------------------------------------------
    # Thermal section
    # ------------------------------------------------------------------

    def _resolve_het_from_indexeddb(self, indexeddb: IndexedDBBridge, barcode: str, fallback_het) -> float | None:
        """Resolve HET via IndexedDB (bridge instance passed in to avoid per-call init)."""
        try:
            cached = indexeddb.get_product(barcode)
            if cached and cached.get("het") is not None:
                return float(cached["het"])
        except Exception:
            pass
        try:
            return float(fallback_het) if fallback_het is not None else None
        except (TypeError, ValueError):
            return None

    def _build_thermal_items(self, lines: list[dict]) -> list[dict]:
        """Build repeated thermal label items from line dicts."""
        # Single IndexedDBBridge instance for all lookups
        indexeddb = IndexedDBBridge()
        items = []
        for line in lines:
            barcode = str(line.get("barcode") or "").strip()
            name = str(line.get("name") or "").strip()
            if not barcode or not name:
                continue
            qty = _parse_price(line.get("qty")) or 0
            if qty <= 0:
                continue
            het = self._resolve_het_from_indexeddb(indexeddb, barcode, line.get("het"))
            entry = {"barcode": barcode, "name": name, "het": het}
            items.extend([entry] * qty)
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
            {"Print": True, "barcode": l.barcode, "name": l.name,
             "qty": l.qty, "het": l.het}
            for l in lines
        ]
        st.session_state.thermal_pdf_ready = False
        st.session_state.thermal_pdf_bytes = None

    def _init_manual_lines(self):
        if not st.session_state.thermal_manual_lines:
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
                w, h = (28.0, 18.0) if st.session_state.thermal_rotate else (18.0, 28.0)
                pdf_bytes = self.service.generate_thermal_labels_pdf(items, width_mm=w, height_mm=h)

            if not pdf_bytes or len(pdf_bytes) < _EMPTY_PDF_THRESHOLD:
                st.error("PDF yang dihasilkan kosong atau tidak valid")
                return

            st.session_state.thermal_pdf_bytes = pdf_bytes
            st.session_state.thermal_pdf_ready = True
            st.toast(f"✅ {len(items)} label thermal dibuat!", icon="✅")
        except Exception as e:
            st.error(f"Gagal membuat PDF thermal: {e}")

    def render_thermal_section(self):
        st.subheader("Thermal Label Generator (18mm x 28mm)")
        st.checkbox(
            "Rotate to landscape (28×18 horizontal)", key="thermal_rotate",
            help="Default is portrait 18×28. Check this if your printer feeds labels horizontally.",
        )

        with st.expander("🧾 Ambil dari Vendor Bill (Odoo)", expanded=True):
            st.text_input("Nomor Vendor Bill", key="thermal_vendor_bill_number")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Fetch Vendor Bill", type="primary", use_container_width=True):
                    self._fetch_vendor_bill()
            with col2:
                pass  # Empty column for layout balance

            remove_idx = None
            for idx, row in enumerate(st.session_state.thermal_lines):
                cols = st.columns([0.8, 2, 4, 1, 1.5, 0.8])
                key_base = f"vb_{idx}_{row.get('barcode', '')[:6]}"

                with cols[0]:
                    print_val = st.checkbox("", value=row.get("Print", True), key=f"{key_base}_print", label_visibility="collapsed")
                    row["Print"] = print_val

                with cols[1]:
                    st.caption(row.get("barcode", ""))

                with cols[2]:
                    st.caption(row.get("name", "")[:40])

                with cols[3]:
                    st.caption(str(row.get("qty", 0)))

                with cols[4]:
                    het = row.get("het")
                    st.caption(f"Rp {int(het):,}" if het else "-")

                with cols[5]:
                    if st.button("✕", key=f"{key_base}_del", help="Remove"):
                        remove_idx = idx

            if remove_idx is not None:
                st.session_state.thermal_lines.pop(remove_idx)
                st.rerun()

            selected = [r for r in st.session_state.thermal_lines if r.get("Print")]
            st.caption(f"Selected: {len(selected)} / {len(st.session_state.thermal_lines)} items")

            if st.button("Generate Thermal PDF (Vendor Bill)", type="primary"):
                self._generate_thermal_pdf(selected)

        with st.expander("⌨️ Input Manual Barcode + Qty", expanded=False):
            self._init_manual_lines()

            # Header
            hdr = st.columns([0.5, 3, 1.5, 0.8])
            hdr[0].markdown("**#**")
            hdr[1].markdown("**Barcode**")
            hdr[2].markdown("**Qty**")
            hdr[3].markdown("**Del**")

            remove_idx = None
            for idx, row in enumerate(st.session_state.thermal_manual_lines):
                cols = st.columns([0.5, 3, 1.5, 0.8])
                key_base = f"tm_{idx}"

                with cols[0]:
                    st.caption(f"{idx+1}")

                with cols[1]:
                    barcode = st.text_input("", value=row.get("barcode", ""), key=f"{key_base}_bc", label_visibility="collapsed")
                    if barcode != row.get("barcode", ""):
                        row["barcode"] = barcode
                        # Auto-lookup on valid length
                        if len(barcode.strip()) >= 6:
                            product = self.service.lookup_product(barcode.strip())
                            if product:
                                row["_name"] = product.get("name", "")
                                row["_het"] = product.get("het")

                with cols[2]:
                    qty = st.number_input("", value=int(row.get("qty", 1)), min_value=0, step=1, key=f"{key_base}_qty", label_visibility="collapsed")
                    if qty != row.get("qty", 1):
                        row["qty"] = qty

                with cols[3]:
                    if st.button("✕", key=f"{key_base}_del", help="Remove"):
                        remove_idx = idx

                # Show lookup result inline
                if row.get("_name"):
                    st.caption(f"✓ {row['_name'][:30]}")

            if remove_idx is not None:
                st.session_state.thermal_manual_lines.pop(remove_idx)
                st.rerun()

            # Add row button
            if st.button("➕ Add Row", use_container_width=True):
                st.session_state.thermal_manual_lines.append({"barcode": "", "qty": 1})
                st.rerun()

            if st.button("Generate Thermal PDF (Manual)", type="primary"):
                manual_lines = []
                for row in st.session_state.thermal_manual_lines:
                    barcode = str(row.get("barcode") or "").strip()
                    if not barcode:
                        continue
                    # Use cached lookup or fetch
                    name = row.get("_name")
                    het = row.get("_het")
                    if not name:
                        product = self.service.lookup_product(barcode)
                        if product:
                            name = product.get("name", "")
                            het = product.get("het")
                    if name:
                        manual_lines.append({
                            "barcode": barcode,
                            "name": name,
                            "qty": row.get("qty", 1),
                            "het": het,
                        })
                self._generate_thermal_pdf(manual_lines)

        ss = st.session_state
        if ss.get("thermal_pdf_ready") and ss.get("thermal_pdf_bytes"):
            with st.expander("⚠️ Pengaturan Print (WAJIB di Edge/Windows)", expanded=True):
                st.markdown("""
**Label: 28mm × 18mm (Landscape)** ← Default (check "Rotate" untuk 18×28)

Saat dialog print Edge terbuka, atur:
1. **More settings** → **Paper Size** → Pilih/buat **"28×18mm"** atau **"User Defined"**
2. **Scale** → Pilih **"Actual size"** atau **"100%"** (bukan "Fit to page")
3. **Margins** → Pilih **"None"** atau minimum
4. **Options** → **Auto-rotate pages** → **OFF**
                """)

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                col_print, col_dl = st.columns(2)
                with col_print:
                    if st.button("🖨️ Print Thermal", type="primary", use_container_width=True):
                        try:
                            pdf_b64 = base64.b64encode(ss.thermal_pdf_bytes).decode("ascii")
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
                        except Exception as e:
                            st.error(f"Gagal membuka print dialog: {e}")

                with col_dl:
                    st.download_button(
                        label="⬇️ Download Thermal PDF",
                        data=ss.thermal_pdf_bytes,
                        file_name=f"thermal_labels_{timestamp}.pdf",
                        mime="application/pdf",
                        type="secondary",
                        use_container_width=True,
                    )

    # ------------------------------------------------------------------
    # Auto-focus
    # ------------------------------------------------------------------

    def _inject_focus_js(self, target_idx: int):
        """Inject JS to focus the barcode input at target_idx."""
        try:
            input_index = target_idx * 4
            components.html(
                f"""<div></div><script>
                setTimeout(function(){{
                  try{{
                    var doc = window.top.document || window.parent.document;
                    var inp = doc.querySelectorAll('input[type="text"]')[{input_index}];
                    if(inp){{ inp.focus(); inp.select(); }}
                  }}catch(e){{ console.log('[AutoFocus] '+e.message); }}
                }}, 500);
                </script>""",
                height=0,
            )
        except Exception:
            pass

    def _process_pending_focus(self):
        focus_target = st.session_state.get('_pending_focus_target')
        if focus_target is not None:
            self._inject_focus_js(focus_target)
            st.session_state._pending_focus_target = None

    # ------------------------------------------------------------------
    # Top-level render
    # ------------------------------------------------------------------

    def render(self):
        st.title("Price Tag Generator 😸")

        col1, col2 = st.columns([4, 1])
        with col1:
            st.caption(f"📦 Database: {self.service.product_count:,} harga sudah terupdate")
        with col2:
            if st.button("🔄 Update harga", type="secondary",
                         help="Force reload price data from file"):
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

        self._process_pending_focus()


def render_price_tag_page():
    """Render Price Tag page (for app.py integration)."""
    PriceTagPage().render()