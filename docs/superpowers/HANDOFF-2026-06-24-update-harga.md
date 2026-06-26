# Handoff — Update Harga Feature

> **Dibuat:** 2026-06-24
> **Branch:** main (5 commits baru)
> **Status:** Implemented, but NOT tested against real Odoo data.

## Ringkasan

Fitur baru: page "Update Harga" untuk mencari vendor bill, menganalisis margin produk (dengan prorata diskon + tax adjustment), mendeteksi promo aktif, dan update list_price + pricelist fixed_price ke Odoo.

## Commits (dari bawah ke atas)

```
64ae877 feat: add PriceUpdateService with Odoo query methods
8586175 feat: add discount, tax, margin, promo logic to PriceUpdateService
7a6ec6f feat: add price update and pricelist write operations
20d39ef feat: add Update Harga UI page with data_editor
c505713 feat: add Update Harga tab to main app
```

## File Structure

| File | Lines | Role |
|------|-------|------|
| `logic/price_update_service.py` | 344 | Core logic: 14 methods for query, compute, write |
| `ui/pages/update_price.py` | 227 | Streamlit UI: dropdown bill, data_editor, promo guardrail, update button |
| `app.py` | +2 lines | Tab "update_harga" + import render_update_price_page |
| `ui/__init__.py` | +1 line | Export render_update_price_page |
| `utils/persistence.py` | +1 | TAB_NAMES includes "update_harga" |

## Apa yang Dibangun

### Logic Layer (`PriceUpdateService` — 14 methods)

| Kategori | Method | Fungsi |
|----------|--------|--------|
| **Query** | `get_recent_bills()` | 20 bill terbaru (in_invoice) |
| | `get_bill_lines(bill_id)` | Split positive/negative lines |
| | `get_product_template(product_id)` | Template + pricelist rules |
| | `get_previous_bill_line(product_id, current_bill_id)` | Modal lama |
| **Compute** | `compute_discount_prorata()` | Prorata diskon dari negative lines |
| | `get_tax_multiplier()` | 4 tax types (11% Blm Termasuk = 1.11) |
| | `compute_modal_baru()` | price_unit * (1-discount) * tax_mult |
| | `compute_margins()` | margin_before, margin_after, diff_amount |
| | `has_active_promo()` | Deteksi promo aktif via date range |
| **Orkestrasi** | `analyze_bill(bill_id)` | Full pipeline: query → compute → filter → return rows |
| | `_extract_pricelist_rules()` | Parse flat Odoo arrays ke structured dicts |
| | `_get_active_promo_rule()` | Return first active promo rule |
| **Write** | `validate_no_active_promo(row, force)` | Guardrail promo |
| | `update_product_price(template_id, sales_price)` | Update list_price |
| | `update_pricelist_fixed_price(row, fixed_price)` | Update/create pricelist item |
| | `update_selected(rows, indices, force_map)` | Batch update |

### UI Layer (`ui/pages/update_price.py`)

1. **Load otomatis** 20 bill terbaru via dropdown
2. **Tombol Load** → panggil `analyze_bill()`
3. **Promo banner** — warning kuning jika ada produk dengan promo aktif
4. **st.data_editor** — editable columns: Sales Price Baru, Fixed Price Baru
5. **Checkboxes**: Force? (override promo), Pilih (auto-unchecked jika promo)
6. **Summary** — rata-rata margin lama & baru
7. **Tombol Update** → panggil `update_selected()`
8. **Tombol Reset** — clear session state

### Promo Guardrail

- Auto-uncheck baris dengan promo aktif
- Warnanya orange via banner
- Column "Force?" untuk override
- Validasi di logic layer sebelum write

## Issues / Yang Perlu Diperbaiki

### 🔴 BLOCKER — Field pricelist tidak ditemukan di Odoo staging

```
RPCError: Invalid field 'x_studio_pricelist_rules_ids/id' on model 'product.template'
```

**Sebab:** Field `x_studio_pricelist_rules_ids` adalah custom field Odoo yang mungkin tidak ada di database staging, atau format query-nya salah. Odoo tidak support nested field access dengan slash notation (`x_studio_pricelist_rules_ids/id`) di semua versi.

**Solusi:**
1. Cek field aktual di Odoo: `product.template` mungkin punya `item_ids` (One2many ke `product.pricelist.item`) atau `x_studio_pricelist_rules_ids` sebagai fields.One2many langsung
2. Alternatif: query `product.pricelist.item` langsung dengan domain `[("product_tmpl_id", "=", template_id)]` — lebih reliable dan Odoo-native
3. Update `get_product_template()` untuk menghilangkan field pricelist dari query template, dan buat method baru `get_pricelist_items(template_id)` yang query `product.pricelist.item` langsung

Ada juga issue: nama bill di dropdown muncul sebagai ID karena field `partner_id` format Odoo OdooRPC mengembalikan `[id, name]` — ini sudah dihandle di UI.

### 🟡 Minor — N+1 Query Pattern

`analyze_bill()` loop per produk dan query `get_product_template` + `get_previous_bill_line`. Untuk bill dengan 20+ produk, ini bisa lambat.

**Optimasi:** Batch query produk templates dengan `product_variant_ids` filter, batch query previous bill lines.

## Arsitektur

### File Structure (existing dari refactor sebelumnya)

```
app.py → ui/pages/* → logic/* → odoo/* (OdooRPC)
```

### Data Flow
```
Pilih bill → get_bill_lines → split positive/negative
  → compute_discount_prorata → per product:
    → get_product_template
    → get_previous_bill_line
    → compute modal_baru + modal_lama
    → compute margins
    → detect promo
    → filter |diff| > 500
  → render data_editor
  → user edit, klik Update
  → update_selected → Odoo write (list_price + pricelist)
```

## Env Config

```
# Credentials not stored in repo — set via .env or .streamlit/secrets.toml
ODOO_PROTOCOL=jsonrpc+ssl
ODOO_PORT=443
```

## Next Steps

1. **Fix field pricelist** — query `product.pricelist.item` langsung, bukan via nested field template
2. **Test end-to-end** — run app, pilih bill, verifikasi data tampil benar
3. **Test promo detection** — pastikan ada data pricelist yang bisa dijadikan sample
4. **Test update** — update satu produk, verifikasi di Odoo
5. **Cleanup** — hapus `_test_analyze.py` kalo masih ada
6. **Push ke git**

## Referensi

- **Design Spec:** `docs/superpowers/specs/2026-06-24-update-harga-design.md`
- **Implementation Plan:** `docs/superpowers/plans/2026-06-24-update-harga.md`
- **Progress Ledger:** `.superpowers/sdd/progress.md`
