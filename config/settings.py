"""Centralized configuration management for Odoo connectivity."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

# Load environment variables from .env when available (no-op in production if absent)
load_dotenv()


@dataclass(frozen=True)
class OdooSettings:
    """Container for Odoo connection settings sourced from the environment."""

    protocol: str = os.getenv("ODOO_PROTOCOL", "jsonrpc")
    host: str = os.getenv("ODOO_HOST", "localhost")
    port: int = int(os.getenv("ODOO_PORT", 8069))
    database: str = os.getenv("ODOO_DATABASE", "odoo")
    username: str = os.getenv("ODOO_USERNAME", "admin")
    api_key: str = os.getenv("ODOO_API_KEY", "")
    version: str | None = os.getenv("ODOO_VERSION")
    pool_min_connections: int = int(os.getenv("ODOO_POOL_MIN_CONNECTIONS", 1))
    pool_max_connections: int = int(os.getenv("ODOO_POOL_MAX_CONNECTIONS", 5))
    pool_max_idle_time: int = int(os.getenv("ODOO_POOL_MAX_IDLE_TIME", 300))
    pool_max_lifetime: int = int(os.getenv("ODOO_POOL_MAX_LIFETIME", 3600))
    pool_health_check_interval: int = int(os.getenv("ODOO_POOL_HEALTH_CHECK_INTERVAL", 60))
    pool_connection_timeout: int = int(os.getenv("ODOO_POOL_CONNECTION_TIMEOUT", 30))


@lru_cache(maxsize=1)
def get_odoo_settings() -> OdooSettings:
    """Return cached settings instance to avoid repeated env parsing."""

    return OdooSettings()
