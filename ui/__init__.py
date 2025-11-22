"""UI package for NK Streamlit application"""

from .components.auth_components import AuthComponents
from .pages.dashboard import render_dashboard_page
from .pages.ba_sales_report import render_ba_sales_report_page, BASalesReportPage
from .pages.stock_control import render_stock_control_page, StockControlPage
from .pages.dsi_report import render_dsi_report_page

__all__ = [
    'AuthComponents',
    'render_dashboard_page',
    'render_ba_sales_report_page',
    'render_stock_control_page',
    'render_dsi_report_page',
    'BASalesReportPage',
    'StockControlPage'
]
