"""Probe Odoo for:
1. Does product.pricelist.list_price have tracking=True?
2. Is there mail.tracking.value data for list_price changes?
3. Does loyalty.program exist with active=True records?"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_odoo_settings
from odoo.connection import OdooConnectionManager, OdooIntegrationError


def main() -> int:
    settings = get_odoo_settings()
    manager = OdooConnectionManager(settings)

    if not manager.ping():
        print("❌ Odoo ping failed")
        return 1

    # 1. Check if list_price has tracking on product.template
    print("=== 1. ir.model.fields: product.template.list_price.tracking ===")
    fields = manager.search_read(
        "ir.model.fields",
        domain=[("model", "=", "product.template"), ("name", "=", "list_price")],
        fields=["id", "name", "model", "tracking", "ttype", "field_description"],
    )
    if fields:
        f = fields[0]
        print(f"  field: {f.get('name')}, type: {f.get('ttype')}")
        print(f"  tracking value: {f.get('tracking')!r}")
        print(f"  description: {f.get('field_description')}")
        if f.get("tracking"):
            print("  ✅ list_price HAS tracking enabled")
        else:
            print("  ❌ list_price does NOT have tracking enabled")
    else:
        print("  ❌ field not found")

    # 2. Sample mail.tracking.value records
    print("\n=== 2. mail.tracking.value sample (list_price) ===")
    tv_count = manager.search_count(
        "mail.tracking.value",
        domain=[("field", "=", "list_price")],
    )
    print(f"  Total tracking records for list_price: {tv_count}")

    if tv_count > 0:
        tv_sample = manager.search_read(
            "mail.tracking.value",
            domain=[("field", "=", "list_price")],
            fields=["create_date", "mail_message_id", "old_value_float", "new_value_float", "field"],
            order="create_date desc",
            limit=5,
        )
        for tv in tv_sample:
            msg_id = tv.get("mail_message_id")
            if isinstance(msg_id, (list, tuple)):
                msg_id = f"[{msg_id[0]}, {msg_id[1]}]"
            print(f"  create_date={tv['create_date']} msg={msg_id} "
                  f"old={tv.get('old_value_float')} new={tv.get('new_value_float')}")

        # Get the message IDs to find res_id
        msg_ids = []
        for tv in tv_sample:
            mid = tv.get("mail_message_id")
            if isinstance(mid, (list, tuple)) and mid:
                msg_ids.append(mid[0])
        if msg_ids:
            msgs = manager.search_read(
                "mail.message",
                domain=[("id", "in", msg_ids)],
                fields=["id", "res_id", "model", "date"],
            )
            print(f"\n  --- Linked mail.messages ---")
            for m in msgs:
                print(f"  id={m['id']} res_id={m['res_id']} model={m['model']} date={m['date']}")
    else:
        print("  ✅ No list_price tracking found — fallback to write_date expected")

    # 3. Check loyalty.program
    print("\n=== 3. loyalty.program (active=True) ===")
    try:
        lp_count = manager.search_count(
            "loyalty.program",
            domain=[("active", "=", True)],
        )
        print(f"  Total active loyalty programs: {lp_count}")
        if lp_count > 0:
            lp_sample = manager.search_read(
                "loyalty.program",
                domain=[("active", "=", True)],
                fields=["id", "name", "active", "program_type", "product_ids"],
                limit=5,
            )
            for lp in lp_sample:
                pids = lp.get("product_ids", [])
                pid_count = len(pids) if isinstance(pids, list) else 0
                print(f"  id={lp['id']} name={lp.get('name')} type={lp.get('program_type')} products={pid_count}")
    except Exception as e:
        print(f"  ❌ loyalty.program not available: {e}")

    # 4. Bonus: check product.template structure
    print("\n=== 4. Sample product.templates with tracked fields ===")
    templates = manager.search_read(
        "product.template",
        domain=[],
        fields=["id", "name", "list_price", "write_date"],
        limit=3,
        order="write_date desc",
    )
    for t in templates:
        print(f"  id={t['id']} name={t.get('name')} price={t.get('list_price')} write_date={t.get('write_date')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
