"""UI pages package"""

from .dashboard import render_dashboard_page
from .ba_sales_report import render_ba_sales_report_page, BASalesReportPage
from .stock_control import render_stock_control_page, StockControlPage
from .dsi_report import render_dsi_report_page
from .stock_card import StockCardPage, render_stock_card_page
from .internal_moves import render_internal_moves_page

__all__ = [
    'render_dashboard_page',
    'render_ba_sales_report_page',
    'render_stock_control_page',
    'render_dsi_report_page',
    'render_stock_card_page',
    'render_internal_moves_page',
    'BASalesReportPage',
    'StockControlPage',
    'StockCardPage'
]
