"""Tests for price tag session management."""

import pytest
import streamlit as st
from ui.pages.update_price import (
    _init_tag_session,
    _accumulate_tag_items,
    _clear_tag_session,
    _tag_session_count,
)


def test_session_init():
    """Test session state initializes price_tag_items as empty list."""
    if "price_tag_items" in st.session_state:
        del st.session_state.price_tag_items
    _init_tag_session()
    assert "price_tag_items" in st.session_state
    assert st.session_state.price_tag_items == []


def test_accumulate_appends():
    """Test that accumulate adds new items."""
    st.session_state.price_tag_items = []
    _accumulate_tag_items([
        {"barcode": "123", "name": "A", "het": 5000, "diskon": None},
        {"barcode": "456", "name": "B", "het": 10000, "diskon": None},
    ])
    assert len(st.session_state.price_tag_items) == 2


def test_accumulate_updates_existing():
    """Test same barcode updates het, no duplicate."""
    st.session_state.price_tag_items = [
        {"barcode": "123", "name": "A", "het": 5000, "diskon": None},
    ]
    _accumulate_tag_items([
        {"barcode": "123", "name": "A", "het": 6000, "diskon": None},
    ])
    assert len(st.session_state.price_tag_items) == 1
    assert st.session_state.price_tag_items[0]["het"] == 6000


def test_tag_session_count():
    """Test count returns correct number."""
    st.session_state.price_tag_items = [
        {"barcode": "123", "name": "A", "het": 5000, "diskon": None},
        {"barcode": "456", "name": "B", "het": 10000, "diskon": None},
    ]
    assert _tag_session_count() == 2


def test_clear_tag_session():
    """Test clear empties the list."""
    st.session_state.price_tag_items = [
        {"barcode": "123", "name": "A", "het": 5000, "diskon": None}
    ]
    _clear_tag_session()
    assert st.session_state.price_tag_items == []
