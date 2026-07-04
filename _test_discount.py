"""Test: fetch vendor bill, show unit prices with discount% + tax multiplier."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from odoo.connection import connection_manager
from logic.cost_update_service import CostUpdateService
from logic.price_update_service import PriceUpdateService

BILL_NUMBER = "NK/POL/100125/10375"

# 1. Find bill ID
moves = connection_manager.search_read(
    "account.move",
    domain=[
        ("move_type", "=", "in_invoice"),
        "|",
        ("name", "=", BILL_NUMBER),
        ("ref", "=", BILL_NUMBER),
    ],
    fields=["id", "name", "ref", "invoice_date", "partner_id"],
    limit=1,
)
if not moves:
    print(f"❌ Bill {BILL_NUMBER} not found")
    sys.exit(1)

bill = moves[0]
bill_id = bill["id"]
print(f"✅ Found bill: {bill.get('name')} (id={bill_id})")
print(f"   Partner: {bill.get('partner_id')}")
print(f"   Date: {bill.get('invoice_date')}")
print()

# 2. Fetch lines WITH discount field
lines = connection_manager.search_read(
    "account.move.line",
    domain=[("move_id", "=", bill_id), ("product_id", "!=", False)],
    fields=["product_id", "price_unit", "quantity", "tax_ids",
            "price_subtotal", "name", "discount"],
)
print(f"   Lines: {len(lines)}")
print()

# 3. Compute tax multipliers inline (same logic as CostUpdateService)
TAX_MULTIPLIERS = {
    "PPN Termasuk": 1.0,
    "PPN Blm Termasuk": 1.11,
    "Non PKP": 1.0,
    "PPN Dikecualikan": 1.0,
}

def get_tax_multiplier(tax_ids):
    if not tax_ids:
        return 1.0
    for tax in tax_ids:
        if isinstance(tax, (list, tuple)) and len(tax) >= 2:
            name = str(tax[1])
            for key, mult in TAX_MULTIPLIERS.items():
                if key in name:
                    return mult
        elif isinstance(tax, int):
            try:
                taxes = connection_manager.search_read(
                    "account.tax", domain=[("id", "=", tax)], fields=["id", "name"]
                )
                for t in taxes:
                    name = str(t.get("name", ""))
                    for key, mult in TAX_MULTIPLIERS.items():
                        if key in name:
                            return mult
            except Exception:
                pass
    return 1.0

# 4. Separate positive and discount/negative lines
positive = [l for l in lines if float(l.get("price_unit", 0)) > 0]
discount_lines = [l for l in lines if float(l.get("price_unit", 0)) < 0]

print("=" * 100)
print(f"{'Product':30s} {'Price Unit':>12s} {'Disc%':>6s} {'Qty':>6s} {'After Disc':>12s} {'Tax Mult':>8s} {'Final':>12s}")
print("=" * 100)

for line in positive:
    pid = line.get("product_id")
    product_name = str(pid[1] if isinstance(pid, (list, tuple)) and len(pid) > 1 else pid)
    price_unit = float(line.get("price_unit", 0))
    discount_pct = float(line.get("discount", 0) or 0) / 100
    qty = float(line.get("quantity", 1))
    tax_ids = line.get("tax_ids", [])
    tax_mult = get_tax_multiplier(tax_ids)

    price_after_disc = price_unit * (1 - discount_pct)
    final = round(price_after_disc * tax_mult)

    print(f"{product_name[:28]:30s} {price_unit:>12,.0f} {discount_pct*100:>5.0f}% {qty:>6.0f} {price_after_disc:>12,.0f} {tax_mult:>8.2f} {final:>12,}")

print("=" * 100)
print()

# Show negative lines too
if discount_lines:
    print("── Discount lines (negative price_unit) ──")
    for line in discount_lines:
        pid = line.get("product_id")
        name = str(pid[1] if isinstance(pid, (list, tuple)) and len(pid) > 1 else pid)
        pu = float(line.get("price_unit", 0))
        q = float(line.get("quantity", 1))
        print(f"   {name:30s} {pu:>12,.0f} × {q:>6.0f}")
    print()

# Show total of final prices
totals = []
for line in positive:
    price_unit = float(line.get("price_unit", 0))
    discount_pct = float(line.get("discount", 0) or 0) / 100
    qty = float(line.get("quantity", 1))
    tax_ids = line.get("tax_ids", [])
    tax_mult = get_tax_multiplier(tax_ids)
    price_after_disc = price_unit * (1 - discount_pct)
    final = round(price_after_disc * tax_mult)
    totals.append(final * qty)

print(f"Total (final × qty): {sum(totals):,.0f}")
