"""UI pages package"""

from .dashboard import render_dashboard_page
from .ba_sales_report import render_ba_sales_report_page, BASalesReportPage
from .stock_control import render_stock_control_page, StockControlPage
from .dsi_report import render_dsi_report_page

__all__ = [
    'render_dashboard_page',
    'render_ba_sales_report_page',
    'render_stock_control_page',
    'render_dsi_report_page',
    'BASalesReportPage',
    'StockControlPage'
]
