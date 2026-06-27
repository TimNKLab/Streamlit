# Price Last Updated Timestamp

## Overview

The Update Harga page now displays a **"Terakhir Diupdate"** (Last Updated) column showing when each product's sales price was last modified in Odoo.

## How It Works

- **Data Source:** The timestamp comes from Odoo's automatic `write_date` field on `product.template`
- **Format:** Indonesian locale - DD/MM/YYYY HH:MM (e.g., "25/06/2026 14:30")
- **Scope:** Shows when ANY field on the product template was last modified, not just the price
- **Missing Data:** Products with no modification history show "-"

## Use Cases

1. **Price Change Audit:** Quickly see when prices were last updated
2. **Stale Price Detection:** Identify products with old prices that may need review
3. **Update Tracking:** After batch updates, verify which products were modified

## Technical Notes

### Why Not Track Price-Specific Changes?

Odoo's `write_date` tracks ANY field modification on the product record. To track price-specific changes would require:
- Creating a custom field (e.g., `x_price_last_updated`)
- Adding custom logic to update this field on every price change
- Maintaining this custom logic across Odoo upgrades

For this use case, the generic `write_date` provides sufficient information without additional maintenance overhead.

### Timestamp Accuracy

The timestamp reflects the last write operation on the `product.template` record, which could be:
- Sales price (`list_price`) update
- Product name change
- Description update
- Any other field modification
- Automated system updates

If precise price-only tracking is needed in the future, consider using Odoo's field tracking feature with the `mail.thread` mixin, which logs field-specific changes to the chatter.

## See Also

- [Update Harga Feature](../superpowers/HANDOFF-2026-06-24-update-harga.md)
- [Odoo `write_date` Documentation](https://www.odoo.com/documentation/19.0/developer/reference/backend/orm.html)
