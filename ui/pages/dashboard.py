"""Dashboard page UI"""

import streamlit as st

def render_dashboard_page():
    """Render dashboard page content"""
    st.title("📊 Dashboard")
    st.markdown("### NK Dashboard v0.1.5")
    
    st.info("This page will display an overview of key business metrics and KPIs.")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Sales", "---", "---")
    
    with col2:
        st.metric("Active Users", "---", "---")
    
    with col3:
        st.metric("Inventory Value", "---", "---")
    
    with col4:
        st.metric("Orders", "---", "---")
    
    st.markdown("---")
    st.subheader("📈 Charts and Visualizations")
    st.text("Interactive charts and graphs will be displayed here.")
    
    st.markdown("---")
    st.subheader("📋 Recent Activity")
    st.text("Recent transactions and updates will be shown in this section.")
