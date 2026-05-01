"""Centralized configuration management for Odoo connectivity."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

# Load environment variables from .env when available (no-op in production if absent)
load_dotenv()


def _get_env_or_secret(key: str, default: str = "") -> str:
    """Get value from Streamlit secrets first, then environment variables."""
    try:
        import streamlit as st
        if key in st.secrets:
            return st.secrets[key]
    except:
        pass  # Streamlit not available or no secrets
    return os.getenv(key, default)


@dataclass(frozen=True)
class OdooSettings:
    """Container for Odoo connection settings sourced from Streamlit secrets or environment variables."""

    protocol: str = _get_env_or_secret("ODOO_PROTOCOL", "jsonrpc")
    host: str = _get_env_or_secret("ODOO_HOST", "localhost")
    port: int = int(_get_env_or_secret("ODOO_PORT", "8069"))
    database: str = _get_env_or_secret("ODOO_DATABASE", "odoo")
    username: str = _get_env_or_secret("ODOO_USERNAME", "admin")
    api_key: str = _get_env_or_secret("ODOO_API_KEY", "")
    version: str | None = _get_env_or_secret("ODOO_VERSION")
    pool_min_connections: int = int(_get_env_or_secret("ODOO_POOL_MIN_CONNECTIONS", "1"))
    pool_max_connections: int = int(_get_env_or_secret("ODOO_POOL_MAX_CONNECTIONS", "5"))
    pool_max_idle_time: int = int(_get_env_or_secret("ODOO_POOL_MAX_IDLE_TIME", "300"))
    pool_max_lifetime: int = int(_get_env_or_secret("ODOO_POOL_MAX_LIFETIME", "3600"))
    pool_health_check_interval: int = int(_get_env_or_secret("ODOO_POOL_HEALTH_CHECK_INTERVAL", "60"))
    pool_connection_timeout: int = int(_get_env_or_secret("ODOO_POOL_CONNECTION_TIMEOUT", "30"))


@lru_cache(maxsize=1)
def get_odoo_settings() -> OdooSettings:
    """Return cached settings instance to avoid repeated env parsing."""

    return OdooSettings()
