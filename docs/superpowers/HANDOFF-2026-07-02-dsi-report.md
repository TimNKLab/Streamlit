# HANDOFF: DSI Report Feature

> **Author:** Subagent-driven implementation  
> **Date:** 2026-07-02  
> **Commits:** 7 (485322c..8856d33) on `main`

---

## What Was Built

DSI (Days Sales of Inventory) report — Streamlit page untuk mengukur perputaran inventory.

### Scope
| Komponen | Status | File |
|----------|--------|------|
| DSI calculation + classification | ✅ Done | `logic/dsi_service.py` |
| Unit tests (19 tests) | ✅ Done | `tests/test_dsi_service.py` |
| DSI page UI (form, chart, table, download) | ✅ Done | `ui/pages/dsi_report.py` |
| Fast/slow moving classification thresholds | ✅ Done | Hardcoded, `logic/dsi_service.py:THRESHOLDS` |
| Brand filter | ❌ Removed | Menunggu brand field di Odoo |

### DSI Formula
```
DSI = (avg_qty / COGS) × days
avg_qty = (beginning_qty + ending_qty) / 2
COGS  = cost of goods sold dalam periode
days  = jumlah hari dalam date range
```

### Classification Thresholds
| Label | Range | Color |
|-------|-------|-------|
| Very Fast | 0–30 | 🟢 |
| Fast | 31–60 | 🔵 |
| Normal | 61–90 | 🟡 |
| Slow | 91–180 | 🟠 |
| Dead | >180 | 🔴 |

---

## Critical Issues — Must Fix Before Production

### #1: `remaining_qty` ≠ Historical Snapshot (C2)

**Apa masalahnya:** `_get_valuation_layers` pake `remaining_qty` dari `stock.valuation.layer`. Tapi `remaining_qty` adalah **sisa saat ini** dari layer itu, bukan nilai historis. Barang yang terjual setelah tanggal target sudah mengurangi `remaining_qty` — jadi beginning/ending inventory salah.

**Fix yang sudah dibahas dengan user:**
- Ganti `remaining_qty` → `quantity` di fields SVL query
- `quantity` = perubahan (+ masuk, - keluar). Sum `quantity` dari seluruh layer up to target_date = net inventory akumulatif
- COGS: query SVL dengan `quantity < 0` dalam date range, sum absolute value

**Penerapan:** Belum dilakukan — tunggu persetujuan user. Lihat detail di pembahasan.

### #2: Brand Filter Dead UX (C1)

**Apa masalahnya:** Brand field di Odoo (`product.brand` atau `x_studio_brand`) belum diketahui field namanya. Filter brand di-remove dari UI sementara, diganti `st.info("akan ditambahkan nanti")`.

**Fix:** Cari field brand yang sebenarnya di Odoo instance, update `_get_product_info` di `dsi_service.py:93-106` untuk query field itu.

---

## Architecture

### File Structure
```
logic/dsi_service.py       → Odoo queries + DSI calculation (pure functions)
ui/pages/dsi_report.py     → Streamlit UI (form, metrics, chart, table, download)
tests/test_dsi_service.py  → 19 unit tests (pure logic + mocked Odoo)
```

### Data Flow
```
User pilih date range → compute_dsi_report(date_from, date_to)
  → _get_valuation_layers([], date, date) → SVL rows
  → _get_product_info([product_ids])     → barcode/name/categ
  → calculate_dsi() for each product     → DSI value
  → classify_dsi()                       → Very Fast/Fast/Normal/Slow/Dead
  → pd.DataFrame sorted by DSI ascending
→ Streamlit renders: metrics + bar chart + detail table + CSV download
```

### Odoo Models Used
| Model | Fields | Purpose |
|-------|--------|---------|
| `stock.valuation.layer` | `product_id`, `remaining_qty`, `remaining_value` | Inventory quantity & value |
| `product.product` | `id`, `barcode`, `name`, `categ_id` | Product metadata |

### Key Functions
```
classify_dsi(dsi: float) → str
calculate_dsi(beginning_qty, ending_qty, cogs, days) → Optional[float]
_get_valuation_layers(product_ids, date_from, date_to) → Dict[pid, {qty, value}]
_get_product_info(product_ids) → Dict[pid, {barcode, name, brand, categ}]
compute_dsi_report(date_from, date_to) → pd.DataFrame
```

---

## Known Limitations (ponytail: comments in code)

| Limitation | Where | When to Upgrade |
|------------|-------|-----------------|
| COGS = end value proxy | `dsi_service.py:136` | SVL quantity < 0 analysis |
| remaining_qty not historical | `dsi_service.py:48` | stock.quant.history module |
| Brand field empty | `dsi_service.py:104` | product.brand_id field sourced |
| Thresholds hardcoded | `dsi_service.py:12-18` | Sidebar inputs for custom thresholds |

---

## Running Tests
```bash
python -m pytest tests/test_dsi_service.py -v
# 19/19 passing
```

---

## Pages in App
DSI Report tab sudah terdaftar di `app.py:73` — `"dsi_report": ("DSI Report", render_dsi_report_page)`.
