"""Higher-level service helpers for querying Odoo objects."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Sequence

from odoo.connection import OdooIntegrationError, connection_manager

SalesOrderRecord = Dict[str, Any]


@dataclass(frozen=True)
class SalesMetrics:
    total_confirmed_orders: int
    total_draft_orders: int
    total_cancelled_orders: int
    pos_order_count: int


def get_recent_sales_orders(limit: int = 10) -> List[SalesOrderRecord]:
    """Retrieve recent (non-cancelled) sale orders ordered by date desc."""

    return connection_manager.search_read(
        model_name="sale.order",
        domain=[("state", "!=", "cancel")],
        fields=["name", "date_order", "state", "partner_id"],
        order="date_order desc",
        limit=limit,
    )


def get_recent_pos_orders(
    *,
    limit: int | None = 10,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
) -> List[SalesOrderRecord]:
    """Retrieve POS orders within the given window ordered by most recent."""

    # Define WIB timezone (UTC+7)
    WIB = ZoneInfo("Asia/Jakarta")

    end_dt = end_dt or datetime.now(WIB)
    start_dt = start_dt or (end_dt - timedelta(days=1))

    start_str = start_dt.astimezone(WIB).strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_dt.astimezone(WIB).strftime("%Y-%m-%d %H:%M:%S")

    return connection_manager.search_read(
        model_name="pos.order",
        domain=[
            ("date_order", ">=", start_str),
            ("date_order", "<=", end_str),
            ("state", "!=", "cancelled"),
        ],
        fields=["name", "date_order", "state", "partner_id"],
        order="date_order desc",
        limit=limit,
    )


def get_sales_metrics(
    *,
    pos_start_dt: datetime | None = None,
    pos_end_dt: datetime | None = None,
) -> SalesMetrics:
    """Aggregate key sales metrics from Odoo."""

    confirmed_domain: Sequence = [("state", "in", ["sale", "done"])]
    draft_domain: Sequence = [("state", "=", "draft")]
    cancelled_domain: Sequence = [("state", "=", "cancel")]

    confirmed_orders = connection_manager.search_count("sale.order", confirmed_domain)
    draft_orders = connection_manager.search_count("sale.order", draft_domain)
    cancelled_orders = connection_manager.search_count("sale.order", cancelled_domain)

    pos_orders = get_recent_pos_orders(limit=None, start_dt=pos_start_dt, end_dt=pos_end_dt)

    return SalesMetrics(
        total_confirmed_orders=confirmed_orders,
        total_draft_orders=draft_orders,
        total_cancelled_orders=cancelled_orders,
        pos_order_count=len(pos_orders),
    )


def check_odoo_health() -> bool:
    """Return True if the Odoo backend responds to a ping."""

    return connection_manager.ping()


def safe_call(func, fallback):
    try:
        return func()
    except OdooIntegrationError:
        return fallback
