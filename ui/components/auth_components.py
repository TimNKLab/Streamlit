"""Authentication UI components"""

import streamlit as st
from logic.auth import AuthManager

class AuthComponents:
    """UI components for authentication"""
    
    def __init__(self, auth_manager=None):
        self.auth_manager = auth_manager or AuthManager()
    
    def render_login_page(self):
        """Render the login page"""
        st.title("🔐 Authentication Required")
        
        col1, col2, col3 = st.columns([1, 2, 1])
        
        with col2:
            st.markdown("### Masukkan Password untuk melanjutkan")
            password = st.text_input("Password", type="password", key="password_input")
            
            if st.button("Login", type="primary", use_container_width=True):
                if self.auth_manager.verify_password(password):
                    self.auth_manager.set_authenticated(st.session_state, True)
                    st.rerun()
                else:
                    st.error("❌ Password salah. Silakan coba lagi.")
    
    def render_logout_button(self):
        """Render logout button in sidebar"""
        if st.sidebar.button("🚪 Logout", use_container_width=True):
            self.auth_manager.logout(st.session_state)
            st.rerun()
    
    def check_authentication(self):
        """Check if user is authenticated"""
        return self.auth_manager.is_authenticated(st.session_state)
