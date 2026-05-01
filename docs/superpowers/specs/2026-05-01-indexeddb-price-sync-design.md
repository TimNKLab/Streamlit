# IndexedDB-Based Price Sync Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans to implement this design.

**Goal:** Replace Excel-based price comparison with IndexedDB storage, enabling per-device price tracking for multiple users without coordination conflicts.

**Architecture:** Each device maintains its own IndexedDB with product price history. Sync compares current Odoo prices against the device's last known prices (stored in IndexedDB). Changes are device-specific; no shared state between devices.

**Tech Stack:** Streamlit, Python, IndexedDB via `streamlit-browser-storage` or custom component, Odoorpc for Odoo API.

---

## Problem Statement

Current workflow uses `products.xlsx` as the baseline for price comparison:
- User A prints price tags for Area 1 → Excel updated
- User B prints price tags for Area 2 → Overwrites User A's updates
- Lost updates, coordination headaches

## Proposed Solution

Use browser IndexedDB as per-device storage:
- Device A: Tracks prices it has printed
- Device B: Tracks prices it has printed  
- No shared state = no conflicts

## Data Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│    Odoo     │────▶│   Python    │────▶│  Streamlit  │
│  (Source)   │     │   Service   │     │     UI      │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                    ┌──────────────────────────┘
                    ▼
              ┌─────────────┐
              │  IndexedDB  │
              │  (Baseline) │
              └─────────────┘
```

**Sync Process:**
1. Fetch current prices from Odoo
2. Read baseline from IndexedDB `products` store
3. Compare → Detect changes
4. Show changes in UI
5. User selects → Print PDF
6. Update IndexedDB with new prices
7. Log to `sync_history`

## IndexedDB Schema

### Store: `products`
Primary key: `barcode`

| Field | Type | Description |
|-------|------|-------------|
| barcode | string | Product barcode (PK) |
| name | string | Product name |
| het | number | HET price |
| diskon | number? | Discount price (nullable) |
| last_sync | string | ISO timestamp of last sync |
| print_count | number | How many times printed |
| last_printed | string? | ISO timestamp of last print |

### Store: `sync_history`
Primary key: auto-increment `id`

| Field | Type | Description |
|-------|------|-------------|
| id | number | Auto-increment PK |
| timestamp | string | ISO timestamp |
| changes_detected | number | Count of changes |
| changes_printed | number | Count printed |
| device_info | string | Browser/device identifier |

## API Design

### Python Service: `IndexedDBPriceSync`

```python
class IndexedDBPriceSync:
    """Sync prices from Odoo, store baseline in IndexedDB via Streamlit component."""
    
    def __init__(self, conn_mgr: OdooConnectionManager = None):
        self.conn_mgr = conn_mgr or connection_manager
    
    def fetch_odoo_products(self) -> Dict[str, dict]:
        """Fetch all active goods from Odoo with pricelist discounts."""
        
    def detect_changes(self, local_baseline: Dict[str, dict]) -> SyncResult:
        """Compare Odoo prices against local IndexedDB baseline."""
        
    def export_changes(self, result: SyncResult) -> bytes:
        """Export changes to Excel for review."""
```

### Streamlit Component: IndexedDB Manager

```python
# JavaScript-side (via st.components.v1)
indexeddb = {
    "get_all_products": () -> List[dict],
    "upsert_products": (products: List[dict]) -> bool,
    "get_sync_history": (limit: int) -> List[dict],
    "add_sync_record": (record: dict) -> bool,
    "clear_all": () -> bool,
}
```

## UI Changes

### Price Sync Page (`ui/pages/price_sync.py`)

**Before:**
- Load `products.xlsx` as baseline
- Compare Odoo vs Excel
- Save to `session_data/user_price_tag.json`

**After:**
- Read from IndexedDB as baseline
- Compare Odoo vs IndexedDB
- Update IndexedDB after printing
- Show "Last synced: [timestamp]" for this device

### New Elements:
1. **IndexedDB Status Indicator**
   - "Database ready" / "Initializing..."
   - "Products cached: 10,247"
   - "Last sync: 2026-05-01 10:30"

2. **First-time Setup**
   - If IndexedDB empty → "First sync will cache all products"
   - Show progress bar for initial load

3. **Device Info**
   - Show browser/device identifier
   - "Changes tracked on this device only"

## Migration Path

**For existing Excel users:**
1. On first IndexedDB sync, offer to import from Excel
2. Or start fresh (recommended) - re-sync from Odoo
3. Excel file becomes read-only backup

## Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| User clears browser data | High | Data lost, must re-sync from Odoo. Acceptable - treat as "fresh start" |
| IndexedDB storage exceeded | Medium | Compress data, or implement pagination. Log warning when approaching limit |
| Multiple tabs race condition | Medium | Use IndexedDB transactions, version-based updates |
| Safari private mode (no storage) | Low | Detect and show error: "Please use normal browsing mode" |
| 10k+ products initial sync slow | Low | Show progress bar, stream results |

## Performance Considerations

- **Initial sync:** ~30-60 seconds for 10k products (acceptable)
- **Subsequent syncs:** ~5-10 seconds (compare in-memory)
- **IndexedDB batch writes:** 500 records at a time to avoid blocking

## Success Criteria

1. ✅ Each device has independent price tracking
2. ✅ No Excel file dependency for comparison
3. ✅ Sync detects changes correctly vs device's last known prices
4. ✅ Multiple users can work simultaneously without conflicts
5. ✅ PDF generation works directly from sync results
6. ✅ Sync history persisted per device

## Files to Modify

- `logic/odoo_price_sync.py` - Refactor to use IndexedDB baseline instead of Excel
- `ui/pages/price_sync.py` - Add IndexedDB component integration
- Create: `utils/indexeddb.py` - Python wrapper for IndexedDB operations
- Create: `components/indexeddb_manager.js` - JavaScript IndexedDB interface

---

**Status:** Design approved, ready for implementation planning.
