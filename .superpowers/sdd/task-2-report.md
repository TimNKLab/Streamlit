# Task 2 Report: Add Discount, Tax, Margin, Promo Logic

## What Was Implemented

Added 8 methods + 1 class constant to `PriceUpdateService` in `logic/price_update_service.py`:

- `TAX_MULTIPLIERS` — class dict mapping tax names to multipliers (11% PPN Blm Termasuk -> 1.11)
- `compute_discount_prorata()` — prorates negative line discounts across positive lines, returns 0-1 pct (capped at 100%)
- `get_tax_multiplier()` — looks up Odoo tax_ids [[id, name], ...] against TAX_MULTIPLIERS
- `compute_modal_baru()` — price after discount * tax multiplier, rounded
- `compute_margins()` — margin_before, margin_after, margin_diff_amount
- `has_active_promo()` — checks date range + fixed_price > 0 on pricelist rules
- `analyze_bill()` — orchestrator: fetches lines, computes discounts/tax/margins, filters by |diff| > 500, detects promos
- `_extract_pricelist_rules()` — parses flat Odoo search_read arrays into structured rule dicts
- `_get_active_promo_rule()` — returns first active promo rule matching today's date

## Test Results

```
compute_discount_prorata: True
get_tax_multiplier: True
compute_modal_baru: True
compute_margins: True
has_active_promo: True
analyze_bill: True
_extract_pricelist_rules: True
_get_active_promo_rule: True
TAX_MULTIPLIERS: True
```

All methods import and resolve correctly. No runtime test (requires Odoo connection).

## Files Changed

- `logic/price_update_service.py` — +269 insertions

## Concerns

- `analyze_bill()` calls `get_bill_lines()`, `get_product_template()`, `get_previous_bill_line()` which hit Odoo API — may be slow for bills with many lines.
- `_extract_pricelist_rules()` relies on Odoo returning flat parallel arrays — schema mismatch would silently produce partial rows.
- Discount prorata uses same pct for both current and previous bill computation; assumes discount structure is consistent across bills.
