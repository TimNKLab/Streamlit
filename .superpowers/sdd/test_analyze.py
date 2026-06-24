"""Quick test of analyze_bill."""
import os
os.environ["ODOO_PROTOCOL"] = "jsonrpc+ssl"
os.environ["ODOO_HOST"] = "REDACTED.dev.odoo.com"
os.environ["ODOO_PORT"] = "443"
os.environ["ODOO_DATABASE"] = "REDACTED"
os.environ["ODOO_USERNAME"] = "robi@nk.com"
os.environ["ODOO_API_KEY"] = "REDACTED"

from logic.price_update_service import PriceUpdateService
s = PriceUpdateService()
rows = s.analyze_bill(1062253)
print(f"Rows returned: {len(rows)}")
if rows:
    for r in rows[:5]:
        print(f"  {r['barcode']} | {r['name']} | modal_lama={r['modal_lama']} | modal_baru={r['modal_baru']} | margin_before={r['margin_before']} | margin_after={r['margin_after']} | promo={r['has_promo']}")
