"""Price Tag Generator Service"""

import os
import io
from datetime import datetime
from typing import Optional, Dict, Any, List
import pandas as pd
import streamlit as st

# PDF generation imports
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas as pdfcanvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib import colors as rcolors
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False


# Top/fast-moving products - hardcoded for instant lookup (O(1))
# Add your best-selling SKUs here - these load without any file I/O
TOP_PRODUCTS = {
    "8991001010049": {"name": "Indomie Goreng Original", "het": 3500, "diskon": None},
    "8991001017215": {"name": "Indomie Kuah Ayam Bawang", "het": 3500, "diskon": None},
    "8886388100017": {"name": "Mie Sedaap Goreng Original", "het": 3200, "diskon": 2800},
    "8998009010309": {"name": "Biscuit Roma Kelapa", "het": 8500, "diskon": 7500},
    "8999999123456": {"name": "Teh Botol Sosro 350ml", "het": 5000, "diskon": 4500},
    "8990000123401": {"name": "Aqua Galon 19L", "het": 22000, "diskon": None},
    "8993979123450": {"name": "Minyak Goreng Bimoli 2L", "het": 38000, "diskon": 35000},
    "8999909123456": {"name": "Sabun Lifebouy Batang", "het": 4500, "diskon": None},
    "8850006792626": {"name": "Ovaltine Sachet 32g", "het": 3000, "diskon": 2500},
    "8886032100109": {"name": "SilverQueen Chunky 58g", "het": 12500, "diskon": 11000},
    # Add more top movers here...
}

# For 50k+ product catalogs, use DuckDB (faster than SQLite)
# Run this once to convert Excel: python -c "import duckdb; duckdb.execute(\"CREATE TABLE products AS SELECT * FROM read_parquet('data/products.parquet')\")"
# Or: duckdb.execute("COPY (SELECT * FROM read_excel('data/products.xlsx')) TO 'data/products.duckdb'")

# Try importing DuckDB
try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False


class PriceTagService:
    """Service for price tag generation and product database management."""
    
    # Tag dimensions (6cm x 4cm)
    TAG_W = 5 * cm  # slightly smaller to fit on page
    TAG_H = 3 * cm
    
    def __init__(self, fallback_db_path: str = "data/products.xlsx", duckdb_path: str = "data/products.duckdb", auto_convert: bool = True, use_memory_cache: bool = True):
        self.fallback_db_path = fallback_db_path
        self.duckdb_path = duckdb_path
        self._products: Dict[str, Dict[str, Any]] = {}
        self._duckdb_conn = None
        self._font_loaded = False
        self._use_duckdb = False
        self._use_memory_cache = use_memory_cache
        self._load_fonts()
        
        # Auto-convert Excel to Parquet if needed
        if auto_convert and HAS_DUCKDB:
            self._auto_convert_if_needed()
        
        # Aggressive: Load Parquet into memory for instant lookups
        if use_memory_cache:
            self._load_parquet_to_memory()
    
    def _load_fonts(self):
        """Load Poppins fonts if available."""
        global MAIN_FONT, MAIN_FONT_BOLD
        self.MAIN_FONT = "Helvetica"
        self.MAIN_FONT_BOLD = "Helvetica-Bold"
        
        if HAS_REPORTLAB:
            # Try to load Poppins fonts
            try:
                if os.path.exists('Poppins-Bold.ttf'):
                    pdfmetrics.registerFont(TTFont('Poppins-Bold', 'Poppins-Bold.ttf'))
                    self.MAIN_FONT_BOLD = "Poppins-Bold"
                if os.path.exists('Poppins-Regular.ttf'):
                    pdfmetrics.registerFont(TTFont('Poppins-Regular', 'Poppins-Regular.ttf'))
                    self.MAIN_FONT = "Poppins-Regular"
            except Exception:
                pass  # Use default Helvetica
        
        self._font_loaded = True
    
    def _auto_convert_if_needed(self):
        """Auto-convert Excel to Parquet if Parquet doesn't exist or is older than Excel."""
        try:
            parquet_path = self.duckdb_path.replace('.duckdb', '.parquet')
            excel_exists = os.path.exists(self.fallback_db_path)
            parquet_exists = os.path.exists(parquet_path)
            
            if not excel_exists:
                return  # No Excel to convert
            
            # Check if conversion needed
            needs_conversion = False
            if not parquet_exists:
                needs_conversion = True
                print(f"[PARQUET] Not found, will create from Excel")
            else:
                # Compare modification times
                excel_mtime = os.path.getmtime(self.fallback_db_path)
                parquet_mtime = os.path.getmtime(parquet_path)
                if excel_mtime > parquet_mtime:
                    needs_conversion = True
                    print(f"[PARQUET] Excel is newer, will reconvert")
            
            if needs_conversion:
                self._convert_excel_to_parquet()
                
        except Exception as e:
            print(f"[PARQUET] Auto-conversion failed: {e}")
    
    def _convert_excel_to_parquet(self):
        """Convert Excel to Parquet (compressed, fast columnar format)."""
        try:
            parquet_path = self.duckdb_path.replace('.duckdb', '.parquet')
            print(f"[PARQUET] Converting {self.fallback_db_path}...")
            df = pd.read_excel(self.fallback_db_path)
            
            # Clean data
            df = df.dropna(subset=['barcode', 'name', 'het'])
            df['barcode'] = df['barcode'].astype(str).str.strip()
            
            print(f"[PARQUET] Loaded {len(df)} products from Excel")
            
            # Write to Parquet (compressed)
            df.to_parquet(parquet_path, index=False, compression='zstd')
            
            excel_size = os.path.getsize(self.fallback_db_path) / 1024 / 1024
            parquet_size = os.path.getsize(parquet_path) / 1024 / 1024
            
            print(f"[PARQUET] Created: {parquet_path}")
            print(f"[PARQUET] Size: {excel_size:.1f}MB (Excel) -> {parquet_size:.1f}MB (Parquet)")
            
        except Exception as e:
            print(f"[PARQUET] Conversion error: {e}")
    
    def _load_parquet_to_memory(self):
        """Load Parquet into memory dict for instant O(1) lookups."""
        try:
            # Skip if already loaded
            if self._products:
                print(f"[CACHE] Products already in memory ({len(self._products)} items), skipping reload")
                return
            
            parquet_path = self.duckdb_path.replace('.duckdb', '.parquet')
            if not os.path.exists(parquet_path):
                return
            
            print(f"[CACHE] Loading Parquet into memory...")
            import time
            start = time.time()
            
            # Read Parquet into DataFrame then convert to dict
            df = pd.read_parquet(parquet_path)
            
            # Convert to dict for O(1) lookups
            for _, row in df.iterrows():
                barcode = str(row.get('barcode', '')).strip()
                if barcode:
                    self._products[barcode] = {
                        'name': str(row.get('name', '')),
                        'het': self._to_float(row.get('het')),
                        'diskon': self._to_float(row.get('diskon')) if 'diskon' in df.columns else None,
                    }
            
            elapsed = time.time() - start
            print(f"[CACHE] Loaded {len(self._products)} products into memory in {elapsed:.2f}s")
            print(f"[CACHE] Lookup speed: ~0.000001s (1 microsecond)")
            
        except Exception as e:
            print(f"[CACHE] Failed to load: {e}")
    
    @staticmethod
    @st.cache_data(ttl=300)  # Cache for 5 minutes
    def _load_excel_cached(file_bytes: bytes) -> pd.DataFrame:
        """Cached Excel loader - much faster on repeated loads."""
        import io
        return pd.read_excel(io.BytesIO(file_bytes))
    
    def _load_duckdb(self) -> bool:
        """Try to load Parquet via DuckDB. Returns True if successful."""
        parquet_path = self.duckdb_path.replace('.duckdb', '.parquet')
        if not HAS_DUCKDB or not os.path.exists(parquet_path):
            return False
        
        try:
            # Connect to in-memory DuckDB and create view for Parquet
            self._duckdb_conn = duckdb.connect(":memory:")
            self._duckdb_conn.execute(f"CREATE VIEW products AS SELECT * FROM read_parquet('{parquet_path}')")
            # Test query
            result = self._duckdb_conn.execute("SELECT COUNT(*) FROM products").fetchone()
            self._use_duckdb = True
            print(f"[DuckDB] Connected to Parquet: {result[0]} products")
            return True
        except Exception as e:
            print(f"[DuckDB] Failed to load Parquet: {e}")
            self._use_duckdb = False
            if self._duckdb_conn:
                self._duckdb_conn.close()
                self._duckdb_conn = None
            return False
    
    def _lookup_duckdb(self, barcode: str) -> Optional[Dict[str, Any]]:
        """Lookup product in Parquet via DuckDB."""
        if not self._use_duckdb or not self._duckdb_conn:
            return None
        
        try:
            result = self._duckdb_conn.execute(
                "SELECT barcode, name, het, diskon FROM products WHERE barcode = ?",
                [barcode]
            ).fetchone()
            
            if result:
                return {
                    'name': result[1],
                    'het': self._to_float(result[2]),
                    'diskon': self._to_float(result[3]),
                }
            return None
        except Exception:
            return None
    
    def load_database(self, uploaded_file=None, use_hardcoded: bool = False, use_duckdb: bool = True) -> Dict[str, Dict[str, Any]]:
        """Load product database from uploaded file, Parquet via DuckDB, Excel, or hardcoded data.
        
        Priority:
        1. Uploaded file (if provided)
        2. Parquet via DuckDB (if exists) - fastest for 50k+ products
        3. Excel fallback file (if exists)
        4. Hardcoded data (fastest startup, no file I/O)
        """
        self._products.clear()
        self._use_duckdb = False
        
        # Option 1: Use hardcoded data only
        if use_hardcoded:
            return TOP_PRODUCTS.copy()
        
        try:
            # Option 2: Try Parquet + DuckDB first (fastest for large catalogs)
            if use_duckdb and self._load_duckdb():
                return {}  # DuckDB queries Parquet directly, no memory load
            
            df = None
            
            # Option 3: Load from uploaded file (cached)
            if uploaded_file is not None:
                file_bytes = uploaded_file.getvalue()
                df = self._load_excel_cached(file_bytes)
            
            # Option 4: Load from fallback Excel file (cached)
            elif os.path.exists(self.fallback_db_path):
                with open(self.fallback_db_path, 'rb') as f:
                    file_bytes = f.read()
                df = self._load_excel_cached(file_bytes)
            
            # Option 5: Ultimate fallback - hardcoded data
            else:
                return TOP_PRODUCTS.copy()
            
            # Validate and load from DataFrame
            if df is not None:
                required_cols = ['barcode', 'name', 'het']
                missing_cols = [col for col in required_cols if col not in df.columns]
                if missing_cols:
                    st.error(f"Missing required columns: {', '.join(missing_cols)}")
                    return TOP_PRODUCTS.copy()
                
                # Load products from DataFrame
                for _, row in df.iterrows():
                    barcode = str(row.get('barcode', '')).strip()
                    if barcode:
                        self._products[barcode] = {
                            'name': str(row.get('name', '')),
                            'het': self._to_float(row.get('het')),
                            'diskon': self._to_float(row.get('diskon')) if 'diskon' in df.columns else None,
                        }
                
                return self._products
            
        except Exception as e:
            st.warning(f"Could not load database: {str(e)}. Using hardcoded fallback.")
            return TOP_PRODUCTS.copy()
    
    @staticmethod
    def _to_float(value) -> Optional[float]:
        """Convert value to float or None."""
        if value is None or value == "" or str(value).lower() == "null":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    
    def lookup_product(self, barcode: str) -> Optional[Dict[str, Any]]:
        """Lookup product by barcode. Priority: Memory cache > TOP_PRODUCTS > DuckDB > None."""
        barcode = barcode.strip()
        
        # Priority 1: Memory cache (loaded from Parquet) - FASTEST (~1 microsecond)
        if self._products:
            return self._products.get(barcode)
        
        # Priority 2: Hardcoded top products - instant
        if barcode in TOP_PRODUCTS:
            return TOP_PRODUCTS[barcode]
        
        # Priority 3: DuckDB query (should not reach here if memory cache loaded)
        if self._use_duckdb:
            result = self._lookup_duckdb(barcode)
            if result:
                return result
        
        return None
    
    @property
    def product_count(self) -> int:
        # Count unique products (avoid double-counting if same barcode in both)
        all_barcodes = set(TOP_PRODUCTS.keys()) | set(self._products.keys())
        return len(all_barcodes)
    
    @staticmethod
    def format_price(price: Optional[float]) -> str:
        """Format price as Indonesian Rupiah."""
        if price is None:
            return ""
        try:
            price_int = int(price)
            return f"Rp {price_int:,}".replace(",", ".")
        except (ValueError, TypeError):
            return str(price)
    
    @staticmethod
    def today_str() -> str:
        """Return today's date as string."""
        return datetime.now().strftime("%d-%m-%Y")
    
    def _hex_to_rgb(self, hex_str: str) -> tuple:
        """Convert hex color to RGB tuple."""
        hex_str = hex_str.lstrip("#")
        return tuple(int(hex_str[i:i+2], 16) / 255 for i in (0, 2, 4))
    
    def _fit_fontsize(self, c, text: str, font: str, max_w: float, 
                     size_max: int = 28, size_min: int = 6) -> int:
        """Return largest font size where text fits in max_w."""
        if not HAS_REPORTLAB:
            return size_min
        for fs in range(size_max, size_min - 1, -1):
            if pdfmetrics.stringWidth(text, font, fs) <= max_w:
                return fs
        return size_min
    
    def _draw_text_block(self, c, text: str, font: str, color_hex: str,
                         x: float, y: float, w: float, h: float,
                         size_max: int = 28, size_min: int = 6, valign: str = "middle"):
        """Draw text block centered with auto-sizing."""
        if not text or not HAS_REPORTLAB:
            return
        
        r, g, b = self._hex_to_rgb(color_hex)
        c.setFillColorRGB(r, g, b)
        
        for fs in range(size_max, size_min - 1, -1):
            leading = fs * 1.25
            # Simple word wrap
            words = text.split()
            lines = []
            cur_line = ""
            for word in words:
                test = (cur_line + " " + word).strip()
                if pdfmetrics.stringWidth(test, font, fs) <= w - 2:
                    cur_line = test
                else:
                    if cur_line:
                        lines.append(cur_line)
                    cur_line = word
            if cur_line:
                lines.append(cur_line)
            
            total_h = len(lines) * leading
            if total_h <= h or fs == size_min:
                # Draw lines
                if valign == "middle":
                    start_y = y + h / 2 + total_h / 2 - leading * 0.8
                elif valign == "top":
                    start_y = y + h - leading * 0.2
                else:  # bottom
                    start_y = y + total_h - leading * 0.8
                
                c.setFont(font, fs)
                for line in lines:
                    lw = pdfmetrics.stringWidth(line, font, fs)
                    c.drawString(x + (w - lw) / 2, start_y, line)
                    start_y -= leading
                return
    
    def _draw_tag(self, c, item: Dict[str, Any], tx: float, ty: float):
        """Draw a single price tag at position (tx, ty)."""
        if not HAS_REPORTLAB:
            return
        
        barcode_val = str(item.get("barcode", "")).strip()
        name = str(item.get("name", "")).strip()
        het = item.get("het")
        diskon = item.get("diskon")
        date_str = self.today_str()
        barcode_short = barcode_val[-6:] if len(barcode_val) >= 6 else barcode_val
        
        W, H = self.TAG_W, self.TAG_H
        
        # Outer border
        c.setStrokeColorRGB(*self._hex_to_rgb("#333333"))
        c.setLineWidth(0.5)
        c.rect(tx, ty, W, H, stroke=1, fill=0)
        
        # Zone heights
        info_h = H * 0.20   # bottom zone
        name_h = H * 0.30   # middle zone
        price_h = H * 0.50  # top zone
        
        info_y = ty
        name_y = ty + info_h
        price_y = ty + info_h + name_h
        
        PAD = 1.5  # mm
        
        # Divider lines
        c.setLineWidth(0.3)
        c.line(tx, name_y, tx + W, name_y)
        c.line(tx, price_y, tx + W, price_y)
        c.line(tx + W / 2, info_y, tx + W / 2, name_y)
        
        # PRICE ZONE
        inner_price_x = tx + PAD
        inner_price_w = W - 2 * PAD
        
        if diskon and het:
            # HET with strikethrough in upper 28%
            het_zone_h = price_h * 0.28
            het_zone_y = price_y + price_h - het_zone_h
            
            het_text = self.format_price(het)
            het_fs = 7
            c.setFont(self.MAIN_FONT, het_fs)
            c.setFillColorRGB(*self._hex_to_rgb("#888888"))
            het_w = pdfmetrics.stringWidth(het_text, self.MAIN_FONT, het_fs)
            het_tx = inner_price_x + (inner_price_w - het_w) / 2
            het_ty = het_zone_y + (het_zone_h - het_fs) / 2
            c.drawString(het_tx, het_ty, het_text)
            
            # Strikethrough line
            strike_y = het_ty + het_fs * 0.35
            c.setLineWidth(0.6)
            c.setStrokeColorRGB(*self._hex_to_rgb("#888888"))
            c.line(het_tx, strike_y, het_tx + het_w, strike_y)
            c.setStrokeColorRGB(*self._hex_to_rgb("#333333"))
            
            # Discount price in lower 72%
            disc_zone_h = price_h * 0.72
            disc_zone_y = price_y
            self._draw_text_block(
                c, self.format_price(diskon), self.MAIN_FONT_BOLD, "#000000",
                inner_price_x, disc_zone_y,
                inner_price_w, disc_zone_h,
                size_max=32, size_min=10, valign="middle",
            )
        elif het:
            # Single price
            self._draw_text_block(
                c, self.format_price(het), self.MAIN_FONT_BOLD, "#000000",
                inner_price_x, price_y,
                inner_price_w, price_h,
                size_max=32, size_min=10, valign="middle",
            )
        else:
            self._draw_text_block(
                c, "- Harga -", self.MAIN_FONT, "#999999",
                inner_price_x, price_y,
                inner_price_w, price_h,
                size_max=11, size_min=7, valign="middle",
            )
        
        # NAME ZONE
        self._draw_text_block(
            c, name, self.MAIN_FONT, "#000000",
            tx + PAD, name_y,
            W - 2 * PAD, name_h,
            size_max=13, size_min=6, valign="middle",
        )
        
        # INFO ZONE - left half: barcode short
        left_x = tx
        left_w = W / 2
        self._draw_text_block(
            c, barcode_short, self.MAIN_FONT, "#000000",
            left_x + PAD, info_y,
            left_w - 2 * PAD, info_h,
            size_max=11, size_min=6, valign="middle",
        )
        
        # INFO ZONE - right half: label + date
        right_x = tx + W / 2
        right_w = W / 2
        
        label_h_frac = info_h * 0.40
        date_h_frac = info_h * 0.60
        
        # "Terakhir diupdate" label
        label_text = "Terakhir diupdate"
        label_fs = 6
        c.setFont(self.MAIN_FONT, label_fs)
        c.setFillColorRGB(*self._hex_to_rgb("#888888"))
        lw = pdfmetrics.stringWidth(label_text, self.MAIN_FONT, label_fs)
        label_draw_x = right_x + (right_w - lw) / 2
        label_draw_y = info_y + date_h_frac + (label_h_frac - label_fs) / 2
        c.drawString(label_draw_x, label_draw_y, label_text)
        
        # Date
        date_fs = 8
        c.setFont(self.MAIN_FONT, date_fs)
        c.setFillColorRGB(*self._hex_to_rgb("#222222"))
        dw = pdfmetrics.stringWidth(date_str, self.MAIN_FONT, date_fs)
        date_draw_x = right_x + (right_w - dw) / 2
        date_draw_y = info_y + (date_h_frac - date_fs) / 2
        c.drawString(date_draw_x, date_draw_y, date_str)
    
    def generate_pdf(self, items: List[Dict[str, Any]], output_path: Optional[str] = None) -> bytes:
        """Generate PDF with price tags. Returns PDF bytes."""
        if not HAS_REPORTLAB:
            raise ImportError("reportlab is required for PDF generation. Install with: pip install reportlab")
        
        PAGE_W, PAGE_H = A4
        
        MARGIN_X = 0.5 * cm
        MARGIN_Y = 0.5 * cm
        GAP_X = 0.3 * cm
        GAP_Y = 0.3 * cm
        
        cols = max(1, int((PAGE_W - 2 * MARGIN_X + GAP_X) / (self.TAG_W + GAP_X)))
        rows_per_page = max(1, int((PAGE_H - 2 * MARGIN_Y + GAP_Y) / (self.TAG_H + GAP_Y)))
        per_page = cols * rows_per_page
        
        # Create buffer
        buffer = io.BytesIO()
        c = pdfcanvas.Canvas(buffer, pagesize=A4)
        
        for page_start in range(0, len(items), per_page):
            page_items = items[page_start:page_start + per_page]
            
            for i, item in enumerate(page_items):
                col = i % cols
                row = i // cols
                
                # PDF y=0 is bottom; tags fill top-down
                tx = MARGIN_X + col * (self.TAG_W + GAP_X)
                ty = PAGE_H - MARGIN_Y - (row + 1) * self.TAG_H - row * GAP_Y
                
                self._draw_tag(c, item, tx, ty)
            
            if page_start + per_page < len(items):
                c.showPage()
        
        c.save()
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        # Also save to file if path provided
        if output_path:
            with open(output_path, 'wb') as f:
                f.write(pdf_bytes)
        
        return pdf_bytes
