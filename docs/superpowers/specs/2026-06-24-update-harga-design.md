# Update Harga — Price Update from Vendor Bills

> **Goal:** New page to search vendor bills, display products with margin analysis, and update sales price + pricelist to Odoo.

## Architecture

### File Structure

| File | Responsibility |
|------|---------------|
| `logic/price_update_service.py` | Core logic: fetch bill lines, tax/discount calculation, margin computation, update Odoo |
| `ui/pages/update_price.py` | Streamlit UI: search/dropdown bill, editable agGrid/table, update button |
| `app.py` | Add `render_update_price_page` import + "update_harga" tab |

### Data Flow

```
User search/pick bill from dropdown
  → get_recent_bills() → dropdown list (account.move, move_type=in_invoice, order by date desc)
  → get_bill_lines(bill_id)
       ├─ positive lines = products (product_id, price_unit, quantity, tax_ids)
       ├─ negative lines = discounts (price_subtotal < 0)
       ├─ for each product: get_previous_bill_line(product_id) → modal_lama
       ├─ for each product: get_product_template(product_id) → list_price, pricelist_rules
       └─ compute: discount_pct, modal_baru, tax_adjustment, margin_before, margin_after
  → filter: |modal_baru - modal_lama| > 500
  → render table + editable inputs
  → user clicks "Update"
       → write list_price to product.template
       → write fixed_price to product.pricelist.item
```

## Odoo Queries

### Search Recent Bills
```
model: account.move
domain: [("move_type", "=", "in_invoice")]
fields: ["id", "name", "ref", "invoice_date", "partner_id"]
order: "invoice_date desc"
limit: 20
```

### Get Bill Lines (products + discounts)
```
model: account.move.line
domain: [("move_id", "=", bill_id), ("product_id", "!=", False)]
fields: ["product_id", "price_unit", "quantity", "tax_ids", "price_subtotal", "name"]
```

### Get Product Template (list_price, pricelist)
```
model: product.template
domain: [("product_variant_ids", "in", [product_id])]
fields: [
  "id", "barcode", "name", "list_price", "standard_price",
  "x_studio_pricelist_rules_ids/id",
  "x_studio_pricelist_rules_ids/pricelist_id/id",
  "x_studio_pricelist_rules_ids/pricelist_id/name",
  "x_studio_pricelist_rules_ids/applied_on",
  "x_studio_pricelist_rules_ids/date_start",
  "x_studio_pricelist_rules_ids/fixed_price"
]
```

### Get Previous Vendor Bill for Product
```
model: account.move.line
domain: [
  ("product_id", "=", product_id),
  ("move_id.move_type", "=", "in_invoice"),
  ("move_id.id", "!=", current_bill_id),
  ("price_unit", ">", 0),
]
fields: ["price_unit", "quantity", "tax_ids", "price_subtotal", "move_id"]
order: "move_id.invoice_date desc"
limit: 1
```

### Update List Price
```
model: product.template
write: {"list_price": new_sales_price}
```

### Update Pricelist Fixed Price
```
model: product.pricelist.item
write(pricelist_item_id): {"fixed_price": new_fixed_price}
```

If no existing pricelist rule for this product, create one:
```
model: product.pricelist.item
create: {
  "pricelist_id": pricelist_id,
  "product_tmpl_id": template_id,
  "applied_on": "0_product_variant",
  "fixed_price": new_fixed_price,
}
```

## Business Logic

### Discount Prorata
```
sum_base = Σ(positive_line.price_unit * positive_line.quantity)
total_discount = abs(Σ negative_line.price_subtotal)
discount_pct = total_discount / sum_base  (0 if no discount lines)
```

### Unit Price After Discount
```
unit_price_after_discount = price_unit * (1 - discount_pct)
```

### Tax Adjustment
| Tax | Multiplier | Notes |
|-----|-----------|-------|
| 11% PPN Termasuk | 1.0 | Price already includes PPN |
| 11% PPN Blm Termasuk | 1.11 | Must add 11% |
| 0% Non PKP/FP | 1.0 | No PPN |
| 0% PPN Dikecualikan | 1.0 | Exempt |

```
modal_baru = unit_price_after_discount * tax_multiplier
```

### Margin Calculation
```
margin_before = (list_price / modal_lama) - 1  (as decimal, show as %)
margin_after  = (list_price / modal_baru) - 1
margin_diff_amount = |modal_baru - modal_lama|
```

### Filter
Show only rows where `margin_diff_amount > 500`.

## Promo Guardrail

### Deteksi Promo Aktif

Sebelum menampilkan table, cek tiap produk apakah memiliki **promo aktif**:

```
model: product.pricelist.item
# Data sudah didapat dari x_studio_pricelist_rules_ids di product.template query
# Evaluasi di Python:
today = date.today()
is_active_promo = (
    rule.date_start <= today
    and (not rule.date_end or rule.date_end >= today)
    and rule.fixed_price < template.list_price  # ada diskon
)
```

**Field tambahan di query product.template:**

```
"x_studio_pricelist_rules_ids/date_end"
```

### Kolom Tambahan di Table

| Kolom | Sumber | Nilai |
|-------|--------|-------|
| **Promo** | Hasil deteksi | `"✅ Aktif"` / `"❌ Tidak"` |
| **Periode Promo** | date_start - date_end | `"01 Jun - 15 Jun 2026"` / `"-"` |
| **Harga Promo** | fixed_price promo | Formatted Rp / `"-"` |

### Guardrail Behavior

1. **Auto-uncheck**: Baris dengan promo aktif otomatis tidak tercentang (Pilih = False)
2. **Force Override**: Kolom `"Force?"` — checkbox terpisah, default False. Jika dicentang, override guardrail
3. **Visual Warning**: Baris promo aktif punya background **orange** dengan tooltip/peringatan
4. **Banner**: Tampilkan warning banner di atas table: "⚠️ X produk memiliki promo aktif. Centang 'Force' untuk override."

### Update Validation

Di logic layer, sebelum update:

```python
def validate_no_active_promo(
    product_id: int, 
    template_id: int, 
    force: bool = False
) -> tuple[bool, str]:
    """Return (is_valid, warning_message)."""
    if force:
        return True, ""
    if has_active_promo(template_id):
        return False, "Produk memiliki promo aktif. Gunakan force=True untuk override."
    return True, ""
```

`has_active_promo(template_id)` — cek apakah ada pricelist rule dengan `date_start <= today <= date_end` dan `fixed_price < list_price`.

### Skenario

| Skenario | Row Tercentang? | Force Butuh? | Warning? |
|----------|----------------|-------------|----------|
| Tidak ada promo | ✅ Ya | ❌ Tidak | Tidak |
| Promo aktif, user setujui override | ✅ Ya (user centang Force) | ✅ Ya | Banner kuning |
| Promo aktif, user tidak override | ❌ Tidak otomatis | - | Banner, row orange |
| Promo sudah lewat | ✅ Ya | ❌ Tidak | Tidak |

## UI Layout

```
┌─────────────────────────────────────────────────────┐
│  [Search / Dropdown Vendor Bills]    [Load Button]  │
├─────────────────────────────────────────────────────┤
│                                                     │
│  st.data_editor with columns:                       │
│  No | Barcode | Nama Produk | Harga Modal Lama    │
│  | Harga Modal Baru | Harga Jual | Margin Lama %  │
│  | Margin Baru % | Promo | Periode Promo          │
│  | Sales Price Baru [editable]                     │
│  | Fixed Price Baru [editable]                     │
│  | Force? [checkbox] | Pilih [checkbox]            │
│                                                     │
│  Summary: N produk | Rata-rata margin lama/baru     │
│                                                     │
│  [Update Selected to Odoo]  [Cancel]                │
└─────────────────────────────────────────────────────┘
```

### Columns in Detail
1. **No** — row number
2. **Barcode** — from product
3. **Nama Produk** — from product
4. **Harga Modal Lama** — from last vendor bill (formatted Rp)
5. **Harga Modal Baru** — from current bill (formatted Rp)
6. **Harga Jual** — list_price current (formatted Rp)
7. **Margin Lama** — `((list_price/modal_lama)-1)*100` %
8. **Margin Baru** — `((list_price/modal_baru)-1)*100` %
9. **Promo** — `"✅ Aktif"` / `"❌ Tidak"` (non-editable)
10. **Periode Promo** — `"01 Jun - 15 Jun 2026"` / `"-"` (non-editable)
11. **Sales Price Baru** — editable text input, pre-filled with list_price
12. **Fixed Price Baru** — editable text input, pre-filled with current fixed_price or list_price
13. **Force?** — checkbox override promo guardrail, default False
14. **Pilih** — checkbox to select for update, auto-unchecked if promo aktif

### Color Coding
- **Red row** if margin_drop > 5pp (percentage points)
- **Green row** if margin_increase > 5pp
- **Yellow row** if modal_baru < modal_lama (price dropped)

### Edge Cases
1. **No previous bill** → modal_lama = "-", margin_lama = "-"
2. **No pricelist rule** → fixed_price input empty, create new on update
3. **Multiple tax_ids** → if any tax is "11% Blm Termasuk", use 1.11 multiplier
4. **Zero discount_pct** → no discount lines found, proceed normally
5. **All rows filtered out** → show info message "Tidak ada perubahan harga > Rp500"
6. **Promo aktif tanpa Force** → row auto-unchecked, warning orange, skip update
7. **Promo aktif dengan Force** → row tetap bisa diupdate, banner peringatan tetap tampil

## UI Component Choice

Use **st.data_editor** (built-in Streamlit editable dataframe) instead of agGrid:
- No extra dependency (streamlit-aggrid already exists but st.data_editor is native)
- Supports editable columns, checkbox selection
- Better Streamlit Cloud compatibility

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Odoo connection fails | Error message, retry button |
| Bill not found | Info message "Bill tidak ditemukan" |
| No products in bill | Info message, show bill summary anyway |
| Update fails for some products | Show partial success with failed list |
| Discount > 100% of base | Treat as no discount, log warning |
| Promo aktif (update tanpa Force) | Skip update, tampilkan error per-produk di summary |

## Success Criteria

1. User can search/select any vendor bill
2. All products show with correct margins (including discount prorata + tax)
3. Editable columns for sales price and fixed price
4. Update pushes changes to Odoo (list_price + pricelist item)
5. Handles discount lines gracefully (prorata)
6. Handles all 4 tax types correctly
7. Only shows changes > Rp500
8. Promo aktif terdeteksi dan auto-uncheck baris terkait
9. Force override berfungsi untuk update paksa barang promo
