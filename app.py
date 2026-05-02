"""Main Streamlit application with separated UI and logic"""

import os
import streamlit as st

# Inject st.secrets into os.environ for cloud deployment
# Only if .env file doesn't exist (prioritize .env for local dev)
from pathlib import Path
env_path = Path(__file__).parent / ".env"

if not env_path.exists() and hasattr(st, 'secrets') and st.secrets:
    for section, values in st.secrets.items():
        if isinstance(values, dict):
            for key, value in values.items():
                env_key = f"{section.upper()}_{key.upper()}"
                os.environ[env_key] = str(value)

from logic.auth import AuthManager
from ui.components.auth_components import AuthComponents
from ui.pages.dashboard import render_dashboard_page
from ui.pages.ba_sales_report import render_ba_sales_report_page
from ui.pages.stock_control import render_stock_control_page
from ui.pages.dsi_report import render_dsi_report_page
from ui.pages.stock_card import render_stock_card_page
from ui.pages.price_tag_generator import render_price_tag_page
from ui.pages.price_sync import render_price_sync_page
from utils.persistence import save_active_tab, restore_active_tab, has_saved_barcodes

# Configure page
st.set_page_config(
    page_title="NK Lab",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize session state for authentication
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False

def main():
    """Main application with separated UI and logic"""
    # Initialize authentication components
    auth_manager = AuthManager()
    auth_components = AuthComponents(auth_manager)
    
    # Check authentication
    if not auth_components.check_authentication():
        auth_components.render_login_page()
        return
    
    # Render main application
    st.sidebar.title("Navigation")
    
    # Render logout button
    auth_components.render_logout_button()
    
    # Determine default tab: prioritize price_tag if has saved barcodes, else restore last tab
    if 'active_tab' not in st.session_state:
        if has_saved_barcodes():
            st.session_state.active_tab = "price_tag"
        else:
            st.session_state.active_tab = restore_active_tab()
    
    # Tab definitions
    tabs = {
        "dashboard": ("Dashboard", render_dashboard_page),
        "ba_sales": ("BA Sales Report", render_ba_sales_report_page),
        "stock_control": ("Stock Control", render_stock_control_page),
        "dsi_report": ("DSI Report", render_dsi_report_page),
        "stock_card": ("Stock Card", render_stock_card_page),
        "price_sync": ("Price Sync", render_price_sync_page),
        "price_tag": ("Price Tag", render_price_tag_page),
    }
    
    # Render tab buttons
    tab_cols = st.columns(len(tabs))
    for idx, (tab_key, (tab_label, _)) in enumerate(tabs.items()):
        with tab_cols[idx]:
            is_active = st.session_state.active_tab == tab_key
            btn_type = "primary" if is_active else "secondary"
            if st.button(tab_label, key=f"tab_{tab_key}", type=btn_type, use_container_width=True):
                st.session_state.active_tab = tab_key
                save_active_tab(tab_key)
                st.rerun()
    
    st.markdown("---")
    
    # Render active tab content
    _, render_func = tabs[st.session_state.active_tab]
    render_func()

if __name__ == "__main__":
    main()
    
    # Footer
    st.markdown(
        """
        <hr style="margin-top: 3em; margin-bottom: 0.5em;">
        <div style="text-align: center; color: gray; font-size: 0.95em;">
            Dibuat dengan ❤️, dari Tim Data NK.
        </div>
        """,
        unsafe_allow_html=True
    )
