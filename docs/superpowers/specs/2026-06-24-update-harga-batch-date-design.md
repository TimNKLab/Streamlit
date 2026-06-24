# Update Harga — Batch by Date

> **Goal:** Add date-picker mode to fetch all posted vendor bills for a single day and analyze products, deduplicated by barcode.

**Fit:** Feature addition to existing `update_price.py` + `PriceUpdateService`.

## UI: Toggle Mode

Current: single dropdown of 20 recent bills.
New: tab toggle — `["Pilih Vendor Bill", "Pilih Tanggal"]`.

| Tab | Mode | Action |
|-----|------|--------|
| Pilih Vendor Bill | Existing dropdown (20 recent posted) | Load single bill |
| Pilih Tanggal | Date picker + "Load" button | Fetch all posted bills for that date, analyze each, merge, dedup |

### Pilih Tanggal Tab Layout

```
[Date Picker] [🔍 Load Bills]
  └─ st.caption: "Menemukan N bill untuk tanggal ini"
  └─ st.caption per bill: "✓ NK/POL/100125/9109: 12 produk" or "⚠️ Bill #1062254: skip (error)"
```

## Backend: `get_bills_by_date(date)`

New method on `PriceUpdateService`:

```python
def get_bills_by_date(self, target_date: date) -> List[Dict[str, Any]]:
    """Return all posted vendor bills for a given date."""
    return self.conn.search_read(
        model_name="account.move",
        domain=[
            ("move_type", "=", "in_invoice"),
            ("state", "=", "posted"),
            ("invoice_date", "=", target_date.isoformat()),
        ],
        fields=["id", "name", "ref", "invoice_date", "partner_id"],
        order="id desc",
    )
```

No limit — all bills for that date.

## Batch Analyze Flow

```
for each bill in bills:
    try:
        rows = self.analyze_bill(bill["id"])
        all_rows.extend(rows)
    except Exception:
        bill_errors.append(bill)
        continue          # skip error bills

# dedup by barcode — keep latest (first in list because order=id desc)
seen = set()
deduped = []
for r in all_rows:
    if r["barcode"] not in seen:
        seen.add(r["barcode"])
        deduped.append(r)
```

Dedup rule: for products appearing in multiple bills on same date, keep the row from the **largest bill ID** (latest created).

## UI: After Load

Same data_editor, same auto-calc, same update flow, same price tag generator.

- Bill label in summary: `"{date} — {len(deduped)} produk dari {len(bills)} bill"`
- No change to data_editor, update_selected, or price tag

## File Changes

| File | Change |
|------|--------|
| `logic/price_update_service.py` | Add `get_bills_by_date(target_date: date)` method (+~15 lines) |
| `ui/pages/update_price.py` | Add tab toggle, date picker section, batch analyze loop, dedup, per-bill status display (+~80 lines) |

No new files. No new dependencies.

## Error Handling

- Single bill fails analyze → skip, show warning "Bill NK/POL/100125/9109 gagal: {error}"
- No bills for date → st.info("Tidak ada faktur vendor untuk tanggal tersebut.")
- All bills fail → st.error + return

## Spec Self-Review

- [x] No placeholders or TODOs
- [x] Internal consistency — dedup rule matches data flow
- [x] Scope — single feature, one day, no new files
- [x] No ambiguity — dedup by barcode, keep largest bill ID, skip on error
