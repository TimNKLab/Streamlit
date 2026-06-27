---
name: price-last-updated-timestamp
description: Update Harga page displays Odoo write_date timestamp showing when products were last modified
metadata:
  type: project
---

# Price Last Updated Timestamp Feature

The Update Harga page now shows a "Terakhir Diupdate" column displaying when each product was last modified in Odoo.

**Why:** User requested visibility into when sales prices were last updated to identify stale prices and audit price changes.

**How to apply:**
- The timestamp comes from Odoo's automatic `write_date` field on `product.template`
- Format is Indonesian locale: DD/MM/YYYY HH:MM
- Shows ANY field modification on the product record, not just price changes
- This was the pragmatic choice vs. creating custom fields for price-specific tracking

**Implementation:**
- `logic/price_update_service.py` - fetches `write_date` from product.template
- `ui/pages/update_price.py` - formats and displays timestamp in analysis table
- Works in both single-bill and batch-by-date modes

**Related:** [[update-harga-feature-complete]]
