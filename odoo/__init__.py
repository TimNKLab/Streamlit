"""High-level interfaces for interacting with Odoo from Streamlit."""

from .connection import (
    OdooIntegrationError,
    OdooConnectionManager,
    connection_manager,
)

__all__ = [
    "OdooIntegrationError",
    "OdooConnectionManager",
    "connection_manager",
]
