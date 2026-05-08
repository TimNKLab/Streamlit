"""Halaman Streamlit untuk alat Pergerakan Internal."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date as date_cls
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
import pandas as pd
import streamlit as st

load_dotenv()

from odoo.stock_services import (
    StockQuantDiff,
    get_candidate_locations_for_products,
    get_location_by_complete_name,
    list_internal_locations,
    get_products_uom_ids,
    get_stock_quant_diffs_for_user_at_location,
    get_internal_picking_type_id,
    list_users,
)
from odoo.connection import connection_manager


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class InternalMoveContact:
    label: str
    name: str
    partner_id: int | None = None


# ---------------------------------------------------------------------------
# Cached Odoo calls
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def _load_contacts() -> List[InternalMoveContact]:
    contacts_raw: Any = None

    secrets_obj = getattr(st, "secrets", {}) or {}
    try:
        secrets: Dict[str, Any] = dict(secrets_obj)
    except Exception:
        secrets = {}

    internal_moves = secrets.get("internal_moves")
    if isinstance(internal_moves, Mapping):
        contacts_raw = internal_moves.get("contacts")

    if contacts_raw is None:
        env_val = os.getenv("INTERNAL_MOVES_CONTACTS")
        if env_val:
            try:
                contacts_raw = json.loads(env_val)
            except json.JSONDecodeError:
                pass

    if not isinstance(contacts_raw, list):
        return []

    result = []
    for item in contacts_raw:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        name = item.get("name")
        partner_id = item.get("partner_id")

        parsed_partner_id: int | None = None
        if isinstance(partner_id, int):
            parsed_partner_id = partner_id
        elif isinstance(partner_id, str) and partner_id.strip().isdigit():
            parsed_partner_id = int(partner_id.strip())

        parsed_name: str = ""
        if isinstance(name, str) and name.strip():
            parsed_name = name.strip()

        if isinstance(label, str) and label.strip() and (parsed_name or parsed_partner_id is not None):
            result.append(InternalMoveContact(
                label=label.strip(),
                name=parsed_name,
                partner_id=parsed_partner_id,
            ))
    return result


@st.cache_data(ttl=300)
def _list_users():
    return list_users()


@st.cache_data(ttl=3600)
def _get_picking_type_id() -> int | None:
    return get_internal_picking_type_id()


@st.cache_data(ttl=600)
def _get_location(name: str):
    return get_location_by_complete_name(name)


@st.cache_data(ttl=600)
def _list_locations(query: str = "", limit: int = 200):
    return list_internal_locations(query=query) if query else list_internal_locations(limit=limit)


@st.cache_data(ttl=120)
def _get_candidate_locations_batch(
    product_ids: Tuple[int, ...],
    exclude_location_id: int,
) -> Dict[int, List]:
    # Tuple arg so st.cache_data dapat hash dengan benar
    return get_candidate_locations_for_products(
        product_ids=list(product_ids),
        exclude_location_id=exclude_location_id,
    )


# ---------------------------------------------------------------------------
# Business logic
# ---------------------------------------------------------------------------

def _build_planned_moves(
    diffs: List[StockQuantDiff],
    display_location,
) -> Tuple[List[Dict[str, Any]], Dict[Tuple[int, int], int]]:
    """Hitung rencana pergerakan dan pengelompokan. Hanya dipanggil saat load.

    Satu RPC batch untuk semua kandidat lokasi, bukan N RPC per SKU.
    """
    planned_moves: List[Dict[str, Any]] = []
    group_counts: Dict[Tuple[int, int], int] = {}

    active_diffs = [d for d in diffs if d.diff_qty != 0]
    if not active_diffs:
        return planned_moves, group_counts

    # Satu RPC untuk semua produk sekaligus
    product_ids = tuple({d.product_id for d in active_diffs})
    candidates_by_product = _get_candidate_locations_batch(product_ids, display_location.id)

    for d in active_diffs:
        qty_needed = abs(d.diff_qty)
        direction = "minus" if d.diff_qty < 0 else "plus"
        candidates = candidates_by_product.get(d.product_id, [])

        if not candidates:
            planned_moves.append({
                "quant_id": d.quant_id,
                "barcode": d.barcode,
                "product_name": d.product_name,
                "product_id": d.product_id,
                "direction": direction,
                "qty_needed": qty_needed,
                "qty_to_move": 0,
                "remainder": qty_needed,
                "src_location_name": "-",
                "dest_location_name": "-",
                "src_location_id": None,
                "dest_location_id": None,
                "blocked": True,
                "block_reason": "Tidak ada lokasi internal dengan qty > 0",
            })
            continue

        candidate = candidates[0]

        # FIX: was "tambah" which never matched — should be "plus"
        if direction == "plus":
            src_location_id = candidate.location_id
            src_location_name = candidate.location_name
            dest_location_id = display_location.id
            dest_location_name = display_location.complete_name
            qty_to_move = min(qty_needed, candidate.qty)
        else:
            src_location_id = display_location.id
            src_location_name = display_location.complete_name
            dest_location_id = candidate.location_id
            dest_location_name = candidate.location_name
            qty_to_move = min(qty_needed, d.display_qty)

        remainder = qty_needed - qty_to_move
        is_blocked = remainder > 0

        planned_moves.append({
            "quant_id": d.quant_id,
            "barcode": d.barcode,
            "product_name": d.product_name,
            "product_id": d.product_id,
            "direction": direction,
            "qty_needed": qty_needed,
            "qty_to_move": qty_to_move,
            "remainder": remainder,
            "src_location_name": src_location_name,
            "dest_location_name": dest_location_name,
            "src_location_id": src_location_id,
            "dest_location_id": dest_location_id,
            "blocked": is_blocked,
            "block_reason": "Stok tidak cukup (pemindahan sebagian)" if is_blocked else "",
        })

        if not is_blocked:
            key = (int(src_location_id), int(dest_location_id))
            group_counts[key] = group_counts.get(key, 0) + 1

    return planned_moves, group_counts


def _group_clean_moves(
    planned_moves: List[Dict[str, Any]],
) -> Dict[Tuple[int, int], List[Dict[str, Any]]]:
    groups: Dict[Tuple[int, int], List[Dict[str, Any]]] = {}
    for m in planned_moves:
        if m["blocked"] or float(m.get("qty_to_move") or 0) <= 0:
            continue
        key = (int(m["src_location_id"]), int(m["dest_location_id"]))
        groups.setdefault(key, []).append(m)
    return groups


def _create_transfers(
    groups: Dict[Tuple[int, int], List[Dict[str, Any]]],
    partner_id: int,
    user_name: str,
    picking_type_id: int,
    uom_map: Dict[int, Any],
    validate: bool,
) -> List[int]:
    """Buat picking dan move di Odoo. Raise exception jika gagal."""
    today = date_cls.today().strftime("%Y-%m-%d")
    origin = f"Stock Opname tanggal {today}"
    created: List[int] = []

    for (src_id, dest_id), items in groups.items():
        picking_id = connection_manager.create("stock.picking", {
            "picking_type_id": picking_type_id,
            "location_id": src_id,
            "location_dest_id": dest_id,
            "partner_id": partner_id,
            "origin": origin,
        })
        created.append(int(picking_id))

        for it in items:
            pid = int(it["product_id"])
            connection_manager.create("stock.move", {
                "name": str(it.get("barcode") or it.get("product_name") or "Pergerakan Internal"),
                "picking_id": picking_id,
                "product_id": pid,
                "product_uom": uom_map[pid].uom_id,
                "product_uom_qty": float(it["qty_to_move"]),
                "location_id": src_id,
                "location_dest_id": dest_id,
            })

        connection_manager.call_method("stock.picking", [picking_id], "action_confirm")
        connection_manager.call_method("stock.picking", [picking_id], "action_assign")
        if validate:
            connection_manager.call_method("stock.picking", [picking_id], "button_validate")

    return created


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------

def _render_contact_selector() -> Tuple[InternalMoveContact | None, str | None]:
    contacts = _load_contacts()
    if not contacts:
        st.error(
            "Kontak tidak ditemukan. "
            "Tambahkan `[internal_moves].contacts` ke secrets.toml."
        )
        return None, None

    selected_label = st.selectbox(
        "Pilih Penanggung Jawab",
        options=[c.label for c in contacts],
        index=None,
    )
    if selected_label is None:
        return None, None

    selected = next((c for c in contacts if c.label == selected_label), None)
    return (selected, selected.label) if selected else (None, None)


def _resolve_display_location(default_name: str):
    location = _get_location(default_name)
    if location is not None:
        return location

    candidates = _list_locations(query="Display") or _list_locations(limit=200)
    if not candidates:
        st.error("Tidak ada lokasi stok internal yang ditemukan.")
        return None

    chosen_name = st.selectbox(
        "Lokasi sumber",
        options=[c.complete_name for c in candidates],
        index=0,
    )
    return next((c for c in candidates if c.complete_name == chosen_name), None)


def _validate_create_inputs(partner_id: int | None, selected_user) -> bool:
    errors = []
    if partner_id is None:
        errors.append("Kontak wajib diisi.")
    if selected_user is None:
        errors.append("Ditugaskan Ke (pengguna) wajib diisi.")
    if not st.session_state.get("internal_moves_confirm_create"):
        errors.append("Harap centang konfirmasi sebelum membuat transfer.")
    for e in errors:
        st.error(e)
    return len(errors) == 0


# ---------------------------------------------------------------------------
# Main page
# ---------------------------------------------------------------------------

def render_internal_moves_page() -> None:
    st.title("Alat Internal")

    # --- Kontak ---
    st.subheader("Kontak")
    contact, label = _render_contact_selector()

    partner_id: int | None = None
    if contact is not None:
        partner_id = contact.partner_id
        if partner_id is None:
            st.error(
                f"Kontak '{label}' tidak memiliki partner_id yang valid. "
                "Pastikan res.partner_id ada di file CSV."
            )
        else:
            st.success(f"Kontak dipilih: {label} (partner_id={partner_id})")

    # --- Pengguna ---
    st.subheader("Pengguna")
    users = _list_users()
    selected_user_name = st.selectbox(
        "User Odoo Yang Digunakan",
        options=[u.name for u in users],
        index=None,
    )
    selected_user = next((u for u in users if u.name == selected_user_name), None)

    # --- Lokasi & Load ---
    st.subheader("Muat Selisih Stok")
    display_location = _resolve_display_location(
        os.getenv("INTERNAL_MOVES_DISPLAY_LOCATION", "STR/Display")
    )
    if display_location is None:
        return

    col1, col2 = st.columns([1, 2])
    with col1:
        load_clicked = st.button("Muat Selisih Stok", type="primary", use_container_width=True)
    with col2:
        st.caption(f"Lokasi sumber: `{display_location.complete_name}` (id={display_location.id})")

    if load_clicked:
        if selected_user is None:
            st.warning("Pilih Ditugaskan Ke (pengguna) terlebih dahulu.")
            return

        with st.spinner("Memuat selisih stok..."):
            diffs = get_stock_quant_diffs_for_user_at_location(
                user_id=selected_user.id,
                location_id=display_location.id,
            )
        with st.spinner("Sedang mengkalkulasi rencana internal..."):
            planned_moves, group_counts = _build_planned_moves(diffs, display_location)

        st.session_state.internal_moves_planned = planned_moves
        st.session_state.internal_moves_group_counts = group_counts

    # --- Preview (dari session state, tidak re-compute) ---
    planned_moves: List[Dict[str, Any]] = st.session_state.get("internal_moves_planned", [])
    if not planned_moves:
        return

    group_counts = st.session_state.get("internal_moves_group_counts", {})

    st.markdown("#### Preview Internal")
    df_preview = pd.DataFrame(planned_moves)
    df_display = df_preview[[
        "barcode", "product_name", "direction", "qty_needed",
        "qty_to_move", "remainder", "src_location_name", "dest_location_name", "blocked", "block_reason"
    ]].rename(columns={
        "barcode": "Barcode",
        "product_name": "Produk",
        "direction": "Keterangan",
        "qty_needed": "Qty Dibutuhkan",
        "qty_to_move": "Qty Dipindahkan",
        "remainder": "Sisa",
        "src_location_name": "Lokasi Asal",
        "dest_location_name": "Lokasi Tujuan",
        "blocked": "Diblokir",
        "block_reason": "Alasan Blokir"
    })
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    st.markdown("#### Preview Pengelompokan")
    grouping_rows = [
        {"Lokasi Asal": k[0], "Lokasi Tujuan": k[1], "Jumlah Baris": v}
        for k, v in sorted(group_counts.items())
    ]
    df_group = pd.DataFrame(grouping_rows)
    st.dataframe(df_group, use_container_width=True, hide_index=True)

    # --- Blocked report (products with no internal location) ---
    blocked_moves = [m for m in planned_moves if m["blocked"]]
    if blocked_moves:
        st.markdown("#### Produk Tanpa Lokasi Internal")
        df_blocked = pd.DataFrame(blocked_moves)[[
            "barcode", "product_name", "direction", "qty_needed", "block_reason"
        ]].rename(columns={
            "barcode": "Barcode",
            "product_name": "Produk",
            "direction": "Keterangan",
            "qty_needed": "Qty Dibutuhkan",
            "block_reason": "Alasan Blokir",
        })
        st.dataframe(df_blocked, use_container_width=True, hide_index=True)

    # --- Konfirmasi & Buat ---
    st.markdown("#### Konfirmasi")
    st.checkbox(
        "Saya sudah memeriksa preview dan mau membuat internal transfer",
        key="internal_moves_confirm_create",
    )

    if not st.button("Internal Transfer", type="primary", use_container_width=True):
        return

    if not _validate_create_inputs(partner_id, selected_user):
        return

    groups = _group_clean_moves(planned_moves)
    if not groups:
        st.error("Tidak ada pergerakan bersih untuk dibuat.")
        return

    picking_type_id = _get_picking_type_id()
    if picking_type_id is None:
        st.error('Tipe pengambilan internal tidak ditemukan (stock.picking.type code="internal").')
        return

    product_ids = list({int(m["product_id"]) for items in groups.values() for m in items})
    uom_map = get_products_uom_ids(product_ids)
    missing_uoms = sorted({pid for pid in product_ids if pid not in uom_map})
    if missing_uoms:
        st.error(f"uom_id tidak ditemukan untuk produk: {missing_uoms}")
        return

    with st.spinner("Melakukan internal transfer di Odoo..."):
        try:
            created = _create_transfers(
                groups=groups,
                partner_id=partner_id,
                user_name=selected_user.name,
                picking_type_id=picking_type_id,
                uom_map=uom_map,
                validate=True,
            )
        except Exception as exc:
            st.error(f"Gagal membuat transfer internal: {exc}")
            return

    st.success(f"Berhasil membuat dan memvalidasi {len(created)} picking: {created}")
    if blocked_moves:
        st.warning(
            f"{len(blocked_moves)} produk tidak diproses karena tidak ada lokasi internal. "
            "Lihat tabel 'Produk Tanpa Lokasi Internal' di atas."
        )


__all__ = ["render_internal_moves_page"]