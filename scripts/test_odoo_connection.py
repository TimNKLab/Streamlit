"""CLI script to verify Odoo connectivity using .env configuration."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_odoo_settings
from odoo.connection import OdooConnectionManager, OdooIntegrationError


def format_orders(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "[]"
    summary = [
        {
            "name": row.get("name"),
            "state": row.get("state"),
            "amount_total": row.get("amount_total"),
            "date_order": row.get("date_order"),
        }
        for row in rows
    ]
    return json.dumps(summary, indent=2, ensure_ascii=False)


def main() -> int:
    settings = get_odoo_settings()
    print("Testing Odoo connection with the following settings: \n")
    print(
        json.dumps(
            {
                "host": settings.host,
                "port": settings.port,
                "protocol": settings.protocol,
                "database": settings.database,
                "username": settings.username,
                "version": settings.version,
            },
            indent=2,
        )
    )

    manager = OdooConnectionManager(settings)

    try:
        if manager.ping():
            print("\n✅ Odoo ping successful")
        else:
            print("\n⚠️ Odoo ping failed to respond")

        count = manager.search_count("sale.order")
        print(f"Total sale.order records: {count}")

        sample = manager.search_read(
            model_name="sale.order",
            domain=[("state", "!=", "cancel")],
            fields=["name", "state", "amount_total", "date_order"],
            limit=5,
            order="date_order desc",
        )
        print("\nSample sale.order rows:")
        print(format_orders(sample))

        return 0
    except OdooIntegrationError as exc:
        print(f"\n❌ Failed to communicate with Odoo: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
