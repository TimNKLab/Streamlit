# Price Sync Refinement — Fix Mapping Bug + New Products + Price Tag Integration
**Date**: 2026-07-01

## Problem

`detect_changes_since()` sering gagal mendeteksi perubahan harga karena:

1. **Mapping bug**: `_query_mail_tracking()` memasukkan template ID dan variant ID ke `changed_map`. Query `product.product` dengan `("id", "in", product_ids)` gagal untuk template ID → produk hilang dari hasil.
2. **`_diff_with_tracking()` skip** saat `old_value_float` is `None` → initial price change tidak terdeteksi.
3. **Deteksi "new"** bergantung parquet yang mungkin usang/tak ada.

## Solusi — 3 Perubahan

### 1. Fix `_query_mail_tracking()` — Bersihkan mapping

Hapus template ID dari `result` setelah mapping variant selesai. Return hanya `{variant_id: (changed_at, old_price_or_None)}`.

Mengadopsi pola yang sudah terbukti dari `PriceUpdateService._init_price_field_id()`.

### 2. Fungsi baru `_detect_new_products_since(start_date)`

```python
def _detect_new_products_since(self, start_date) -> List[PriceChange]:
    """Query product.product dengan create_date >= start_date, qty > 0.
    Filter: barcode tidak ada di parquet (known products).
    Tidak perlu menebak increase/decrease — semua sebagai 'new'.
    """
```

- Query `product.product` domain `[("create_date", ">=", start), ("qty_available", ">", 0), ("barcode", "!=", False)]`
- Filter barcode yang sudah ada di parquet → skip
- Return `PriceChange(change_type="new")`

### 3. Simplify `detect_changes_since()`

```
1. changed_map = _query_mail_tracking(start_date)       # clean: {variant_id: (ts, old)}
2. odoo_products = query variant_ids dari changed_map    # ONLY variants
3. changes = _diff_with_tracking(odoo_products, changed_map)
4. new_changes = _detect_new_products_since(start_date)
5. changes + new_changes → sort + sortir non-listrik → return
```

Hapus:
- Fallback `write_date` (tidak berguna tanpa old_price)
- Kode "all products" untuk new detection (diganti fungsi baru)
- Hapus duplicate `changes.sort()` (line 649-650)

### 4. Price tag preparation — Pakai PriceTagService

Di `price_sync.py`, setelah user pilih produk:

```python
def _generate_pdf(selected_changes, tag_service) -> bytes:
    items = []
    for c in selected_changes:
        # Lookup dari PTS untuk dapat diskon & harga terkini
        local = tag_service.lookup_product(c.barcode)
        items.append({
            "barcode": c.barcode,
            "name": c.name,
            "het": local["het"] if local else c.new_price,
            "diskon": local.get("diskon") if local else None,
        })
    return tag_service.generate_pdf(items)
```

## Files Changed

- `logic/odoo_price_sync.py` — Fix `_query_mail_tracking`, add `_detect_new_products_since`, simplify `detect_changes_since`
- `ui/pages/price_sync.py` — Refactor `_generate_pdf` to use `PriceTagService.lookup_product()`

## Edge Cases

| Skenario | Penanganan |
|---|---|
| Produk baru (tracking kosong, parquet kosong) | `_detect_new_products_since` langsung query create_date |
| old_value_float = None | Return sebagai change_type "new" (bukan skip) |
| Template ID di changed_map | Variant mapping sudah bersih → tidak masuk final keys |
| No products in range | Empty result, info message (existing) |
| Barcode tidak di PTS | Fallback ke new_price dari PriceChange |
