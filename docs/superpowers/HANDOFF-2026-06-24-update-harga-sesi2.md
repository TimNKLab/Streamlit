# Handoff — Update Harga Sesi 2 (Batch + Price Tag + Fixes)

> **Dibuat:** 2026-06-24
> **Branch:** main

## Ringkasan

Lanjutan dari sesi 1. Fix blocker query, restyle UI, auto-calc roundup, price tag generator, batch by date.

## Commits

```
c505713 feat: add Update Harga tab to main app          (sebelumnya)
ff00453 feat: add batch-by-date mode for vendor bill     (baru)
```

## File Changes

| File | Status | Description |
|------|--------|-------------|
| `logic/price_update_service.py` | Modified | 16 changes: N+1→batch, tax int-ID fix, hapus discount, hapus draft, skip new products |
| `ui/pages/update_price.py` | Modified | 6 rewrites: inline checkbox, auto-calc, price tag, batch by date, responsive toggle |
| `docs/superpowers/specs/2026-06-24-update-harga-batch-date-design.md` | New | Design spec for batch mode |

## Semua Fix Sesi 2

### 🔴 Blocker Fixes

| # | Issue | Fix |
|---|-------|-----|
| 1 | `x_studio_pricelist_rules_ids/id` RPCError | Hapus dot-notation. Query `product.pricelist.item` langsung via `get_pricelist_items(template_id)` |
| 2 | `move_id.invoice_date` RPCError di `order` | Ganti `order="id desc"` |
| 3 | N+1 query (2N per bill) | Batch barcode-keyed: `product.product` → `product.template` → `product.pricelist.item` → `account.move.line`. Cuma **5 query total** |
| 4 | Tax multiplier gak match int ID `[7]` | `_init_tax_map()` cache semua tax di init. `get_tax_multiplier` handle `int` dan `[id, name]` |
| 5 | Tax key mismatch (nama kurung vs tanpa kurung) | Ganti key jadi substring: `"PPN Blm Termasuk"` bukan `"11% PPN Blm Termasuk"` |
| 6 | `modal_lama` pakai `discount_pct` dari bill sekarang | Hapus `compute_discount_prorata`. `modal = round(price_unit * tax_mult)` — konsisten untuk kedua modal |
| 7 | Draft bills di dropdown tampil `False \| - \| Partner` | `get_recent_bills` domain tambah `("state", "=", "posted")` |

### 🟡 UI Changes

| # | Change |
|---|--------|
| 1 | `st.checkbox` per row → **checkbox column** di `data_editor` (Pilih + Force?) |
| 2 | `Harga Jual (Fix)` gabung → **Sales Price Lama** + **Fixed Price Lama** (2 kolom pisah) |
| 3 | **Margin Lama** kolom baru (disabled) |
| 4 | **Modal Lama** kolom baru (disabled) |
| 5 | Margin Baru → **Harga→Fix** (rasio `old_fp / list_price`, persen) |
| 6 | **Auto-calc**: `Sales Price Baru = roundup(modal_baru * (1 + margin))`, `Fixed Price Baru = roundup(sp_baru * ratio)` |
| 7 | **Roundup** ke 100: `math.ceil(v/100)*100` |
| 8 | **Price Tag Download** setelah update berhasil: A4 standard + thermal 28x18mm |
| 9 | **Toggle Mode**: radio button `Pilih Vendor Bill` / `Pilih Tanggal` |
| 10 | **Batch by Date**: date picker → `get_bills_by_date()` → batch analyze → dedup by barcode |
| 11 | Produk baru (`modal_lama = None`) **otomatis skip** dari tabel |

### Arsitektur Price Tag

Price tag reuse existing `PriceTagService` dari `price_tag_generator.py`. Item format:
```python
{
    "barcode": "...",
    "name": "...",
    "het": new_price,   # harga baru (tanpa coret)
    "diskon": None,
}
```

`_draw_tag()` render `het` sebagai harga besar di tengah tag. Dua output:
- **A4 standard** (48×30mm, multipel per page)
- **Thermal** (28×18mm, 1 per page)

### Batch by Date Flow

```
Toggle "Pilih Tanggal"
→ date picker → get_bills_by_date(date)
→ [for each bill] analyze_bill(bid) → skip on error
→ flatten all rows
→ dedup by barcode (keep bill ID tertinggi)
→ same analysis/update/price-tag flow
```

### Catatan

- `str(name_raw)` panggil di bill — Odoo return `False` untuk field kosong
- Tax ID `7` = `"11% (PPN Blm Termasuk)"` → multiplier 1.11
- Bill density per hari maks ~44 bill (2026-04-21)
- Bill posted rata-rata date `False` di draft — setelah fix `state=posted`, invoice_date selalu ada

## Next Steps

1. Tes E2E di Streamlit app — pilih bill, verifikasi data, update, price tag
2. Tes batch by date — pilih tanggal dengan banyak bill
3. Tes price tag download — verifikasi PDF layout
4. Push ke git
