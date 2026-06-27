"""Probe mail.tracking.value model structure."""
from __future__ import annotations

import json, sys
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

# 1. Get all fields of mail.tracking.value
fields = manager.search_read(
    "ir.model.fields",
    domain=[("model", "=", "mail.tracking.value")],
    fields=["name", "ttype", "field_description", "tracking"],
    limit=50,
)
print("=== mail.tracking.value fields ===")
for f in fields:
    print(f"  {f['name']:25s} type={f['ttype']:15s} desc={f.get('field_description', '')}")

# 2. Get field info for "field" on mail.tracking.value
fe = manager.search_read(
    "ir.model.fields",
    domain=[("model", "=", "mail.tracking.value"), ("name", "=", "field")],
    fields=["name", "ttype", "relation", "field_description"],
)
print(f"\n=== 'field' on mail.tracking.value ===")
if fe:
    print(json.dumps(fe[0], indent=2, default=str))
else:
    print("  No 'field' field found")

# 3. Loyalty program check
print("\n=== loyalty.program ===")
try:
    lp = manager.search_read(
        "loyalty.program",
        domain=[("active", "=", True)],
        fields=["id", "name", "active", "product_ids"],
        limit=5,
    )
    print(f"  Active programs: {manager.search_count('loyalty.program', [('active','=',True)])}")
    for p in lp:
        pids = p.get("product_ids") or []
        print(f"  id={p['id']} name={p.get('name')} products={len(pids)}")
except Exception as e:
    print(f"  Error: {e}")
