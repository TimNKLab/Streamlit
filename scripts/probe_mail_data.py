"""Probe mail.tracking.value with correct field_id for list_price."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_odoo_settings
from odoo.connection import OdooConnectionManager

settings = get_odoo_settings()
manager = OdooConnectionManager(settings)

if not manager.ping():
    print("Ping failed")
    raise SystemExit(1)

# 1. Get field_id for list_price on product.template
fields = manager.search_read(
    "ir.model.fields",
    domain=[("model", "=", "product.template"), ("name", "=", "list_price")],
    fields=["id", "name", "ttype"],
)
print(f"=== 1. ir.model.fields id for product.template.list_price ===")
if not fields:
    print("NOT FOUND - aborting")
    raise SystemExit(1)
fid = fields[0]["id"]
print(f"field_id = {fid}")

# 2. Query mail.tracking.value for this field
tv = manager.search_read(
    "mail.tracking.value",
    domain=[("field_id", "=", fid)],
    fields=["create_date", "mail_message_id", "new_value_float", "old_value_float"],
    order="create_date desc",
    limit=20,
)
print(f"\n=== 2. mail.tracking.value (field_id={fid}) ===")
print(f"Total records returned: {len(tv)}")
if not tv:
    print("NO DATA - fallback to write_date expected")
    raise SystemExit(0)

for t in tv[:5]:
    mid = t.get("mail_message_id")
    mid_str = f"[{mid[0]}, {mid[1]}]" if isinstance(mid, (list, tuple)) else str(mid)
    print(f"  date={t.get('create_date')} msg={mid_str} old={t.get('old_value_float')} new={t.get('new_value_float')}")

# 3. Get linked mail.message res_ids
msg_ids = []
for t in tv:
    mid = t.get("mail_message_id")
    if isinstance(mid, (list, tuple)) and mid:
        msg_ids.append(mid[0])

msgs = manager.search_read(
    "mail.message",
    domain=[("id", "in", msg_ids[:20])],
    fields=["id", "res_id", "model", "date"],
)
print(f"\n=== 3. Linked mail.messages (res_id mapping) ===")
res_ids_found = set()
for m in msgs:
    print(f"  id={m['id']} res_id={m['res_id']} model={m.get('model')} date={m.get('date')}")
    if m.get("model") == "product.template":
        res_ids_found.add(m["res_id"])

print(f"\nUnique product.template IDs in sample: {sorted(res_ids_found)}")
print(f"\n=== VERDICT ===")
print(f"Tracking data EXISTS, price-specific timestamps feasible")
