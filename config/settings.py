"""Centralized configuration management for Odoo connectivity."""

from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

# Load environment variables from .env when available (no-op in production if absent)
load_dotenv()


def _get_env_or_secret(key: str, default: str = "") -> str:
    """Get value from session state (user login), then Streamlit secrets, then environment variables."""
    try:
        import streamlit as st
        
        # Check session state first (user-entered credentials at login)
        session_key_map = {
            "ODOO_DATABASE": "odoo_database",
            "ODOO_API_KEY": "odoo_api_key",
            "ODOO_USERNAME": "odoo_username",
        }
        session_key = session_key_map.get(key)
        if session_key and session_key in st.session_state:
            val = st.session_state[session_key]
            if val:
                print(f"[CONFIG] Loading {key} from session state (user login)")
                return val
        
        # Then check Streamlit secrets
        if key in st.secrets:
            print(f"[CONFIG] Loading {key} from Streamlit secrets")
            return st.secrets[key]
    except Exception as e:
        print(f"[CONFIG] Error checking session/secrets: {e}")
    
    env_val = os.getenv(key, default)
    if env_val and env_val != default:
        print(f"[CONFIG] Loading {key} from environment variable")
    return env_val


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


def get_odoo_settings() -> OdooSettings:
    """Return settings instance reading from session state, secrets, or env vars."""
    settings = OdooSettings()
    masked_key = '*' * len(settings.api_key) if settings.api_key else 'None'
    print(f"[CONFIG] Odoo Settings: host={settings.host}, db={settings.database}, user={settings.username}, api_key={masked_key}")
    return settings
