# Handoff — Credentials Configuration Fix

> **Dibuat:** 2026-06-27
> **Branch:** main

## Ringkasan

Fix credentials loading dari environment variables. Root cause: format file mismatch antara TOML dan dotenv, plus struktur secrets.toml yang incompatible dengan app.py injection logic.

## Problem

Credentials sudah ada di `.env` dan `.streamlit/secrets.toml`, tapi **tidak ter-load** ke environment variables:
- `ODOO_HOST: None`
- `ODOO_API_KEY: None` 
- `ODOO_DATABASE: None`

**Root Cause:**
1. File `.env` menggunakan format TOML (`host = "..."`) padahal `load_dotenv()` expect format standard dotenv (`ODOO_HOST=...`)
2. File `.streamlit/secrets.toml` tidak punya `[odoo]` section, jadi `app.py` skip inject ke `os.environ`
3. Variable names tidak match: file punya `host`, `api_key` tapi `settings.py` cari `ODOO_HOST`, `ODOO_API_KEY`

## Solution

### 1. Fix `.env` Format (Local Development)

**Before:**
```toml
host = "newkhatulistiwa.odoo.com"
api_key = "d78f5cd7063b259c6d2c05fce02e14e695be9c07"
database = "falinwasales-fwa-nk18-main-16841291"
```

**After:**
```env
ODOO_HOST=newkhatulistiwa.odoo.com
ODOO_API_KEY=d78f5cd7063b259c6d2c05fce02e14e695be9c07
ODOO_DATABASE=falinwasales-fwa-nk18-main-16841291
ODOO_USERNAME=robi@nk.com
ODOO_PROTOCOL=jsonrpc+ssl
ODOO_PORT=443
```

✓ `load_dotenv()` sekarang bisa parse dengan benar
✓ Variable names match dengan `settings.py`

### 2. Fix `.streamlit/secrets.toml` Structure (Cloud Deployment)

**Before:**
```toml
host = "..."
api_key = "..."

[internal_moves]
contacts = [...]
```

**After:**
```toml
[odoo]
host = "..."
api_key = "..."
pool_min_connections = "2"
...

[internal_moves]
contacts = [...]
```

✓ `app.py` sekarang inject credentials sebagai `ODOO_HOST`, `ODOO_API_KEY`, dll

## Verification

```
[SUCCESS] Odoo connection successful!
[SUCCESS] Found 1251 sale orders in database
```

Test via `test_connection_simple.py` (created for testing tanpa Unicode emoji issues).

## File Changes

| File | Change | Why |
|------|--------|-----|
| `.env` | Format TOML → dotenv, tambah `ODOO_*` prefix | `load_dotenv()` expect format `KEY=value`, `settings.py` cari `ODOO_*` vars |
| `.streamlit/secrets.toml` | Tambah `[odoo]` section wrapper | `app.py` injection logic expect section structure untuk inject ke `os.environ` |
| `test_connection_simple.py` | Created | Test script tanpa Unicode emoji (bypass Windows console encoding issues) |

## How It Works

### Local Development (`.env` exists)
```
.env file
  ↓ load_dotenv()
  ↓ os.getenv("ODOO_HOST")
  ↓ settings.py → OdooSettings
  ↓ connection.py → OdooConnectionManager
  ↓ Connected ✓
```

### Streamlit Cloud (`.env` not exists)
```
.streamlit/secrets.toml
  ↓ st.secrets (TOML parser)
  ↓ app.py: for section="odoo", values=dict → inject to os.environ
  ↓ os.environ["ODOO_HOST"] = values["host"]
  ↓ settings.py → os.getenv("ODOO_HOST")
  ↓ connection.py → OdooConnectionManager
  ↓ Connected ✓
```

## Security

✓ Both `.env` dan `.streamlit/secrets.toml` sudah di `.gitignore`
✓ Credentials tidak ter-commit ke repository

## Next Steps

Fix dan improve Update Harga page.
