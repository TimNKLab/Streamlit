"""Test Odoo connection with current credentials."""

import odoorpc

# Test with hardcoded values from previous successful connections
HOST = "newkhatulistiwa.odoo.com"
PORT = 443
PROTOCOL = "jsonrpc+ssl"
DATABASE = "REDACTED"
USERNAME = "robi@nk.com"
# Prompt for API key
API_KEY = input("Enter your Odoo API key: ").strip()

print(f"\nConnecting to {HOST}:{PORT} with protocol {PROTOCOL}...")
print(f"Database: {DATABASE}")
print(f"Username: {USERNAME}")

try:
    client = odoorpc.ODOO(HOST, protocol=PROTOCOL, port=PORT)
    print("ODOO client created successfully")
    
    uid = client.login(DATABASE, USERNAME, API_KEY)
    print(f"Login successful! User ID: {uid}")
    
    # Try a simple operation
    user = client.env.user
    print(f"Logged in as: {user.name}")
    
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
