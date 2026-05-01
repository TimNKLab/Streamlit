"""Test secrets parsing"""
import os
import streamlit as st

print("=== RAW ST.SECRETS ===")
print(f"st.secrets type: {type(st.secrets)}")
print(f"st.secrets items: {dict(st.secrets)}")

print("\n=== TESTING PARSING ===")
for section, values in st.secrets.items():
    print(f"\nSection: {section} (type: {type(values)})")
    if isinstance(values, dict):
        for key, value in values.items():
            env_key = f"{section.upper()}_{key.upper()}"
            print(f"  {key} = {value} (type: {type(value)}) -> {env_key}")

print("\n=== TESTING OS.ENVIRON ===")
print(f"ODOO_HOST: {os.getenv('ODOO_HOST', 'NOT SET')}")
print(f"ODOO_PORT: {os.getenv('ODOO_PORT', 'NOT SET')}")
print(f"ODOO_DATABASE: {os.getenv('ODOO_DATABASE', 'NOT SET')}")
print(f"ODOO_API_KEY: {os.getenv('ODOO_API_KEY', 'NOT SET')[:10]}...")

print("\n=== TESTING SETTINGS IMPORT ===")
try:
    from config.settings import get_odoo_settings
    settings = get_odoo_settings()
    print(f"Settings loaded OK!")
    print(f"  host: {settings.host}")
    print(f"  port: {settings.port}")
    print(f"  database: {settings.database}")
    print(f"  username: {settings.username}")
    print(f"  api_key: {settings.api_key[:10]}...")
except Exception as e:
    print(f"ERROR loading settings: {e}")
    import traceback
    traceback.print_exc()
