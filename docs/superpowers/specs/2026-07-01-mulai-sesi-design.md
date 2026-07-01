# Mulai Sesi Feature Design
**Date**: 2026-07-01

## Overview
Replace the manual "Update harga" button with an automatic "Mulai Sesi" button that:
1. Syncs live Odoo prices to products.parquet (only products with qty_available > 0)
2. Initializes the price tag session
3. Removes the need for manual price updates

## Architecture

### Core Changes
1. **New service method**: `PriceTagService.sync_from_odoo()`
   - Queries Odoo for in-stock products
   - Updates parquet file with latest prices
   - Refreshes in-memory cache

2. **UI state management**: 
   - New session state: `price_tag_session_active` (boolean)
   - Blocks UI until session is started
   - Provides "Akhiri Sesi" to end session

3. **Removed components**:
   - "Update harga" button (manual update)
   - Automatic price loading on service init

### Data Flow
```
[User clicks "Mulai Sesi"]
        ↓
[PriceTagService.sync_from_odoo()]
        ↓
1. Odoo RPC: product.product (qty_available > 0)
   → barcode, name, list_price, product_tmpl_id
2. Odoo RPC: product.pricelist.item (batch lookup)
   → product_tmpl_id, fixed_price
3. Join in Python:
   - het = list_price
   - diskon = fixed_price (if > 0, else null)
4. Write DataFrame to data/products.parquet
5. Reload in-memory cache via _load_parquet_to_memory()
        ↓
[Set session state: price_tag_session_active = true]
        ↓
[Show price tag UI with fresh data]
```

## Components

### 1. PriceTagService.sync_from_odoo() (logic/price_tag_service.py)
**Inputs**: None
**Outputs**: Dict with keys:
- `success`: number of products synced
- `skipped`: number of products skipped (missing barcode/name)

**Steps**:
1. Build domain: `[("qty_available", ">", 0)]`
2. Fields: `["barcode", "name", "list_price", "id", "product_tmpl_id"]`
3. Execute search_read on `product.product`
4. Extract unique `product_tmpl_id` values
5. Batch search_read on `product.pricelist.item`:
   - Domain: `[("product_tmpl_id", "in", tmpl_ids)]`
   - Fields: `["product_tmpl_id", "fixed_price"]`
6. Create lookup map: `{tmpl_id: fixed_price}`
7. Build records list:
   ```python
   for product in products:
       record = {
           "barcode": product["barcode"].strip(),
           "name": product["name"].strip(),
           "het": float(product["list_price"]),
           "diskon": float(product["fixed_price"]) 
                    if product.get("fixed_price", 0) > 0 else None
       }
       if record["barcode"] and record["name"]:
           records.append(record)
   ```
8. Create DataFrame and write to parquet:
   ```python
   df = pd.DataFrame(records)
   df.to_parquet(self.parquet_path, index=False, compression="zstd")
   ```
9. Refresh cache: `self._load_parquet_to_memory()`
10. Return counts

### 2. PriceTagPage.render() (ui/pages/price_tag_generator.py)
**Session state additions**:
- `price_tag_session_active`: boolean (default False)

**Modified render flow**:
```python
def render(self):
    st.title("Price Tag Generator 😸")
    
    # Session activation check
    if not st.session_state.get("price_tag_session_active", False):
        self._render_session_start()
        return  # BLOCK UI until session starts
    
    # Normal UI (unchanged from current)
    st.caption(f"📦 Database: {self.service.product_count:,} harga sudah terupdate")
    ...
    
    # Session end button (optional, bottom of page)
    with st.container():
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("🏁 Akhiri Sesi", use_container_width=True):
                st.session_state.price_tag_session_active = False
                # Clear PDF cache to force regeneration
                st.session_state.price_tag_pdf_ready = False
                st.session_state.price_tag_pdf_bytes = None
                st.rerun()
```

**_render_session_start() helper**:
```python
def _render_session_start(self):
    st.markdown("---")
    st.markdown("### 🚀 Tekan untuk memulai sesi price tag")
    st.caption("Inakan sinkronisasi harga terbaru dari Odoo (hanya produk dengan stok > 0)")
    
    if st.button("Mulai Sesi", type="primary", use_container_width=True):
        with st.spinner("Mengambil data harga dari Odoo..."):
            try:
                result = self.service.sync_from_odoo()
                st.toast(
                    f"✅ {result['success']} produk berhasil di-sinkronisasi!", 
                    icon="✅"
                )
                st.session_state.price_tag_session_active = True
                st.rerun()
            except Exception as e:
                st.error(f"Gagal sinkronisasi: {str(e)}")
                st.exception(e)
```

### 3. Removed: Manual update button
Remove from `PriceTagPage.render()` (lines ~972-984 in current code):
- The entire `col2` block containing "🔄 Update harga" button
- Associated session state clearing logic (now handled by session activation)

## Data Flow Details

### Odoo Queries
1. **Product query** (executed once per sync):
   ```python
   domain = [("qty_available", ">", 0)]
   fields = ["barcode", "name", "list_price", "id", "product_tmpl_id"]
   products = connection.search_read("product.product", domain, fields)
   ```
   Returns: List of dicts with product data for in-stock items

2. **Pricelist item query** (batch lookup):
   ```python
   tmpl_ids = list(set(p["product_tmpl_id"][0] for p in products if p["product_tmpl_id"]))
   domain = [("product_tmpl_id", "in", tmpl_ids)]
   fields = ["product_tmpl_id", "fixed_price"]
   pricelist_items = connection.search_read("product.pricelist.item", domain, fields)
   ```
   Returns: List of dicts mapping template ID to fixed_price

### Data Transformation
- **het** (harga etalage): Always from `list_price` (sale price)
- **diskon**: From `fixed_price` ONLY if > 0, otherwise None/null
- **Filtering**: Skip records with empty barcode or name
- **Data types**: 
  - barcode: string (stripped)
  - name: string (stripped)
  - het: float → stored as int in parquet (via existing formatting)
  - diskon: float or None

### Parquet Schema
Matches existing `price_tag_service.py` expectations:
- barcode: string
- name: string  
- het: integer (price in Rupiah, no decimals)
- diskon: integer or null

## Error Handling

### Service Layer (`sync_from_odoo`)
- **Connection failures**: Catch `OdooIntegrationError`, show user-friendly message
- **Missing fields**: Skip invalid records, log warning
- **Parquet write errors**: Catch IO errors, show error toast
- **Empty results**: Return `{success: 0, skipped: 0}` with info toast

### UI Layer
- **Sync errors**: Show `st.error()` with details, retain inactive session state
- **Loading state**: Show spinner during sync, disable button to prevent double-click
- **Success feedback**: Use `st.toast()` for non-intrusive confirmation

## Edge Cases

1. **No products in stock** (`qty_available > 0` returns empty)
   - Result: Empty parquet file, service shows 0 products
   - UI: Show info message "Tidak ada produk dengan stok tersedia"

2. **Products missing barcode/name**
   - Handled in Python: skipped during record building
   - Counted in `skipped` metric

3. **Partial Odoo failure** (product query succeeds, pricelist fails)
   - Current design: treat missing fixed_price as None (no discount)
   - Alternative: fail entire sync - chosen approach is more resilient

4. **Concurrent sync attempts**
   - Button disabled during spinner prevents multiple clicks
   - Service method is idempotent - safe to call multiple times

5. **Corrupted parquet file**
   - Service automatically reloads on next sync
   - Fallback to Excel if parquet missing/corrupt (existing behavior)

## Testing Strategy

### Unit Tests (service layer)
1. `test_sync_from_odoo_success`:
   - Mock Odoo responses
   - Verify parquet file written with correct data
   - Check returned counts match mocks

2. `test_sync_from_odoo_empty_results`:
   - Mock empty product list
   - Verify empty parquet file created

3. `test_sync_from_odoo_missing_fields`:
   - Test data with missing barcode/name
   - Verify only valid records processed

4. `test_sync_from_odoo_connection_error`:
   - Mock Odoo connection failure
   - Verify error propagated to UI

### Integration Tests (UI layer)
1. **Manual test flow**:
   - Start app → see "Mulai Sesi" button
   - Click button → show spinner
   - Mock successful sync → see toast + UI enabled
   - Verify product count reflects mocked data

2. **End-to-end scenario**:
   - Add test product to Odoo with qty > 0
   - Start session → product appears in price tag UI
   - Update product price in Odoo
   - Start new session → updated price appears

### Performance Considerations
- **Batch RPC**: Single call for all pricelist items (O(1) vs O(n))
- **Throttled reload**: Existing `_check_and_reload_if_needed()` prevents excessive file stats
- **Memory caching**: Products loaded once per session unless file changes
- **Parquet compression**: Uses zstd (existing setting) for fast I/O

## Open Questions

1. **Session persistence**: Should `price_tag_session_active` survive page refresh?
   - Current: No (resets on reload) - forces fresh sync each visit
   - Alternative: Store in localStorage via existing `persistence.py` utilities

2. **End session behavior**: 
   - Current option: Clear PDF cache to force regeneration
   - Alternative: Keep PDFs until new session starts

3. **Error recovery**:
   - Should failed sync allow manual retry without full page refresh?
   - Current: Yes - button remains visible, user can click again

## Implementation Notes

### Files to Modify
1. `logic/price_tag_service.py` - Add `sync_from_odoo()` method
2. `ui/pages/price_tag_generator.py` - 
   - Add session state handling
   - Replace update button with Mulai Sesi/Akhiri Sesi
   - Remove manual update logic

### Dependencies
- None new - uses existing Odoo connection manager
- Uses existing parquet/pandas infrastructure
- Leverages existing `_load_parquet_to_memory()` for cache refresh

### Estimated Effort
- Service method: 2-3 hours
- UI modifications: 1-2 hours
- Testing: 1-2 hours
- Total: 4-7 hours

## Next Steps
1. Approve this design document
2. Implement `sync_from_odoo()` in service layer
3. Modify UI to implement session flow
4. Test end-to-end with real Odoo data
5. Remove old update button code