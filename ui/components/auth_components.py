"""Authentication UI components"""

import streamlit as st
from logic.auth import AuthManager

class AuthComponents:
    """UI components for authentication"""
    
    def __init__(self, auth_manager=None):
        self.auth_manager = auth_manager or AuthManager()
    
    def render_login_page(self):
        """Render the login page with Odoo credentials."""
        st.title("🔐 Login Odoo")
        
        col1, col2, col3 = st.columns([1, 2, 1])
        
        with col2:
            st.markdown("### Masukkan kredensial Odoo")
            
            # User = Odoo database name
            database = st.text_input(
                "Database (User)", 
                key="database_input",
                placeholder="falinwasales-fwa-nk18-main-16841291"
            )
            
            # Optional: Odoo username (defaults to settings)
            username = st.text_input(
                "Username Odoo (opsional)", 
                key="username_input",
                placeholder="robi@nk.com",
                help="Kosongkan jika menggunakan default"
            )
            
            # Password = Odoo API key
            password = st.text_input(
                "Password (Odoo API Key)", 
                type="password", 
                key="password_input",
                placeholder="Masukkan API Key Odoo Anda"
            )
            
            # Allow demo access for basic features
            use_demo = st.checkbox("Mode Demo (tanpa Odoo)", value=False)
            
            if st.button("Login", type="primary", use_container_width=True):
                if use_demo:
                    # Demo mode - no Odoo access
                    self.auth_manager.set_authenticated(
                        st.session_state, 
                        True, 
                        odoo_connected=False
                    )
                    st.success("✅ Login Demo berhasil! (Tanpa akses Odoo)")
                    st.rerun()
                else:
                    # Try Odoo authentication
                    with st.spinner("Menghubungkan ke Odoo..."):
                        success, message = self.auth_manager.authenticate_odoo(
                            database=database,
                            api_key=password,
                            username=username if username else None
                        )
                    
                    if success:
                        self.auth_manager.set_authenticated(
                            st.session_state, 
                            True, 
                            odoo_connected=True,
                            odoo_database=database,
                            odoo_api_key=password,
                            odoo_username=username if username else None
                        )
                        st.success(f"✅ {message}")
                        st.rerun()
                    else:
                        st.error(f"❌ {message}")
    
    def render_logout_button(self):
        """Render logout button in sidebar"""
        if st.sidebar.button("🚪 Logout", use_container_width=True):
            self.auth_manager.logout(st.session_state)
            st.rerun()
    
    def check_authentication(self):
        """Check if user is authenticated"""
        return self.auth_manager.is_authenticated(st.session_state)
