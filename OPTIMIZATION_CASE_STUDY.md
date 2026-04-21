# From 8 Seconds to 1 Microsecond: Optimizing a Streamlit Price Tag Generator for 55,000 Products

## The Challenge: Speed at Scale

When building an internal price tag generator for a retail operation managing over 55,000 SKUs, we hit a critical performance wall. What started as a simple Streamlit application for printing shelf labels became a lesson in data engineering, caching strategies, and the nuances of reactive web frameworks.

The initial problem was straightforward but severe: every barcode lookup took **8 seconds**. For a user scanning 20 items to generate a PDF of price tags, this meant nearly 3 minutes of waiting—unacceptable for a production tool.

## Identifying the Bottlenecks

### Problem 1: Excel as a Database

The original implementation loaded product data from an Excel file (`products.xlsx`) on every lookup. With 55,123 products and a 51MB file size, pandas' `read_excel()` was being called repeatedly, parsing the entire workbook each time. This was fundamentally the wrong tool for the job—Excel is a spreadsheet format, not a queryable database.

### Problem 2: Streamlit's Reactive Model

Streamlit's architecture re-runs the entire Python script on every user interaction. Every keystroke in a text input triggers a full re-execution. Our original code was reloading the entire product database on every single render, amplifying the Excel parsing problem exponentially.

### Problem 3: Widget State Decoupling

When we populated product data (name, price, discount) after a barcode lookup, the UI fields weren't reflecting the changes. Streamlit widgets maintain their own internal state through widget keys, and updating the backend `session_state` values wasn't enough—we needed to force widget regeneration.

## The Optimization Journey

### Phase 1: Caching with `@st.cache_data`

Our first attempt used Streamlit's built-in caching decorator:

```python
@st.cache_data(ttl=300)
def _load_excel_cached(file_bytes: bytes) -> pd.DataFrame:
    return pd.read_excel(io.BytesIO(file_bytes))
```

This helped with repeated loads of the same file, but the fundamental issue remained: we were still parsing Excel, and cache invalidation was tricky when the underlying data changed.

### Phase 2: DuckDB and Parquet

We explored two database options for faster lookups:

**DuckDB** emerged as the superior choice over SQLite for analytical workloads. It's designed for columnar data and can query Parquet files directly without loading them into memory.

**Parquet**, a columnar storage format, provided:
- **Compression**: 51MB Excel → 1.1MB Parquet (Zstandard compression)
- **Speed**: Columnar format enables predicate pushdown and faster scans
- **Compatibility**: Native support in both pandas and DuckDB

We implemented auto-conversion on startup:

```python
def _convert_excel_to_parquet(self):
    df = pd.read_excel(self.fallback_db_path)
    df.to_parquet(parquet_path, index=False, compression='zstd')
```

### Phase 3: Aggressive In-Memory Caching

Even with Parquet, we were still querying DuckDB for each lookup. The breakthrough came from loading the **entire dataset into a Python dictionary** at startup:

```python
def _load_parquet_to_memory(self):
    df = pd.read_parquet(self.parquet_path)
    for _, row in df.iterrows():
        barcode = str(row.get('barcode', '')).strip()
        if barcode:
            self._products[barcode] = {
                'name': str(row.get('name', '')),
                'het': self._to_float(row.get('het')),
                'diskon': self._to_float(row.get('diskon')),
            }
```

This transformed lookup complexity from O(n) file scanning to O(1) hash table access—approximately **1 microsecond per query**.

### Phase 4: `@st.cache_resource` for Persistence

To prevent reloading 55,000 products on every Streamlit rerender, we used `@st.cache_resource` instead of `@st.cache_data`:

```python
@st.cache_resource(ttl=3600)
def get_price_tag_service() -> PriceTagService:
    service = PriceTagService()
    service.load_database()
    return service
```

Unlike `cache_data` (for serializable data), `cache_resource` caches arbitrary Python objects, persisting our in-memory dictionary across all user interactions.

### Phase 5: Solving the Widget State Problem

To force UI refresh after populating lookup data, we regenerate widget keys dynamically:

```python
# After filling product data
st.session_state.price_tag_items[idx]['key_prefix'] = \
    f"row_{idx}_{datetime.now().strftime('%H%M%S%f')}"
```

New keys = new widgets = fresh values displayed.

### Phase 6: Batch Lookup Mode

For maximum scanning speed, we implemented a batch mode where users can:
1. Scan all barcodes rapidly (no lookups, no lag)
2. Click "Lookup N Items" button once
3. All lookups happen in ~0.2 seconds total

This eliminates per-keystroke processing entirely during the scanning phase.

## Results: Dramatic Performance Gains

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| Startup time | ~12s | ~0.3s | **40x faster** |
| Per-lookup time | 8s | ~0.000001s | **8,000,000x faster** |
| Batch lookup (20 items) | ~160s | ~0.2s | **800x faster** |
| Memory usage | Minimal | ~4MB | Acceptable trade-off |
| File size (data) | 51MB (Excel) | 1.1MB (Parquet) | **46x smaller** |

The application now feels instant. A user can scan 20 items and generate a PDF in under 10 seconds total, compared to nearly 3 minutes previously.

## Cloud Deployment Considerations

Moving from local Windows development to Streamlit Cloud required several fixes:

1. **Absolute paths**: Using `Path(__file__).parent.parent` instead of relative paths
2. **Directory creation**: Ensuring `data/` folder exists with `os.makedirs(..., exist_ok=True)`
3. **Font fallbacks**: Defaulting to Helvetica when custom fonts aren't available
4. **Dependency management**: Pinning `pyarrow`, `duckdb`, and `reportlab` versions

## Future Development Opportunities

### 1. Web Workers for Background Processing
For even larger catalogs (500k+ products), we could move the Parquet loading to a Web Worker thread, keeping the UI responsive during startup.

### 2. Incremental Loading with Lazy Evaluation
Rather than loading all 55k products upfront, we could implement a two-tier system:
- Load top 1000 sellers into memory immediately
- Lazy-load remaining products on first access

### 3. Browser Storage Integration
Using IndexedDB or localStorage to cache the product catalog client-side, eliminating server round-trips entirely for repeat users.

### 4. WebSocket Barcode Scanners
Modern barcode scanners can act as USB keyboards OR WebSocket devices. Supporting the latter would enable instant scan-to-web-app workflows without focus management.

### 5. Print-Direct Integration
Instead of PDF download-then-print, investigate Streamlit's ability to trigger browser print dialogs directly with pre-formatted label templates.

### 6. Product Image Integration
Adding product images to price tags (from a CDN or local cache) would require thumbnail optimization and potentially a separate image cache strategy.

### 7. Real-time Inventory Sync
Connecting the label generator to live inventory systems via Webhooks or polling, ensuring price changes propagate immediately without manual Excel updates.

## Key Takeaways

1. **Choose the right data format**: Parquet > Excel for read-heavy analytical workloads
2. **Cache aggressively**: In-memory dictionaries beat database queries for static reference data
3. **Understand your framework**: Streamlit's reactive model requires specific patterns for state persistence
4. **Profile before optimizing**: Our 8-second delay was obvious, but measuring each phase helped prioritize fixes
5. **Design for batch operations**: UI perceived performance often matters more than actual backend speed

This optimization exercise transformed a frustrating tool into a competitive advantage, demonstrating that thoughtful data engineering can deliver orders-of-magnitude improvements even in "simple" internal applications.
