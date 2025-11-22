"""Main Streamlit application with separated UI and logic"""

import streamlit as st
from logic.auth import AuthManager
from ui.components.auth_components import AuthComponents
from ui.pages.dashboard import render_dashboard_page
from ui.pages.ba_sales_report import render_ba_sales_report_page
from ui.pages.stock_control import render_stock_control_page
from ui.pages.dsi_report import render_dsi_report_page

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
    
    # Create tabs for different pages
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "💰 BA Sales Report", "📦 Stock Control", "📋 DSI Report"])
    
    with tab1:
        render_dashboard_page()
    
    with tab2:
        render_ba_sales_report_page()
    
    with tab3:
        render_stock_control_page()
    
    with tab4:
        render_dsi_report_page()

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
