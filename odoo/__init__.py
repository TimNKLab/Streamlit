"""High-level interfaces for interacting with Odoo from Streamlit."""

from .connection import (
    OdooIntegrationError,
    OdooConnectionManager,
    connection_manager,
)

def __getattr__(name):
    if name == "stock_services":
        from . import stock_services
        return stock_services
    raise AttributeError(f"module 'odoo' has no attribute {name!r}")

__all__ = [
    "OdooIntegrationError",
    "OdooConnectionManager",
    "connection_manager",
]