"""Simple test imports for the refactored application"""

try:
    print("Testing imports...")
    
    # Test logic imports
    from logic.auth import AuthManager
    from logic.sales_processor import SalesProcessor
    from logic.stock_processor import StockProcessor
    from logic.excel_utils import sanitize_filename
    print("Logic imports successful")
    
    # Test UI imports
    from ui.components.auth_components import AuthComponents
    from ui.pages.dashboard import render_dashboard_page
    from ui.pages.ba_sales_report import render_ba_sales_report_page
    from ui.pages.stock_control import render_stock_control_page
    from ui.pages.dsi_report import render_dsi_report_page
    print("UI imports successful")
    
    # Test basic functionality
    auth_manager = AuthManager()
    auth_components = AuthComponents(auth_manager)
    sales_processor = SalesProcessor()
    stock_processor = StockProcessor()
    
    print("Component initialization successful")
    
    # Test utility functions
    test_name = sanitize_filename("test<>file|name?.xlsx")
    print(f"Sanitize filename test: {test_name}")
    
    print("\nAll imports and basic functionality tests passed!")
    
except Exception as e:
    print(f"Error: {str(e)}")
    import traceback
    traceback.print_exc()
