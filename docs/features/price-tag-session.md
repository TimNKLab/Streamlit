# Price Tag Session

## What It Is

Instead of generating price tag PDF after every "Update ke Odoo" (slow, duplicative),
the app now **accumulates items** into a session. All items from all bills are
collected until you choose to print.

## How It Works

1. **Update prices** from any bill (single or batch mode)
2. Items are silently added to the session — no PDF generated
3. A **section** at the bottom shows pending labels: "🏷️ Price Tag Sesi (14 label)"
4. When ready, click **"Download PDF"** or **"Print di Browser"**
5. Click **"Hapus Sesi"** to start fresh

## Session Rules

- Same barcode = newer price overwrites older one (no duplicates)
- Switching bills keeps session intact
- Session clears when you click "Hapus Sesi"
- Thermal label (28x18mm) also supports session accumulation

## Implementation

- Session lives in `st.session_state.price_tag_items`
- Accumulated via `_accumulate_tag_items()` which handles dedup by barcode
- Rendered via `_render_tag_session_ui()` at page bottom
- Cleared via `_clear_tag_session()`
