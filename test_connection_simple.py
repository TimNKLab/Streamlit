"""Simple Odoo connection test without Unicode emojis"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_odoo_settings
from odoo.connection import OdooConnectionManager, OdooIntegrationError

def main():
    print("Loading Odoo settings...")
    settings = get_odoo_settings()

    print(f"Host: {settings.host}")
    print(f"Database: {settings.database}")
    print(f"Username: {settings.username}")
    print(f"API Key: {settings.api_key[:20]}...")
    print(f"Protocol: {settings.protocol}")
    print(f"Port: {settings.port}")

    print("\nCreating connection manager...")
    manager = OdooConnectionManager(settings)

    print("Testing connection...")
    try:
        if manager.ping():
            print("[SUCCESS] Odoo connection successful!")

            # Try a simple query
            count = manager.search_count("sale.order")
            print(f"[SUCCESS] Found {count} sale orders in database")

            return 0
        else:
            print("[FAILED] Odoo ping failed")
            return 1

    except OdooIntegrationError as e:
        print(f"[ERROR] Connection failed: {e}")
        return 1
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
