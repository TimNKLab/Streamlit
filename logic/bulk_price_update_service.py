"""Service for bulk price update from uploaded file — validate, check promo, update."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from odoo.connection import OdooIntegrationError, connection_manager
from logic.schedule_storage import ScheduleStorage


class BulkPriceUpdateService:
    """Validate and execute bulk price changes from uploaded data."""

    def __init__(self):
        self.conn = connection_manager

    # ── Barcode lookup ──────────────────────────────────────────────────

    def lookup_barcode(self, barcode: str) -> Optional[Dict[str, Any]]:
        """Find product by barcode. Returns {id, tmpl_id, name, list_price} or None."""
        try:
            products = self.conn.search_read(
                "product.product",
                domain=[("barcode", "=", barcode)],
                fields=["id", "barcode", "name", "list_price", "product_tmpl_id"],
            )
        except Exception:
            return None
        if not products:
            return None
        p = products[0]
        tmpl = p.get("product_tmpl_id")
        return {
            "id": p["id"],
            "barcode": p.get("barcode"),
            "name": str(p.get("name") or ""),
            "list_price": float(p.get("list_price") or 0),
            "template_id": int(tmpl[0]) if isinstance(tmpl, (list, tuple)) and tmpl else None,
        }

    # ── Pricelist / promo ───────────────────────────────────────────────

    def get_pricelist_rules(self, template_id: int) -> List[Dict[str, Any]]:
        """Fetch pricelist rules for a product template."""
        try:
            return self.conn.search_read(
                "product.pricelist.item",
                domain=[("product_tmpl_id", "=", template_id)],
                fields=["id", "pricelist_id", "fixed_price", "date_start", "date_end"],
            )
        except Exception:
            return []

    def _is_active_promo_rule(self, rule: Dict[str, Any]) -> bool:
        """Check if a single pricelist rule is an active promo.
        Mirrors PriceUpdateService._get_active_promo_rule logic.
        """
        ds_str = rule.get("date_start")
        if not ds_str:
            return False
        try:
            ds = datetime.strptime(str(ds_str)[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return False
        today = date.today()
        if ds > today:
            return False
        de = rule.get("date_end")
        if de:
            try:
                de_date = datetime.strptime(str(de)[:10], "%Y-%m-%d").date()
                if de_date < today:
                    return False
            except (ValueError, TypeError):
                pass
        fp = rule.get("fixed_price")
        if not fp or float(fp) <= 0:
            return False
        return True

    def has_active_promo(self, rules: List[Dict[str, Any]]) -> bool:
        return any(self._is_active_promo_rule(r) for r in rules)

    def _get_latest_promo_end(self, rules: List[Dict[str, Any]]) -> Optional[str]:
        """Return the latest date_end among active promo rules, or None."""
        latest: Optional[date] = None
        for r in rules:
            if not self._is_active_promo_rule(r):
                continue
            de = r.get("date_end")
            if not de:
                continue
            try:
                d = datetime.strptime(str(de)[:10], "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue
            if latest is None or d > latest:
                latest = d
        return latest.isoformat() if latest else None

    def _promo_period_str(self, rules: List[Dict[str, Any]]) -> str:
        """Format promo period string like '01/07/2026 s.d 15/07/2026'.
        Mirrors PriceUpdateService logic but reads from pricelist items.
        """
        for r in rules:
            if not self._is_active_promo_rule(r):
                continue
            ds = str(r.get("date_start", ""))[:10] if r.get("date_start") else ""
            de = str(r.get("date_end", ""))[:10] if r.get("date_end") else ""
            if ds and de:
                try:
                    ds_fmt = datetime.strptime(ds, "%Y-%m-%d").strftime("%d/%m/%Y")
                    de_fmt = datetime.strptime(de, "%Y-%m-%d").strftime("%d/%m/%Y")
                    return f"{ds_fmt} s.d {de_fmt}"
                except ValueError:
                    return f"{ds} s.d {de}"
            elif ds:
                return f"mulai {ds}"
        return "-"

    def has_fixed_price(self, rules: List[Dict[str, Any]]) -> bool:
        """Check if any pricelist rule has a fixed_price > 0 (active or not)."""
        return any(float(r.get("fixed_price") or 0) > 0 for r in rules)

    # ── Write operations ────────────────────────────────────────────────

    def update_list_price(self, template_id: int, sales_price: float) -> bool:
        """Update list_price on product.template."""
        try:
            return bool(self.conn.write(
                "product.template",
                [template_id],
                {"list_price": sales_price},
            ))
        except Exception as exc:
            raise OdooIntegrationError(f"Gagal update list_price: {exc}") from exc

    def update_fixed_price(self, rule_id: int, fixed_price: float) -> bool:
        """Update fixed_price on a pricelist item."""
        try:
            return bool(self.conn.write(
                "product.pricelist.item",
                [rule_id],
                {"fixed_price": fixed_price},
            ))
        except Exception as exc:
            raise OdooIntegrationError(f"Gagal update fixed_price: {exc}") from exc

    # ── Validate & prepare rows ─────────────────────────────────────────

    def validate_rows(self, raw_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Validate uploaded rows against Odoo. Returns enriched rows.

        Two-phase:
          1. Basic validation + barcode lookup → collect product_ids
          2. Batch loyalty.program query → promo detection (same as PriceUpdateService)
          3. Enrich each row with promo + pricelist data
        """
        # ── Phase 1: basic validation + barcode lookup ────────────────
        results: List[Dict[str, Any]] = []
        product_ids: List[int] = []
        for i, row in enumerate(raw_rows):
            barcode = str(row.get("Barcode") or row.get("barcode") or "").strip()
            sales_price = row.get("Sales Price") or row.get("sales_price") or row.get("Harga Jual")
            fixed_price = row.get("Fixed Price") or row.get("fixed_price")
            tanggal_raw = row.get("Tanggal Update") or row.get("tanggal_update") or row.get("Tanggal")

            out: Dict[str, Any] = {
                "row_no": i + 1,
                "barcode": barcode,
                "name": "",
                "sales_price": _safe_float(sales_price),
                "fixed_price": _safe_float(fixed_price),
                "tanggal_update": _parse_tanggal(tanggal_raw),
                "selected": False,
                "found": False,
                "error": None,
                "current_list_price": 0.0,
                "template_id": None,
                "product_id": None,
                "pricelist_rules": [],
                "has_fixed_price": False,
                "has_active_promo": False,
                "promo_period_str": "",
                "promo_warning": None,
                "status": "Pending",
            }

            if not barcode:
                out["error"] = "Barcode kosong"
                out["status"] = "Error"
                results.append(out)
                continue

            if out["sales_price"] is None or out["sales_price"] <= 0:
                out["error"] = "Sales price tidak valid"
                out["status"] = "Error"
                results.append(out)
                continue

            product = self.lookup_barcode(barcode)
            if not product:
                out["error"] = "Barcode tidak ditemukan di Odoo"
                out["status"] = "Error"
                results.append(out)
                continue

            out["found"] = True
            out["name"] = product["name"]
            out["current_list_price"] = product["list_price"]
            out["template_id"] = product["template_id"]
            out["product_id"] = product["id"]
            product_ids.append(product["id"])
            results.append(out)

        # ── Phase 2: batch loyalty.program (same as PriceUpdateService) ──
        # More reliable than scanning pricelist items for date rules.
        promo_map: Dict[int, Dict[str, Any]] = {}
        if product_ids:
            try:
                active_progs = self.conn.search_read(
                    "loyalty.program",
                    domain=[
                        ("active", "=", True),
                        ("trigger_product_ids", "in", product_ids),
                    ],
                    fields=["id", "name", "date_from", "date_to", "trigger_product_ids"],
                )
                today = date.today()
                for prog in active_progs:
                    df = prog.get("date_from")
                    dt = prog.get("date_to")
                    try:
                        start_ok = datetime.strptime(str(df)[:10], "%Y-%m-%d").date() <= today if df else True
                        end_ok = datetime.strptime(str(dt)[:10], "%Y-%m-%d").date() >= today if dt else True
                    except (ValueError, TypeError):
                        continue
                    if not (start_ok and end_ok):
                        continue
                    affected = prog.get("trigger_product_ids") or []
                    for v in affected:
                        if v in product_ids and v not in promo_map:
                            promo_map[v] = {
                                "name": prog.get("name"),
                                "date_from": df,
                                "date_to": dt,
                            }
            except Exception:
                pass  # Loyalty optional — falls through silently

        # ── Phase 3: enrich with promo + pricelist ────────────────────────
        for out in results:
            if not out.get("found") or not out["template_id"]:
                continue

            product_id = out["product_id"]
            rules = self.get_pricelist_rules(out["template_id"])
            out["pricelist_rules"] = rules
            out["has_fixed_price"] = self.has_fixed_price(rules)

            # Promo detection: loyalty.program (primary) + pricelist rules (fallback)
            promo = promo_map.get(product_id)
            out["has_active_promo"] = promo is not None or self.has_active_promo(rules)

            if out["has_active_promo"]:
                # Prefer loyalty data for period string, fallback to pricelist
                if promo:
                    ds = str(promo.get("date_from", ""))[:10] if promo.get("date_from") else ""
                    de = str(promo.get("date_to", ""))[:10] if promo.get("date_to") else ""
                    out["promo_period_str"] = f"{ds} s.d {de}" if ds and de else (f"mulai {ds}" if ds else "-")
                    latest_end = de
                else:
                    out["promo_period_str"] = self._promo_period_str(rules)
                    latest_end = self._get_latest_promo_end(rules)

                if latest_end:
                    try:
                        end_date = datetime.strptime(latest_end, "%Y-%m-%d").date()
                        next_day = end_date + timedelta(days=1)
                        # Normalise existing tanggal_update back to date for comparison
                        existing = _parse_tanggal(out["tanggal_update"])
                        existing_dt = datetime.strptime(existing, "%Y-%m-%d").date() if existing else None
                        if existing_dt is None or next_day > existing_dt:
                            out["tanggal_update"] = next_day.isoformat()
                    except (ValueError, TypeError):
                        pass

                out["promo_warning"] = (
                    "Produk sedang dalam promo aktif. "
                    f"Tanggal update diatur ke {_fmt_tanggal_display(out['tanggal_update'])} "
                    f"(sehari setelah promo berakhir)."
                )
                out["status"] = "⚠️ Promo Aktif"
                out["selected"] = True
            else:
                out["selected"] = True
                out["status"] = "✅ Siap"

            # Carry forward current fixed_price if not specified
            if out["fixed_price"] is None and out["has_fixed_price"]:
                for r in rules:
                    fp = r.get("fixed_price")
                    if fp and float(fp) > 0:
                        out["fixed_price"] = float(fp)
                        break

        return results

    # ── Execute updates (selected rows only) ────────────────────────────

    def execute_updates(
        self, validated: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Execute price updates for selected rows. Returns summary."""
        result: Dict[str, Any] = {"success": 0, "skipped": 0, "errors": [], "warnings": []}

        for row in validated:
            if not row.get("selected"):
                result["skipped"] += 1
                continue
            if row.get("error") or row["status"].startswith("Error"):
                result["skipped"] += 1
                continue

            try:
                if row["template_id"]:
                    self.update_list_price(row["template_id"], row["sales_price"])

                if row["fixed_price"] is not None and row["fixed_price"] > 0:
                    rules = row.get("pricelist_rules", [])
                    rule_to_update = None
                    for r in rules:
                        rid = r.get("id")
                        if rid:
                            rule_to_update = int(rid)
                            break
                    if rule_to_update:
                        self.update_fixed_price(rule_to_update, row["fixed_price"])

                row["status"] = "✅ Updated"
                result["success"] += 1

            except OdooIntegrationError as e:
                result["errors"].append((row["barcode"], str(e)))
                row["status"] = "❌ Gagal"

        return result

    # ── Schedule metadata persistence (via Odoo ir.attachment) ─────────

    def save_scheduled(self, validated: List[Dict[str, Any]], label: str = "") -> str:
        """Save selected rows with a future tanggal_update as Odoo attachment.
        Returns the attachment name or empty string.
        """
        rows = [
            {
                "barcode": r["barcode"],
                "name": r["name"],
                "sales_price": r["sales_price"],
                "fixed_price": r["fixed_price"],
                "tanggal_update": r["tanggal_update"],
                "template_id": r["template_id"],
                "has_fixed_price": r["has_fixed_price"],
            }
            for r in validated
            if r.get("selected") and r.get("tanggal_update") and r["template_id"]
        ]
        if not rows:
            return ""
        storage = ScheduleStorage()
        name = storage.save(rows, label=label)
        return name or ""

    def list_scheduled(self) -> List[Dict[str, Any]]:
        """List all pending schedule attachments from Odoo."""
        return ScheduleStorage().list_all()

    def execute_scheduled_file(self, attach_id: int) -> Dict[str, Any]:
        """Execute a schedule by attachment ID. Returns summary."""
        storage = ScheduleStorage()
        data = storage.get_by_id(attach_id)
        if not data:
            return {"success": 0, "skipped": 0, "errors": [("?", "Schedule not found")], "file_id": attach_id}

        rows = data.get("rows", [])
        result: Dict[str, Any] = {"success": 0, "skipped": 0, "errors": [], "file_id": attach_id}

        for row in rows:
            tgl = row.get("tanggal_update", "")
            if tgl and tgl > date.today().isoformat():
                result["skipped"] += 1
                continue  # not yet due

            try:
                self.update_list_price(row["template_id"], row["sales_price"])
                if row.get("fixed_price") and row["fixed_price"] > 0:
                    rules = self.get_pricelist_rules(row["template_id"])
                    rule_id = None
                    for r in rules:
                        rid = r.get("id")
                        if rid:
                            rule_id = int(rid)
                            break
                    if rule_id:
                        self.update_fixed_price(rule_id, row["fixed_price"])
                result["success"] += 1
            except OdooIntegrationError as e:
                result["errors"].append((row.get("barcode", "?"), str(e)))

        # Cleanup: hapus attachment jika semua sukses, rename jika ada yg gagal
        if result["errors"]:
            storage.mark_executed(attach_id)
        else:
            storage.delete(attach_id)

        return result

    @staticmethod
    def remove_scheduled_file(attach_id: int) -> None:
        ScheduleStorage().delete(attach_id)


def _fmt_tanggal_display(iso_str: Optional[str]) -> str:
    """YYYY-MM-DD → DD/MM/YYYY or '-'."""
    if not iso_str:
        return "-"
    try:
        return datetime.strptime(iso_str[:10], "%Y-%m-%d").date().strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return iso_str[:10]


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_tanggal(v: Any) -> Optional[str]:
    """Parse date from various formats, return ISO YYYY-MM-DD or None."""
    if v is None:
        return None
    if isinstance(v, date):
        return v.isoformat()
    s = str(v).strip()
    if not s:
        return None
    # DD/MM/YYYY
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s[:10], fmt).date().isoformat()
        except ValueError:
            continue
    return None
