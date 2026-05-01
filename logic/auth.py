"""Authentication logic module — now uses Odoo credentials."""

import odoorpc

class AuthManager:
    """Handles authentication logic via Odoo connection."""
    
    def __init__(self, odoo_host="newkhatulistiwa.odoo.com", odoo_port=8069, protocol="jsonrpc", default_username="robi@nk.com"):
        self.odoo_host = odoo_host
        self.odoo_port = odoo_port
        self.protocol = protocol
        self.default_username = default_username
    
    def authenticate_odoo(self, database: str, api_key: str, username: str = None) -> tuple[bool, str]:
        """Try to authenticate with Odoo using database + API key.
        
        Uses default_username from settings if username not provided.
        
        Returns:
            (success: bool, message: str)
        """
        if not database or not api_key:
            return False, "Database dan API Key harus diisi"
        
        username = username or self.default_username
        
        try:
            # Build connection and test login
            print(f"[AUTH] Connecting to {self.odoo_host}:{self.odoo_port} ({self.protocol})...")
            print(f"[AUTH] DB={database}, User={username}")
            
            client = odoorpc.ODOO(
                self.odoo_host,
                protocol=self.protocol,
                port=self.odoo_port,
            )
            print("[AUTH] ODOO client created, attempting login...")
            
            uid = client.login(database, username, api_key)
            
            if uid:
                print(f"[AUTH] Login successful, uid={uid}")
                return True, f"Terhubung ke Odoo (User ID: {uid})"
            else:
                print("[AUTH] Login returned None - invalid credentials")
                return False, "Login gagal: API Key atau username tidak valid. Pastikan API Key aktif di Odoo (Settings > My Account > API Keys)"
                
        except Exception as e:
            import traceback
            tb_str = traceback.format_exc()
            print(f"[AUTH] Exception: {type(e).__name__}: {e}")
            print(tb_str)
            
            error_msg = str(e).lower()
            if "database" in error_msg and ("not found" in error_msg or "doesn't exist" in error_msg):
                return False, f"Database tidak ditemukan: {str(e)[:80]}"
            elif any(x in error_msg for x in ["credentials", "password", "login", "authentication", "access denied", "401", "403"]):
                return False, f"API Key atau username salah: {str(e)[:80]}"
            elif "connection" in error_msg or "timeout" in error_msg or "refused" in error_msg:
                return False, f"Tidak dapat terhubung: {str(e)[:80]}"
            else:
                # Return full error for debugging
                return False, f"{type(e).__name__}: {str(e)[:150]}"
    
    def verify_password(self, input_password):
        """Legacy - kept for compatibility."""
        return False  # No longer used
    
    def is_authenticated(self, session_state):
        """Check if user is authenticated based on session state"""
        return session_state.get('authenticated', False)
    
    def is_odoo_connected(self, session_state):
        """Check if user has active Odoo connection"""
        return session_state.get('odoo_connected', False)
    
    def get_odoo_credentials(self, session_state) -> dict:
        """Get stored Odoo credentials from session state"""
        return {
            'database': session_state.get('odoo_database', ''),
            'api_key': session_state.get('odoo_api_key', ''),
            'username': session_state.get('odoo_username', self.default_username),
            'host': self.odoo_host,
            'port': self.odoo_port,
            'protocol': self.protocol,
        }
    
    def set_authenticated(self, session_state, authenticated=True, odoo_connected=False, odoo_database=None, odoo_api_key=None, odoo_username=None):
        """Set authentication status in session state"""
        session_state['authenticated'] = authenticated
        session_state['odoo_connected'] = odoo_connected
        if odoo_database:
            session_state['odoo_database'] = odoo_database
        if odoo_api_key:
            session_state['odoo_api_key'] = odoo_api_key
        if odoo_username:
            session_state['odoo_username'] = odoo_username
    
    def logout(self, session_state):
        """Logout user by clearing all auth state"""
        session_state['authenticated'] = False
        session_state['odoo_connected'] = False
        session_state.pop('odoo_database', None)
        session_state.pop('odoo_api_key', None)
        session_state.pop('odoo_username', None)
