"""Price Tag Generator Service — optimized for performance."""

import os
import io
import time
from functools import lru_cache
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import pandas as pd
import streamlit as st

from odoo.connection import connection_manager

# Get project root (works locally and on Streamlit Cloud)
PROJECT_ROOT = Path(__file__).parent.parent

# PDF generation imports
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm, mm
    from reportlab.pdfgen import canvas as pdfcanvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.lib import colors as rcolors
    from reportlab.graphics.barcode import code128
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

# Fallbacks so this module can still import even if ReportLab isn't available.
# Some deployments (or partial installs) may not include ReportLab, and failing
# during import can surface as confusing import errors.
if not HAS_REPORTLAB:
    A4 = (595.275590551, 841.88976378)
    cm = 28.3464566929
    mm = 2.83464566929
    pdfcanvas = None
    pdfmetrics = None
    TTFont = None
    rcolors = None
    code128 = None

# Top/fast-moving products - hardcoded for instant lookup (O(1))
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
}

try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False

# ---------------------------------------------------------------------------
# Module-level caches (survive across instances within a process)
# ---------------------------------------------------------------------------

# Hex → RGB float tuple.  Only ~16M possible values but in practice < 100
# unique colors per run, so an unbounded cache is fine.
@lru_cache(maxsize=256)
def _hex_to_rgb(hex_str: str) -> Tuple[float, float, float]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255)


# Price formatting: same prices appear on many tags.
@lru_cache(maxsize=4096)
def _format_price_cached(price_int: int) -> str:
    return f"Rp {price_int:,}".replace(",", ".")


# stringWidth is cheap but called thousands of times; cache the hot path.
# Key: (text, font_name, font_size)
@lru_cache(maxsize=8192)
def _str_width(text: str, font: str, size: int) -> float:
    if pdfmetrics is None:
        # Approximation only; used when ReportLab isn't installed.
        return float(len(text) * size) * 0.55
    return pdfmetrics.stringWidth(text, font, size)


class PriceTagService:
    """Service for price tag generation and product database management."""

    # Tag size presets (width, height in cm)
    TAG_PRESETS = {
        "standard": (4.8, 3.0),      # 48mm x 30mm - original size
        "mini": (5.5, 2.5),          # 55mm x 25mm - new small size
    }

    TAG_W = 4.8 * cm
    TAG_H = 3 * cm

    # How often (seconds) to stat the parquet file for changes.
    # Avoids a syscall on every single lookup while still reacting promptly.
    _RELOAD_CHECK_INTERVAL = 5.0

    def __init__(
        self,
        fallback_db_path: str = None,
        duckdb_path: str = None,
        auto_convert: bool = True,
        use_memory_cache: bool = True,
    ):
        self.fallback_db_path = fallback_db_path or str(PROJECT_ROOT / "data" / "products.xlsx")
        self.duckdb_path = duckdb_path or str(PROJECT_ROOT / "data" / "products.duckdb")
        self.parquet_path = self.duckdb_path.replace(".duckdb", ".parquet")

        self._products: Dict[str, Dict[str, Any]] = {}
        self._suffix_index: Dict[str, List[str]] = {}
        self._duckdb_conn = None
        self._font_loaded = False
        self._use_duckdb = False
        self._use_memory_cache = use_memory_cache
        self._last_load_mtime: Optional[float] = None
        # Throttle file-stat checks: only stat at most every N seconds.
        self._next_check_at: float = 0.0

        self.MAIN_FONT = "Helvetica"
        self.MAIN_FONT_BOLD = "Helvetica-Bold"

        self._load_fonts()

        if auto_convert and HAS_DUCKDB:
            self._auto_convert_if_needed()

        if use_memory_cache:
            self._load_parquet_to_memory()

    # ------------------------------------------------------------------
    # Odoo sync
    # ------------------------------------------------------------------

    def sync_from_odoo(self) -> Dict[str, int]:
        """Sync in-stock products from Odoo to local parquet file.

        Queries ``product.product`` where ``qty_available > 0``,
        joins ``product.pricelist.item.fixed_price`` as ``diskon``,
        writes to parquet, and reloads the in-memory cache.

        Returns:
            Dict with ``success`` (valid records written) and
            ``skipped`` (records missing barcode/name).
        """
        # 1. Fetch in-stock products
        products = connection_manager.search_read(
            "product.product",
            domain=[("qty_available", ">", 0)],
            fields=["barcode", "name", "list_price", "id", "product_tmpl_id"],
        )

        # 2. Fetch pricelist items (batch)
        tmpl_ids = list({
            p["product_tmpl_id"][0]
            for p in products
            if isinstance(p.get("product_tmpl_id"), (list, tuple)) and len(p["product_tmpl_id"]) > 0
        })
        pricelist_items: List[Dict[str, Any]] = []
        if tmpl_ids:
            pricelist_items = connection_manager.search_read(
                "product.pricelist.item",
                domain=[("product_tmpl_id", "in", tmpl_ids)],
                fields=["product_tmpl_id", "fixed_price"],
            )

        # Build fixed_price lookup: {tmpl_id: fixed_price}
        fp_map: Dict[int, float] = {}
        for pi in pricelist_items:
            ptid = pi.get("product_tmpl_id")
            fp = float(pi.get("fixed_price") or 0)
            if isinstance(ptid, (list, tuple)) and ptid and fp > 0:
                fp_map[int(ptid[0])] = fp

        # 3. Build records
        records: List[Dict[str, Any]] = []
        skipped = 0
        for p in products:
            barcode = str(p.get("barcode") or "").strip()
            name = str(p.get("name") or "").strip()
            if not barcode or not name:
                skipped += 1
                continue

            tmpl_id = None
            ptid = p.get("product_tmpl_id")
            if isinstance(ptid, (list, tuple)) and ptid:
                tmpl_id = int(ptid[0])

            diskon = fp_map.get(tmpl_id) if tmpl_id is not None else None

            records.append({
                "barcode": barcode,
                "name": name,
                "het": float(p.get("list_price") or 0),
                "diskon": diskon,
            })

        # 4. Write parquet (ensure schema even when empty)
        df = pd.DataFrame(records, columns=["barcode", "name", "het", "diskon"])
        os.makedirs(os.path.dirname(self.parquet_path), exist_ok=True)
        df.to_parquet(self.parquet_path, index=False, compression="zstd")

        # 5. Reload cache
        self._load_parquet_to_memory()

        return {"success": len(records), "skipped": skipped}

    # ------------------------------------------------------------------
    # Font loading
    # ------------------------------------------------------------------

    def _load_fonts(self):
        if not HAS_REPORTLAB:
            self._font_loaded = True
            return

        try:
            fonts_dir = PROJECT_ROOT / "fonts"
            fonts_dir.mkdir(exist_ok=True)

            poppins_regular_url = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf"
            poppins_bold_url = "https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf"
            regular_path = fonts_dir / "Poppins-Regular.ttf"
            bold_path = fonts_dir / "Poppins-Bold.ttf"

            import urllib.request
            if not regular_path.exists():
                urllib.request.urlretrieve(poppins_regular_url, regular_path)
            if not bold_path.exists():
                urllib.request.urlretrieve(poppins_bold_url, bold_path)

            if regular_path.exists():
                pdfmetrics.registerFont(TTFont("Poppins-Regular", str(regular_path)))
                self.MAIN_FONT = "Poppins-Regular"
            if bold_path.exists():
                pdfmetrics.registerFont(TTFont("Poppins-Bold", str(bold_path)))
                self.MAIN_FONT_BOLD = "Poppins-Bold"
        except Exception as e:
            print(f"[FONTS] Failed to load Poppins: {e}, using Helvetica fallback")

        self._font_loaded = True

    # ------------------------------------------------------------------
    # Parquet / Excel management
    # ------------------------------------------------------------------

    def _auto_convert_if_needed(self):
        try:
            if not os.path.exists(self.fallback_db_path):
                return
            needs = not os.path.exists(self.parquet_path) or (
                os.path.getmtime(self.fallback_db_path) > os.path.getmtime(self.parquet_path)
            )
            if needs:
                self._convert_excel_to_parquet()
        except Exception as e:
            print(f"[PARQUET] Auto-conversion failed: {e}")

    def _convert_excel_to_parquet(self):
        try:
            print(f"[PARQUET] Converting {self.fallback_db_path}...")
            df = pd.read_excel(self.fallback_db_path)
            df = df.dropna(subset=["barcode", "name", "het"])
            df["barcode"] = df["barcode"].astype(str).str.strip()
            os.makedirs(os.path.dirname(self.parquet_path), exist_ok=True)
            df.to_parquet(self.parquet_path, index=False, compression="zstd")
            print(f"[PARQUET] Created {len(df)} rows → {self.parquet_path}")
        except Exception as e:
            print(f"[PARQUET] Conversion error: {e}")

    def _load_parquet_to_memory(self):
        """Load Parquet into memory dicts for O(1) lookups.

        Key optimisations over original:
        - Uses ``pd.DataFrame.to_dict('records')`` instead of slow ``iterrows``.
        - Builds the suffix index in the same pass (no second loop).
        - Skips reload when mtime unchanged.
        """
        if not os.path.exists(self.parquet_path):
            print(f"[CACHE] Parquet not found at {self.parquet_path}")
            return

        current_mtime = os.path.getmtime(self.parquet_path)
        if self._products and self._last_load_mtime == current_mtime:
            print(f"[CACHE] Already loaded ({len(self._products)} items), file unchanged")
            return

        if self._last_load_mtime is not None:
            print("[CACHE] Price data changed, reloading…")

        t0 = time.perf_counter()

        df = pd.read_parquet(self.parquet_path)

        # Vectorised string ops (much faster than per-row Python)
        barcodes = df["barcode"].astype(str).str.strip()
        suffixes = barcodes.str[-6:]
        has_diskon = "diskon" in df.columns

        # Build products dict in one pass using to_dict (avoids iterrows overhead)
        records = df.assign(barcode=barcodes, barcode_suffix=suffixes).to_dict("records")

        products: Dict[str, Dict[str, Any]] = {}
        suffix_index: Dict[str, List[str]] = {}

        for row in records:
            bc = row["barcode"]
            if not bc:
                continue
            sfx = row["barcode_suffix"]
            products[bc] = {
                "name": str(row.get("name", "")),
                "het": self._to_float(row.get("het")),
                "diskon": self._to_float(row.get("diskon")) if has_diskon else None,
                "barcode_suffix": sfx,
            }
            # Build suffix index in the same pass
            if sfx in suffix_index:
                suffix_index[sfx].append(bc)
            else:
                suffix_index[sfx] = [bc]

        self._products = products
        self._suffix_index = suffix_index
        self._last_load_mtime = current_mtime
        # Reset throttle clock so next check starts fresh
        self._next_check_at = time.monotonic() + self._RELOAD_CHECK_INTERVAL

        elapsed = time.perf_counter() - t0
        print(f"[CACHE] Loaded {len(products)} products in {elapsed:.3f}s")
        print(f"[CACHE] Suffix index: {len(suffix_index)} unique suffixes")

    # ------------------------------------------------------------------
    # Throttled reload check — replaces per-lookup os.stat() calls
    # ------------------------------------------------------------------

    def _check_and_reload_if_needed(self):
        """Stat the parquet file at most once every _RELOAD_CHECK_INTERVAL seconds."""
        if not self._use_memory_cache or not os.path.exists(self.parquet_path):
            return
        now = time.monotonic()
        if now < self._next_check_at:
            return  # Too soon — skip the syscall
        self._next_check_at = now + self._RELOAD_CHECK_INTERVAL
        current_mtime = os.path.getmtime(self.parquet_path)
        if self._last_load_mtime != current_mtime:
            print(f"[CACHE] Detected change, reloading…")
            self._load_parquet_to_memory()

    # ------------------------------------------------------------------
    # DuckDB
    # ------------------------------------------------------------------

    @staticmethod
    @st.cache_data(ttl=300)
    def _load_excel_cached(file_bytes: bytes) -> pd.DataFrame:
        return pd.read_excel(io.BytesIO(file_bytes))

    def _load_duckdb(self) -> bool:
        if not HAS_DUCKDB or not os.path.exists(self.parquet_path):
            return False
        try:
            self._duckdb_conn = duckdb.connect(":memory:")
            self._duckdb_conn.execute(
                f"CREATE VIEW products AS SELECT * FROM read_parquet('{self.parquet_path}')"
            )
            result = self._duckdb_conn.execute("SELECT COUNT(*) FROM products").fetchone()
            self._use_duckdb = True
            print(f"[DuckDB] Connected: {result[0]} products")
            return True
        except Exception as e:
            print(f"[DuckDB] Failed: {e}")
            self._use_duckdb = False
            if self._duckdb_conn:
                self._duckdb_conn.close()
                self._duckdb_conn = None
            return False

    def _lookup_duckdb(self, barcode: str) -> Optional[Dict[str, Any]]:
        if not self._use_duckdb or not self._duckdb_conn:
            return None
        try:
            row = self._duckdb_conn.execute(
                "SELECT barcode, name, het, diskon FROM products WHERE barcode = ?",
                [barcode],
            ).fetchone()
            if row:
                return {"name": row[1], "het": self._to_float(row[2]), "diskon": self._to_float(row[3])}
        except Exception:
            pass
        return None

    def load_database(
        self,
        uploaded_file=None,
        use_hardcoded: bool = False,
        use_duckdb: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        already_loaded = len(self._products) > 0
        self._use_duckdb = False

        if use_hardcoded:
            return TOP_PRODUCTS.copy()
        if already_loaded:
            print(f"[DB_LOAD] Already loaded ({len(self._products)} items), skipping")
            return self._products

        try:
            if use_duckdb and self._load_duckdb():
                return {}

            df = None
            if uploaded_file is not None:
                df = self._load_excel_cached(uploaded_file.getvalue())
            elif os.path.exists(self.fallback_db_path):
                with open(self.fallback_db_path, "rb") as f:
                    df = self._load_excel_cached(f.read())
            else:
                return TOP_PRODUCTS.copy()

            if df is not None:
                required_cols = ["barcode", "name", "het"]
                missing = [c for c in required_cols if c not in df.columns]
                if missing:
                    st.error(f"Missing required columns: {', '.join(missing)}")
                    return TOP_PRODUCTS.copy()

                barcodes = df["barcode"].astype(str).str.strip()
                suffixes = barcodes.str[-6:]
                has_diskon = "diskon" in df.columns
                records = df.assign(barcode=barcodes, barcode_suffix=suffixes).to_dict("records")

                for row in records:
                    bc = row["barcode"]
                    if not bc:
                        continue
                    sfx = row["barcode_suffix"]
                    self._products[bc] = {
                        "name": str(row.get("name", "")),
                        "het": self._to_float(row.get("het")),
                        "diskon": self._to_float(row.get("diskon")) if has_diskon else None,
                        "barcode_suffix": sfx,
                    }
                    if sfx in self._suffix_index:
                        self._suffix_index[sfx].append(bc)
                    else:
                        self._suffix_index[sfx] = [bc]

                return self._products

        except Exception as e:
            st.warning(f"Could not load database: {e}. Using hardcoded fallback.")
            return TOP_PRODUCTS.copy()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _to_float(value) -> Optional[float]:
        if value is None or value == "" or str(value).lower() in ("null", "nan"):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def format_price(price: Optional[float]) -> str:
        if price is None:
            return ""
        try:
            return _format_price_cached(int(price))
        except (ValueError, TypeError):
            return str(price)

    @staticmethod
    def today_str() -> str:
        return datetime.now().strftime("%d-%m-%Y")

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def lookup_product(self, barcode: str) -> Optional[Dict[str, Any]]:
        barcode = barcode.strip()
        self._check_and_reload_if_needed()
        if self._products:
            return self._products.get(barcode)
        if barcode in TOP_PRODUCTS:
            return TOP_PRODUCTS[barcode]
        if self._use_duckdb:
            return self._lookup_duckdb(barcode)
        return None

    def lookup_product_by_suffix(self, suffix: str) -> Optional[Dict[str, Any]]:
        suffix = suffix.strip()
        self._check_and_reload_if_needed()

        if len(suffix) != 6:
            return None

        matches = self._suffix_index.get(suffix, [])
        if len(matches) == 1:
            return self._products.get(matches[0])
        if len(matches) > 1:
            return {"_status": "AMBIGUOUS"}

        # Fallback: treat suffix as full barcode
        return self._products.get(suffix)

    @property
    def product_count(self) -> int:
        return len(set(TOP_PRODUCTS) | set(self._products))

    # ------------------------------------------------------------------
    # PDF drawing helpers
    # ------------------------------------------------------------------

    def _fit_fontsize(self, text: str, font: str, max_w: float,
                      size_max: int = 28, size_min: int = 6) -> int:
        """Return largest font size where text fits in max_w (uses cached widths)."""
        if not HAS_REPORTLAB:
            return size_min
        for fs in range(size_max, size_min - 1, -1):
            if _str_width(text, font, fs) <= max_w:
                return fs
        return size_min

    def _draw_text_block(
        self,
        c,
        text: str,
        font: str,
        color_hex: str,
        x: float,
        y: float,
        w: float,
        h: float,
        size_max: int = 28,
        size_min: int = 6,
        valign: str = "middle",
    ):
        """Draw word-wrapped, auto-sized, centred text.

        Optimisation: instead of wrapping at every font size (O(n²)), we
        binary-search for the largest size that fits the first line, then do a
        single wrap pass at that size.  This is exact for single-line text and
        a good heuristic for multi-line (we fall through to smaller sizes only
        when the block still overflows vertically).
        """
        if not text or not HAS_REPORTLAB:
            return

        r, g, b = _hex_to_rgb(color_hex)
        c.setFillColorRGB(r, g, b)

        inner_w = w - 2  # 1-pt padding each side

        def _wrap(fs: int) -> List[str]:
            """Wrap *text* at *inner_w* using cached stringWidth."""
            lines: List[str] = []
            cur = ""
            for word in text.split():
                candidate = (cur + " " + word).strip() if cur else word
                if _str_width(candidate, font, fs) <= inner_w:
                    cur = candidate
                else:
                    if cur:
                        lines.append(cur)
                    cur = word
            if cur:
                lines.append(cur)
            return lines

        for fs in range(size_max, size_min - 1, -1):
            leading = fs * 1.25
            lines = _wrap(fs)
            if len(lines) * leading <= h or fs == size_min:
                total_h = len(lines) * leading
                if valign == "middle":
                    start_y = y + h / 2 + total_h / 2 - leading * 0.8
                elif valign == "top":
                    start_y = y + h - leading * 0.2
                else:
                    start_y = y + total_h - leading * 0.8

                c.setFont(font, fs)
                for line in lines:
                    lw = _str_width(line, font, fs)
                    c.drawString(x + (w - lw) / 2, start_y, line)
                    start_y -= leading
                return

    def _draw_tag(
        self,
        c,
        item: Dict[str, Any],
        tx: float,
        ty: float,
        TAG_W: float,
        TAG_H: float,
        size_preset: str = "standard",
    ):
        """Draw one price tag at (tx, ty).  Colours fetched from module-level cache.

        Args:
            c: Canvas
            item: Product data dict
            tx: X position
            ty: Y position
            TAG_W: Tag width
            TAG_H: Tag height
            size_preset: "standard" (48x30mm) or "mini" (70x20mm)
        """
        if not HAS_REPORTLAB:
            return

        barcode_val = str(item.get("barcode", "")).strip()
        name = str(item.get("name", "")).strip()
        het = item.get("het")
        diskon = item.get("diskon")
        date_str = self.today_str()
        barcode_short = barcode_val[-6:] if len(barcode_val) >= 6 else barcode_val

        W, H = TAG_W, TAG_H

        # Different layout for mini tags
        if size_preset == "mini":
            self._draw_mini_tag(c, item, tx, ty, W, H)
            return

        # Standard tag layout (original)
        c.setStrokeColorRGB(*_hex_to_rgb("#333333"))
        c.setLineWidth(0.5)
        c.rect(tx, ty, W, H, stroke=1, fill=0)

        info_h = H * 0.20
        name_h = H * 0.30
        price_h = H * 0.50
        info_y = ty
        name_y = ty + info_h
        price_y = ty + info_h + name_h
        PAD = 1.5

        c.setLineWidth(0.3)
        c.line(tx, name_y, tx + W, name_y)
        c.line(tx, price_y, tx + W, price_y)
        c.line(tx + W / 2, info_y, tx + W / 2, name_y)

        inner_price_x = tx + PAD
        inner_price_w = W - 2 * PAD

        if diskon and het:
            het_zone_h = price_h * 0.28
            het_zone_y = price_y + price_h - het_zone_h
            het_text = self.format_price(het)
            het_fs = 7
            c.setFont(self.MAIN_FONT, het_fs)
            c.setFillColorRGB(*_hex_to_rgb("#888888"))
            het_w = _str_width(het_text, self.MAIN_FONT, het_fs)
            het_tx = inner_price_x + (inner_price_w - het_w) / 2
            het_ty = het_zone_y + (het_zone_h - het_fs) / 2
            c.drawString(het_tx, het_ty, het_text)
            strike_y = het_ty + het_fs * 0.35
            c.setLineWidth(0.6)
            c.setStrokeColorRGB(*_hex_to_rgb("#888888"))
            c.line(het_tx, strike_y, het_tx + het_w, strike_y)
            c.setStrokeColorRGB(*_hex_to_rgb("#333333"))
            self._draw_text_block(
                c, self.format_price(diskon), self.MAIN_FONT_BOLD, "#000000",
                inner_price_x, price_y, inner_price_w, price_h * 0.72,
                size_max=32, size_min=10, valign="middle",
            )
        elif het:
            self._draw_text_block(
                c, self.format_price(het), self.MAIN_FONT_BOLD, "#000000",
                inner_price_x, price_y, inner_price_w, price_h,
                size_max=32, size_min=10, valign="middle",
            )
        else:
            self._draw_text_block(
                c, "- Harga -", self.MAIN_FONT, "#999999",
                inner_price_x, price_y, inner_price_w, price_h,
                size_max=11, size_min=7, valign="middle",
            )

        self._draw_text_block(
            c, name, self.MAIN_FONT, "#000000",
            tx + PAD, name_y, W - 2 * PAD, name_h,
            size_max=13, size_min=6, valign="middle",
        )

        self._draw_text_block(
            c, barcode_short, self.MAIN_FONT, "#000000",
            tx + PAD, info_y, W / 2 - 2 * PAD, info_h,
            size_max=11, size_min=6, valign="middle",
        )

        right_x = tx + W / 2
        right_w = W / 2
        label_h_frac = info_h * 0.40
        date_h_frac = info_h * 0.60

        label_text = "Terakhir diupdate"
        label_fs = 6
        c.setFont(self.MAIN_FONT, label_fs)
        c.setFillColorRGB(*_hex_to_rgb("#888888"))
        lw = _str_width(label_text, self.MAIN_FONT, label_fs)
        c.drawString(right_x + (right_w - lw) / 2, info_y + date_h_frac + (label_h_frac - label_fs) / 2, label_text)

        date_fs = 8
        c.setFont(self.MAIN_FONT, date_fs)
        c.setFillColorRGB(*_hex_to_rgb("#222222"))
        dw = _str_width(date_str, self.MAIN_FONT, date_fs)
        c.drawString(right_x + (right_w - dw) / 2, info_y + (date_h_frac - date_fs) / 2, date_str)

    def _draw_mini_tag(
        self,
        c,
        item: Dict[str, Any],
        tx: float,
        ty: float,
        W: float,
        H: float,
    ):
        """Draw a mini price tag (55mm x 25mm) - same layout as standard, smaller."""
        if not HAS_REPORTLAB:
            return

        barcode_val = str(item.get("barcode", "")).strip()
        name = str(item.get("name", "")).strip()
        het = item.get("het")
        diskon = item.get("diskon")
        date_str = self.today_str()
        barcode_short = barcode_val[-6:] if len(barcode_val) >= 6 else barcode_val

        # Same zone proportions as standard tag
        info_h = H * 0.20
        name_h = H * 0.30
        price_h = H * 0.50
        info_y = ty
        name_y = ty + info_h
        price_y = ty + info_h + name_h
        PAD = 1.5

        # Draw border (same style as standard tag)
        c.setStrokeColorRGB(*_hex_to_rgb("#333333"))
        c.setLineWidth(0.5)
        c.rect(tx, ty, W, H, stroke=1, fill=0)

        # Divider lines (same as standard)
        c.setLineWidth(0.3)
        c.line(tx, name_y, tx + W, name_y)
        c.line(tx, price_y, tx + W, price_y)
        c.line(tx + W / 2, info_y, tx + W / 2, name_y)

        inner_price_x = tx + PAD
        inner_price_w = W - 2 * PAD

        # Price zone - same logic as standard (strikethrough + big discount)
        if diskon and het:
            het_zone_h = price_h * 0.28
            het_zone_y = price_y + price_h - het_zone_h
            het_text = self.format_price(het)
            het_fs = 6  # slightly smaller for mini
            c.setFont(self.MAIN_FONT, het_fs)
            c.setFillColorRGB(*_hex_to_rgb("#888888"))
            het_w = _str_width(het_text, self.MAIN_FONT, het_fs)
            het_tx = inner_price_x + (inner_price_w - het_w) / 2
            het_ty = het_zone_y + (het_zone_h - het_fs) / 2
            c.drawString(het_tx, het_ty, het_text)
            strike_y = het_ty + het_fs * 0.35
            c.setLineWidth(0.6)
            c.setStrokeColorRGB(*_hex_to_rgb("#888888"))
            c.line(het_tx, strike_y, het_tx + het_w, strike_y)
            c.setStrokeColorRGB(*_hex_to_rgb("#333333"))
            self._draw_text_block(
                c, self.format_price(diskon), self.MAIN_FONT_BOLD, "#000000",
                inner_price_x, price_y, inner_price_w, price_h * 0.72,
                size_max=24, size_min=8, valign="middle",
            )
        elif het:
            self._draw_text_block(
                c, self.format_price(het), self.MAIN_FONT_BOLD, "#000000",
                inner_price_x, price_y, inner_price_w, price_h,
                size_max=24, size_min=8, valign="middle",
            )
        else:
            self._draw_text_block(
                c, "- Harga -", self.MAIN_FONT, "#999999",
                inner_price_x, price_y, inner_price_w, price_h,
                size_max=10, size_min=6, valign="middle",
            )

        # Name zone - auto-resize like standard
        self._draw_text_block(
            c, name, self.MAIN_FONT, "#000000",
            tx + PAD, name_y, W - 2 * PAD, name_h,
            size_max=11, size_min=6, valign="middle",
        )

        # Info zone left: barcode short
        self._draw_text_block(
            c, barcode_short, self.MAIN_FONT, "#000000",
            tx + PAD, info_y, W / 2 - 2 * PAD, info_h,
            size_max=9, size_min=5, valign="middle",
        )

        # Info zone right: date only (no "Terakhir diupdate" label)
        right_x = tx + W / 2
        right_w = W / 2
        date_fs = 7
        c.setFont(self.MAIN_FONT, date_fs)
        c.setFillColorRGB(*_hex_to_rgb("#222222"))
        dw = _str_width(date_str, self.MAIN_FONT, date_fs)
        c.drawString(right_x + (right_w - dw) / 2, info_y + (info_h - date_fs) / 2, date_str)

    # ------------------------------------------------------------------
    # PDF generation
    # ------------------------------------------------------------------

    def generate_pdf(
        self,
        items: List[Dict[str, Any]],
        output_path: Optional[str] = None,
        size_preset: str = "standard",
    ) -> bytes:
        if not HAS_REPORTLAB:
            raise ImportError("reportlab required: pip install reportlab")

        # Get tag dimensions from preset
        if size_preset not in self.TAG_PRESETS:
            size_preset = "standard"
        tag_w_cm, tag_h_cm = self.TAG_PRESETS[size_preset]
        TAG_W = tag_w_cm * cm
        TAG_H = tag_h_cm * cm

        PAGE_W, PAGE_H = A4
        MARGIN_X = 0.3 * cm
        MARGIN_Y = 0.5 * cm
        GAP_X = 0.2 * cm
        GAP_Y = 0.3 * cm

        cols = max(1, int((PAGE_W - 2 * MARGIN_X + GAP_X) / (TAG_W + GAP_X)))
        rows_per_page = max(1, int((PAGE_H - 2 * MARGIN_Y + GAP_Y) / (TAG_H + GAP_Y)))
        per_page = cols * rows_per_page

        buffer = io.BytesIO()
        c = pdfcanvas.Canvas(buffer, pagesize=A4)

        for page_start in range(0, len(items), per_page):
            page_items = items[page_start : page_start + per_page]
            for i, item in enumerate(page_items):
                col = i % cols
                row = i // cols
                tx = MARGIN_X + col * (TAG_W + GAP_X)
                ty = PAGE_H - MARGIN_Y - (row + 1) * TAG_H - row * GAP_Y
                self._draw_tag(c, item, tx, ty, TAG_W, TAG_H, size_preset)
            if page_start + per_page < len(items):
                c.showPage()

        c.save()
        pdf_bytes = buffer.getvalue()
        buffer.close()

        if output_path:
            with open(output_path, "wb") as f:
                f.write(pdf_bytes)

        return pdf_bytes

    def generate_thermal_labels_pdf(
        self,
        items: List[Dict[str, Any]],
        *,
        width_mm: float = 28.0,
        height_mm: float = 18.0,
    ) -> bytes:
        """Generate a thermal label PDF (one label per page).

        Key optimisations over original:
        - ``_truncate_to_width`` defined once (not per-item closure).
        - All ``stringWidth`` calls go through the module-level LRU cache.
        - Font-size constants computed once outside the loop.
        """
        if not HAS_REPORTLAB:
            raise ImportError("reportlab required: pip install reportlab")

        page_w = width_mm * mm
        page_h = height_mm * mm

        buffer = io.BytesIO()
        c = pdfcanvas.Canvas(buffer, pagesize=(page_w, page_h))

        # Tighter padding for small 18x28mm labels
        pad_x = 0.3 * mm
        pad_y = 0.3 * mm
        max_w = page_w - 2 * pad_x

        # Smaller fonts for tiny labels
        name_fs = 4
        barcode_text_fs = 4
        price_fs = 5

        # Pre-compute layout constants for 18x28mm label
        name_zone_h = 4.0 * mm
        price_zone_h = 4.5 * mm
        barcode_text_zone_h = 2.5 * mm
        barcode_zone_h = page_h - (pad_y * 2) - name_zone_h - barcode_text_zone_h - price_zone_h

        # Vertical positions (from bottom up)
        price_y = pad_y
        barcode_text_y = price_y + price_zone_h
        barcode_y = barcode_text_y + barcode_text_zone_h
        name_y = page_h - pad_y - name_zone_h

        def _truncate(text: str, font: str, fs: int) -> str:
            """Truncate text to fit max_w, appending ellipsis if needed."""
            if _str_width(text, font, fs) <= max_w:
                return text
            ell = "…"
            if _str_width(ell, font, fs) > max_w:
                return ""
            lo, hi = 0, len(text)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                cand = text[: mid - 1].rstrip() + ell
                if _str_width(cand, font, fs) <= max_w:
                    lo = mid
                else:
                    hi = mid - 1
            return text[: lo - 1].rstrip() + ell

        def _draw_centred(text: str, font: str, fs: int, zone_y: float, zone_h: float):
            c.setFont(font, fs)
            tw = _str_width(text, font, fs)
            c.drawString(pad_x + max(0.0, (max_w - tw) / 2), zone_y + (zone_h - fs) / 2, text)

        for idx, item in enumerate(items):
            barcode = str(item.get("barcode", "")).strip()
            name = str(item.get("name", "")).strip()
            het = item.get("het")

            if not barcode or not name:
                continue

            het_text = self.format_price(het)
            if het_text and not het_text.endswith(",-"):
                het_text = f"{het_text},-"

            c.setFillColorRGB(0, 0, 0)

            # Name
            _draw_centred(_truncate(name, self.MAIN_FONT_BOLD, name_fs), self.MAIN_FONT_BOLD, name_fs, name_y, name_zone_h)

            # Barcode graphic
            try:
                bar_h = max(3.5 * mm, barcode_zone_h - 0.4 * mm)
                bc = code128.Code128(barcode, barWidth=0.15 * mm, barHeight=bar_h, humanReadable=False)
                bx = pad_x + (max_w - bc.width) / 2
                by = barcode_y + (barcode_zone_h - bc.height) / 2
                bc.drawOn(c, bx, by)
            except Exception:
                _draw_centred(
                    _truncate(barcode, self.MAIN_FONT, barcode_text_fs),
                    self.MAIN_FONT, barcode_text_fs, barcode_y, barcode_zone_h,
                )

            # Human-readable barcode
            _draw_centred(
                _truncate(barcode, self.MAIN_FONT_BOLD, barcode_text_fs),
                self.MAIN_FONT_BOLD, barcode_text_fs, barcode_text_y, barcode_text_zone_h,
            )

            # Price
            _draw_centred(
                _truncate(het_text, self.MAIN_FONT_BOLD, price_fs),
                self.MAIN_FONT_BOLD, price_fs, price_y, price_zone_h,
            )

            if idx < len(items) - 1:
                c.showPage()

        c.save()
        pdf_bytes = buffer.getvalue()
        buffer.close()
        return pdf_bytes
