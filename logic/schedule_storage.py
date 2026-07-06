"""Schedule persistence — stores/loads bulk-price-schedule JSON via Odoo ir.attachment.

Survives redeploy on Streamlit Cloud because data lives in Odoo's database.
"""
from __future__ import annotations

import base64
import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from odoo.connection import connection_manager

_ATTACH_RES_MODEL = "res.company"
_ATTACH_RES_ID = 1
_NAME_PREFIX = "bulk_schedule_"


class ScheduleStorage:
    """Read/write schedule metadata via Odoo ir.attachment."""

    def __init__(self):
        self.conn = connection_manager

    # ── CRUD ────────────────────────────────────────────────────────────

    def save(self, rows: List[Dict[str, Any]], label: str = "") -> Optional[str]:
        """Save rows as an ir.attachment. Returns attachment name or None."""
        if not rows:
            return None
        today_str = date.today().isoformat()
        ts = datetime.now().strftime("%H%M%S")
        name = f"{_NAME_PREFIX}{today_str}_{ts}.json"

        data = {
            "label": label or f"Scheduled {today_str}",
            "created_at": datetime.now().isoformat(),
            "rows": rows,
        }
        json_bytes = json.dumps(data, indent=2).encode()
        b64 = base64.b64encode(json_bytes).decode()

        try:
            self.conn.create("ir.attachment", {
                "name": name,
                "res_model": _ATTACH_RES_MODEL,
                "res_id": _ATTACH_RES_ID,
                "datas": b64,
                "mimetype": "application/json",
            })
            return name
        except Exception:
            return None

    def list_all(self) -> List[Dict[str, Any]]:
        """Return all pending schedule attachments."""
        try:
            attachments = self.conn.search_read(
                "ir.attachment",
                domain=[("name", "like", f"{_NAME_PREFIX}%"),
                        ("res_model", "=", _ATTACH_RES_MODEL)],
                fields=["id", "name", "datas", "create_date"],
            )
        except Exception:
            return []

        today = date.today()
        result = []
        for att in attachments:
            try:
                raw = base64.b64decode(att["datas"]).decode()
                data = json.loads(raw)
            except (Exception, json.JSONDecodeError):
                continue

            all_tgl = [r["tanggal_update"] for r in data.get("rows", []) if r.get("tanggal_update")]
            due = any(t <= today.isoformat() for t in all_tgl)

            result.append({
                "id": att["id"],
                "name": att["name"],
                "label": data.get("label", att["name"]),
                "created_at": data.get("created_at", str(att.get("create_date", ""))),
                "total_rows": len(data.get("rows", [])),
                "rows": data.get("rows", []),
                "is_due": due,
            })
        return result

    def get_by_id(self, attach_id: int) -> Optional[Dict[str, Any]]:
        try:
            att = self.conn.search_read(
                "ir.attachment",
                domain=[("id", "=", attach_id)],
                fields=["id", "name", "datas", "create_date"],
            )
            if not att:
                return None
            raw = base64.b64decode(att[0]["datas"]).decode()
            return json.loads(raw)
        except Exception:
            return None

    def delete(self, attach_id: int) -> bool:
        try:
            return bool(self.conn.unlink("ir.attachment", [attach_id]))
        except Exception:
            return False

    def mark_executed(self, attach_id: int) -> bool:
        """Rename attachment to mark it as done (keep for audit)."""
        try:
            att = self.conn.search_read(
                "ir.attachment",
                domain=[("id", "=", attach_id)],
                fields=["name"],
            )
            if not att:
                return False
            old_name = att[0]["name"]
            new_name = old_name.replace(_NAME_PREFIX, "executed_")
            return bool(self.conn.write("ir.attachment", [attach_id], {"name": new_name}))
        except Exception:
            return False
