import streamlit as st
import pandas as pd
from openpyxl import Workbook
from openpyxl.utils.dataframe import dataframe_to_rows
import io
import zipfile
from datetime import datetime
import re

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

# Simple password authentication
PASSWORD = "admin123"  # Change this to your desired password

def login():
    """Display login page"""
    st.title("🔐 Authentication Required")
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("### Masukkan Password untuk melanjutkan")
        password = st.text_input("Password", type="password", key="password_input")
        
        if st.button("Login", type="primary", use_container_width=True):
            if password == PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ Password salah. Silakan coba lagi.")

def dashboard_page():
    """Dashboard page content"""
    st.title("📊 Dashboard")
    st.markdown("### NK Dashboard v0.1.3")
    
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

def sanitize_filename(name):
    """Sanitize filename by removing invalid characters"""
    # Remove invalid characters for Windows/Linux filenames
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', str(name))
    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip(' .')
    return sanitized if sanitized else 'Unknown'

def sort_sales_data(df):
    """Sort data by Parent Brand (alphabetically) then Order Date (earliest date, then earliest hour)"""
    df = df.copy()
    
    # Ensure Order Date is datetime
    if not pd.api.types.is_datetime64_any_dtype(df['Order Date']):
        df['Order Date'] = pd.to_datetime(df['Order Date'], errors='coerce')
    
    # Create sorting key: use Parent Brand if not None, otherwise use Brand
    df['sort_key_parent_brand'] = df['Parent Brand'].fillna(df['Brand'])
    
    # Extract date and hour for explicit sorting
    df['sort_date'] = df['Order Date'].dt.date  # Date only
    df['sort_hour'] = df['Order Date'].dt.hour  # Hour only
    
    # Sort by Parent Brand (alphabetically), then by date (earliest first), then by hour (earliest first)
    df_sorted = df.sort_values(
        by=['sort_key_parent_brand', 'sort_date', 'sort_hour', 'Order Date'],
        ascending=[True, True, True, True],
        na_position='last'
    )
    
    # Drop the temporary sorting columns
    df_sorted = df_sorted.drop(columns=['sort_key_parent_brand', 'sort_date', 'sort_hour'])
    
    return df_sorted.reset_index(drop=True)

def group_by_parent_brand(df):
    """Group data by Parent Brand (use Brand if Parent Brand is None).
    For Paragon and Hebe, also split by Brand."""
    groups = {}
    
    # Parent brands that should be split by Brand
    split_by_brand_parents = ['Paragon', 'Hebe']
    
    for idx, row in df.iterrows():
        # Use Parent Brand if available, otherwise use Brand
        parent_brand = row['Parent Brand'] if pd.notna(row['Parent Brand']) else row['Brand']
        brand = row['Brand'] if pd.notna(row['Brand']) else 'Unknown'
        
        # For Paragon and Hebe, create group key with both Parent Brand and Brand
        if parent_brand in split_by_brand_parents:
            group_key = f"{parent_brand}_{brand}"
        else:
            # For other parent brands, use just the parent brand name
            group_key = parent_brand
        
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(idx)
    
    # Convert to DataFrames
    grouped_dfs = {}
    for key, indices in groups.items():
        grouped_dfs[key] = df.loc[indices].reset_index(drop=True)
    
    return grouped_dfs

def create_pivot_by_barcode(df_group):
    """Create pivot table with barcode as index, dates as columns, showing Quantity and Tax Incl."""
    df = df_group.copy()
    
    # Ensure Product/Barcode is string
    df['Product/Barcode'] = df['Product/Barcode'].astype(str)
    
    # Ensure Order Date is datetime
    if not pd.api.types.is_datetime64_any_dtype(df['Order Date']):
        df['Order Date'] = pd.to_datetime(df['Order Date'])
    
    # Extract date (without time) for grouping - normalize to date only
    df['Order Date Day'] = pd.to_datetime(df['Order Date']).dt.normalize()
    
    # Create separate pivot tables for Quantity and Tax Incl., then merge
    pivot_qty = pd.pivot_table(
        df,
        index=['Product/Barcode', 'Product'],
        columns='Order Date Day',
        values='Quantity',
        aggfunc='sum',
        fill_value=0
    )
    
    pivot_revenue = pd.pivot_table(
        df,
        index=['Product/Barcode', 'Product'],
        columns='Order Date Day',
        values='Tax Incl.',
        aggfunc='sum',
        fill_value=0
    )
    
    # Rename columns to distinguish Quantity and Revenue
    def format_col_name(prefix, col_val):
        if pd.notna(col_val) and isinstance(col_val, pd.Timestamp):
            return f"{prefix}_{col_val.strftime('%Y-%m-%d')}"
        else:
            return f"{prefix}_{str(col_val)}"
    
    pivot_qty.columns = [format_col_name("Quantity", col) for col in pivot_qty.columns]
    pivot_revenue.columns = [format_col_name("Tax_Incl", col) for col in pivot_revenue.columns]
    
    # Merge the two pivot tables
    pivot = pd.merge(
        pivot_qty.reset_index(),
        pivot_revenue.reset_index(),
        on=['Product/Barcode', 'Product'],
        how='outer'
    )
    
    # Sort columns: Product/Barcode, Product, then Quantity columns, then Tax Incl. columns
    base_cols = ['Product/Barcode', 'Product']
    qty_cols = [col for col in pivot.columns if col.startswith('Quantity_')]
    revenue_cols = [col for col in pivot.columns if col.startswith('Tax_Incl_')]
    
    # Sort date columns by date
    def extract_date(col_name):
        try:
            date_str = col_name.split('_', 1)[1]
            return pd.to_datetime(date_str)
        except:
            return pd.Timestamp.min
    
    qty_cols_sorted = sorted(qty_cols, key=extract_date)
    revenue_cols_sorted = sorted(revenue_cols, key=extract_date)
    
    pivot = pivot[base_cols + qty_cols_sorted + revenue_cols_sorted]
    
    return pivot

def create_pivot_by_brand(df_group):
    """Create pivot table organized by Brand with column groups for each Brand.
    Structure: Product/Barcode | Product | Brand1_Quantity_Date1 | Brand1_Tax_Incl_Date1 | ... | Brand2_Quantity_Date1 | ..."""
    df = df_group.copy()
    
    # Ensure Product/Barcode is string
    df['Product/Barcode'] = df['Product/Barcode'].astype(str)
    
    # Ensure Order Date is datetime
    if not pd.api.types.is_datetime64_any_dtype(df['Order Date']):
        df['Order Date'] = pd.to_datetime(df['Order Date'])
    
    # Extract date (without time) for grouping
    df['Order Date Day'] = pd.to_datetime(df['Order Date']).dt.normalize()
    
    # Get unique brands and sort them
    brands = sorted(df['Brand'].dropna().unique())
    
    # Create pivot tables for each brand
    brand_pivots = []
    
    for brand in brands:
        brand_df = df[df['Brand'] == brand].copy()
        
        # Create pivot tables for Quantity and Tax Incl. for this brand
        pivot_qty = pd.pivot_table(
            brand_df,
            index=['Product/Barcode', 'Product'],
            columns='Order Date Day',
            values='Quantity',
            aggfunc='sum',
            fill_value=0
        )
        
        pivot_revenue = pd.pivot_table(
            brand_df,
            index=['Product/Barcode', 'Product'],
            columns='Order Date Day',
            values='Tax Incl.',
            aggfunc='sum',
            fill_value=0
        )
        
        # Rename columns with brand prefix
        def format_col_name(prefix, brand_name, col_val):
            if pd.notna(col_val) and isinstance(col_val, pd.Timestamp):
                return f"{brand_name}_{prefix}_{col_val.strftime('%Y-%m-%d')}"
            else:
                return f"{brand_name}_{prefix}_{str(col_val)}"
        
        pivot_qty.columns = [format_col_name("Quantity", brand, col) for col in pivot_qty.columns]
        pivot_revenue.columns = [format_col_name("Tax_Incl", brand, col) for col in pivot_revenue.columns]
        
        # Merge Quantity and Tax_Incl for this brand
        brand_pivot = pd.merge(
            pivot_qty.reset_index(),
            pivot_revenue.reset_index(),
            on=['Product/Barcode', 'Product'],
            how='outer'
        )
        
        brand_pivots.append((brand, brand_pivot))
    
    # Merge all brand pivots
    if not brand_pivots:
        # If no brands, return empty pivot with base columns
        return pd.DataFrame(columns=['Product/Barcode', 'Product'])
    
    # Start with first brand
    final_pivot = brand_pivots[0][1]
    
    # Merge remaining brands
    for brand, brand_pivot in brand_pivots[1:]:
        final_pivot = pd.merge(
            final_pivot,
            brand_pivot,
            on=['Product/Barcode', 'Product'],
            how='outer',
            suffixes=('', f'_{brand}')
        )
    
    # Organize columns: base columns first, then brand columns grouped together
    base_cols = ['Product/Barcode', 'Product']
    brand_col_groups = {}
    
    for brand in brands:
        brand_qty_cols = [col for col in final_pivot.columns if col.startswith(f"{brand}_Quantity_")]
        brand_revenue_cols = [col for col in final_pivot.columns if col.startswith(f"{brand}_Tax_Incl_")]
        
        # Sort date columns by date
        def extract_date(col_name):
            try:
                # Extract date from column name like "Brand_Quantity_2025-11-03"
                date_str = col_name.split('_', 2)[2]  # Get date part after Brand_Quantity_
                return pd.to_datetime(date_str)
            except:
                return pd.Timestamp.min
        
        brand_qty_cols_sorted = sorted(brand_qty_cols, key=extract_date)
        brand_revenue_cols_sorted = sorted(brand_revenue_cols, key=extract_date)
        
        # For each date, put Quantity then Tax_Incl
        brand_cols = []
        dates = set()
        for col in brand_qty_cols_sorted:
            date_str = col.split('_', 2)[2]
            dates.add(date_str)
        
        for date_str in sorted(dates):
            qty_col = f"{brand}_Quantity_{date_str}"
            revenue_col = f"{brand}_Tax_Incl_{date_str}"
            if qty_col in final_pivot.columns:
                brand_cols.append(qty_col)
            if revenue_col in final_pivot.columns:
                brand_cols.append(revenue_col)
        
        brand_col_groups[brand] = brand_cols
    
    # Combine all columns in order
    all_cols = base_cols.copy()
    for brand in brands:
        if brand in brand_col_groups:
            all_cols.extend(brand_col_groups[brand])
    
    # Reorder columns
    final_pivot = final_pivot[[col for col in all_cols if col in final_pivot.columns]]
    
    return final_pivot

def create_detailed_report(df_group):
    """Create detailed report with all original columns, formatting Order Date as long date with hour"""
    df = df_group.copy()
    
    # Format Order Date as long date (date, hour)
    # Format: "YYYY-MM-DD, HH:MM" or similar readable format
    if 'Order Date' in df.columns and pd.api.types.is_datetime64_any_dtype(df['Order Date']):
        df['Order Date'] = df['Order Date'].dt.strftime('%Y-%m-%d, %H:%M')
    
    # Ensure Product/Barcode is string to prevent Excel from converting to number
    if 'Product/Barcode' in df.columns:
        df['Product/Barcode'] = df['Product/Barcode'].astype(str)
    
    return df

def create_workbook_for_parent_brand(pivot_df, detailed_df, parent_brand_name, date_str=None, is_brand_organized=False, df_group=None, organize_by_brand=False, separate_by_date=False):
    """Create Excel workbook with 2 sheets: Pivoted and Detailed Report
    
    Args:
        pivot_df: Pivot table DataFrame (None if separate_by_date=True)
        detailed_df: Detailed report DataFrame (None if separate_by_date=True)
        parent_brand_name: Name of the parent brand
        date_str: Date string for filename
        is_brand_organized: Whether pivot is organized by brand
        df_group: Original data group (for brand identification)
        organize_by_brand: If True, organize pivot data by brand sections (for non-Paragon/Hebe)
        separate_by_date: If True, create separate sheets for each date
    """
    wb = Workbook()
    wb.remove(wb.active)  # Remove default sheet
    
    if separate_by_date and df_group is not None:
        # Create separate sheets for each date
        # Extract unique dates from the data
        df_group['Order Date Day'] = pd.to_datetime(df_group['Order Date']).dt.normalize()
        unique_dates = sorted(df_group['Order Date Day'].unique())
        
        # Extract actual parent brand name (remove brand suffix if present)
        actual_parent_brand = parent_brand_name.split('_')[0] if '_' in parent_brand_name else parent_brand_name
        is_non_paragon_hebe = (actual_parent_brand not in ['Paragon', 'Hebe'])
        
        # For each date, create pivot and detailed report sheets
        for date_val in unique_dates:
            # Filter data for this date only
            date_df = df_group[df_group['Order Date Day'] == date_val].copy()
            
            if not date_df.empty:
                # Create pivot table for this date
                date_pivot_df = create_pivot_by_barcode(date_df)
                
                # Create detailed report for this date
                date_detailed_df = create_detailed_report(date_df)
                
                # Format date for sheet name
                date_str_sheet = pd.to_datetime(date_val).strftime('%Y-%m-%d')
                
                # Create Pivoted sheet for this date
                ws_pivot = wb.create_sheet(f"Pivoted_{date_str_sheet}")
                
                # Apply brand organization logic
                if organize_by_brand and is_non_paragon_hebe and 'Brand' in date_df.columns:
                    # Organize by brand sections for this date
                    brands = sorted(date_df['Brand'].dropna().unique())
                    
                    # Write header once at the top
                    header_row_data = {}
                    for col in date_pivot_df.columns:
                        header_row_data[col] = col
                    ws_pivot.append([header_row_data.get(col, "") for col in date_pivot_df.columns])
                    
                    current_row = 2  # Start after header
                    
                    # For each brand, create a section
                    for brand in brands:
                        # Filter products for this brand
                        brand_products = date_df[date_df['Brand'] == brand]
                        
                        if not brand_products.empty:
                            # Get product barcodes for this brand
                            brand_barcodes = set(brand_products['Product/Barcode'].astype(str))
                            
                            # Filter pivot_df to only include products of this brand
                            brand_pivot = date_pivot_df[date_pivot_df['Product/Barcode'].astype(str).isin(brand_barcodes)]
                            
                            # Calculate total sellout (Tax_Incl) for this brand
                            tax_incl_cols = [col for col in date_pivot_df.columns if col.startswith('Tax_Incl_')]
                            brand_total_sellout = brand_pivot[tax_incl_cols].sum().sum() if not brand_pivot.empty and tax_incl_cols else 0
                            
                            # Create brand total sellout row
                            brand_total_row_data = {}
                            for col in date_pivot_df.columns:
                                if col in ['Product/Barcode', 'Product']:
                                    brand_total_row_data[col] = f"{brand} Total Sellout" if col == 'Product/Barcode' else ""
                                elif col.startswith('Tax_Incl_'):
                                    # Show total sellout for this brand in all Tax_Incl columns
                                    brand_total_row_data[col] = brand_total_sellout
                                elif col.startswith('Quantity_'):
                                    # Leave quantity columns empty for brand totals
                                    brand_total_row_data[col] = ""
                                else:
                                    brand_total_row_data[col] = ""
                            
                            # Write brand total sellout row
                            ws_pivot.append([brand_total_row_data.get(col, "") for col in date_pivot_df.columns])
                            current_row += 1
                            
                            # Write all product rows for this brand
                            if not brand_pivot.empty:
                                for _, row in brand_pivot.iterrows():
                                    row_data = []
                                    for col in date_pivot_df.columns:
                                        row_data.append(row.get(col, ""))
                                    ws_pivot.append(row_data)
                                    current_row += 1
                else:
                    # Standard format: Write pivot data first
                    for r in dataframe_to_rows(date_pivot_df, index=False, header=True):
                        ws_pivot.append(r)
                    
                    # Add Total Sellout row for standard format
                    total_row_data = {}
                    for col in date_pivot_df.columns:
                        if col in ['Product/Barcode', 'Product']:
                            total_row_data[col] = "Total Sellout" if col == 'Product/Barcode' else ""
                        elif col.startswith('Tax_Incl_'):
                            total_row_data[col] = date_pivot_df[col].sum()
                        elif col.startswith('Quantity_'):
                            total_row_data[col] = date_pivot_df[col].sum()
                        else:
                            total_row_data[col] = ""
                    
                    total_row_df = pd.DataFrame([total_row_data])
                    total_row_df = total_row_df.reindex(columns=date_pivot_df.columns, fill_value="")
                    
                    # Insert total row at row 2 (after header)
                    ws_pivot.insert_rows(2)
                    for col_idx, col_name in enumerate(date_pivot_df.columns, 1):
                        cell = ws_pivot.cell(row=2, column=col_idx)
                        value = total_row_df.iloc[0][col_name]
                        cell.value = value
                
                # Format barcode column as text
                header_row = list(ws_pivot.iter_rows(min_row=1, max_row=1))[0]
                barcode_col_idx_pivot = None
                for idx, cell in enumerate(header_row):
                    if cell.value == 'Product/Barcode':
                        barcode_col_idx_pivot = idx
                        break
                
                if barcode_col_idx_pivot is not None:
                    # Determine start row based on organization
                    if organize_by_brand and is_non_paragon_hebe:
                        start_data_row = 2  # After header
                    else:
                        start_data_row = 3  # After header and total row
                    
                    for row in ws_pivot.iter_rows(min_row=start_data_row):
                        cell = row[barcode_col_idx_pivot]
                        if cell.value is not None:
                            cell.value = str(cell.value)
                            cell.number_format = '@'  # Text format
                
                # Create Detailed Report sheet for this date
                ws_detailed = wb.create_sheet(f"Detailed Report_{date_str_sheet}")
                for r in dataframe_to_rows(date_detailed_df, index=False, header=True):
                    ws_detailed.append(r)
                
                # Format Product/Barcode column as text in detailed report
                header_row = list(ws_detailed.iter_rows(min_row=1, max_row=1))[0]
                barcode_col_idx = None
                for idx, cell in enumerate(header_row, 1):
                    if cell.value == 'Product/Barcode':
                        barcode_col_idx = idx
                        break
                
                if barcode_col_idx:
                    for row in ws_detailed.iter_rows(min_row=2):  # Skip header
                        cell = row[barcode_col_idx - 1]  # Convert to 0-based index
                        if cell.value is not None:
                            cell.value = str(cell.value)
                            cell.number_format = '@'  # Text format

        # In separate-by-date mode we have created all sheets; return workbook now
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)
        return output
    else:
        # Original logic: Single pivot and detailed report sheets
        # Sheet 1: Pivoted
        ws_pivot = wb.create_sheet("Pivoted")
        
        # Detect if pivot is brand-organized by checking column names
        if not is_brand_organized:
            # Check if columns have brand prefixes (format: BrandName_Quantity_Date or BrandName_Tax_Incl_Date)
            has_brand_prefixes = any('_' in col and col not in ['Product/Barcode', 'Product'] and 
                                     not col.startswith('Quantity_') and not col.startswith('Tax_Incl_') 
                                     for col in pivot_df.columns)
            is_brand_organized = has_brand_prefixes
        
        if organize_by_brand and df_group is not None and 'Brand' in df_group.columns:
            # Organize by brand sections: each brand gets its own section with total sellout row followed by product rows
            brands = sorted(df_group['Brand'].dropna().unique())
            
            # Write header once at the top
            header_row_data = {}
            for col in pivot_df.columns:
                header_row_data[col] = col
            ws_pivot.append([header_row_data.get(col, "") for col in pivot_df.columns])
            
            current_row = 2  # Start after header
            
            # For each brand, create a section
            for brand in brands:
                # Filter products for this brand
                brand_products = df_group[df_group['Brand'] == brand]
                
                if not brand_products.empty:
                    # Get product barcodes for this brand
                    brand_barcodes = set(brand_products['Product/Barcode'].astype(str))
                    
                    # Filter pivot_df to only include products of this brand
                    brand_pivot = pivot_df[pivot_df['Product/Barcode'].astype(str).isin(brand_barcodes)]
                    
                    # Calculate total sellout (Tax_Incl) for this brand
                    tax_incl_cols = [col for col in pivot_df.columns if col.startswith('Tax_Incl_')]
                    brand_total_sellout = brand_pivot[tax_incl_cols].sum().sum() if not brand_pivot.empty and tax_incl_cols else 0
                    
                    # Create brand total sellout row
                    brand_total_row_data = {}
                    for col in pivot_df.columns:
                        if col in ['Product/Barcode', 'Product']:
                            brand_total_row_data[col] = f"{brand} Total Sellout" if col == 'Product/Barcode' else ""
                        elif col.startswith('Tax_Incl_'):
                            # Show total sellout for this brand in all Tax_Incl columns
                            brand_total_row_data[col] = brand_total_sellout
                        elif col.startswith('Quantity_'):
                            # Leave quantity columns empty for brand totals
                            brand_total_row_data[col] = ""
                        else:
                            brand_total_row_data[col] = ""
                    
                    # Write brand total sellout row
                    ws_pivot.append([brand_total_row_data.get(col, "") for col in pivot_df.columns])
                    current_row += 1
                    
                    # Write all product rows for this brand
                    if not brand_pivot.empty:
                        for _, row in brand_pivot.iterrows():
                            row_data = []
                            for col in pivot_df.columns:
                                row_data.append(row.get(col, ""))
                            ws_pivot.append(row_data)
                            current_row += 1
        else:
            # Original logic: Write pivot data first
            for r in dataframe_to_rows(pivot_df, index=False, header=True):
                ws_pivot.append(r)
        
        # Only add additional totals if not organizing by brand sections
        if not organize_by_brand and is_brand_organized:
            # For brand-organized pivots: Add brand totals at top of each brand's column group
            # First, identify all brands from column names
            brands = set()
            for col in pivot_df.columns:
                if col not in ['Product/Barcode', 'Product'] and '_' in col:
                    # Extract brand name (first part before _Quantity_ or _Tax_Incl_)
                    parts = col.split('_')
                    if len(parts) >= 2 and parts[1] in ['Quantity', 'Tax_Incl']:
                        brands.add(parts[0])
            
            brands = sorted(brands)
            
            # Calculate totals for each brand
            brand_totals = {}
            for brand in brands:
                brand_qty_cols = [col for col in pivot_df.columns if col.startswith(f"{brand}_Quantity_")]
                brand_revenue_cols = [col for col in pivot_df.columns if col.startswith(f"{brand}_Tax_Incl_")]
                
                total_qty = pivot_df[brand_qty_cols].sum().sum() if brand_qty_cols else 0
                total_revenue = pivot_df[brand_revenue_cols].sum().sum() if brand_revenue_cols else 0
                
                brand_totals[brand] = {
                    'total_quantity': total_qty,
                    'total_sold': total_revenue
                }
            
            # Create total rows for each brand
            # Find the start column index for each brand's column group
            header_row = list(ws_pivot.iter_rows(min_row=1, max_row=1))[0]
            brand_col_ranges = {}
            
            for brand in brands:
                start_col = None
                end_col = None
                for idx, cell in enumerate(header_row):
                    col_name = str(cell.value) if cell.value else ''
                    if col_name.startswith(f"{brand}_"):
                        if start_col is None:
                            start_col = idx + 1  # 1-based column index
                        end_col = idx + 1
                if start_col is not None:
                    brand_col_ranges[brand] = (start_col, end_col)
            
            # Insert brand total rows after header, before product rows
            # Row 2 will be the first brand total row
            current_row = 2
            
            for brand in brands:
                # Create total row for this brand - ONE row showing totals
                # Calculate totals for this brand: sum across all products and all dates
                brand_qty_cols = [c for c in pivot_df.columns if c.startswith(f"{brand}_Quantity_")]
                brand_rev_cols = [c for c in pivot_df.columns if c.startswith(f"{brand}_Tax_Incl_")]
                
                total_qty_brand = pivot_df[brand_qty_cols].sum().sum() if brand_qty_cols else 0
                total_rev_brand = pivot_df[brand_rev_cols].sum().sum() if brand_rev_cols else 0
                
                # Find the first Quantity and first Tax_Incl column for this brand to show totals
                first_qty_col = brand_qty_cols[0] if brand_qty_cols else None
                first_rev_col = brand_rev_cols[0] if brand_rev_cols else None
                
                total_row_data = {}
                for col in pivot_df.columns:
                    if col in ['Product/Barcode', 'Product']:
                        total_row_data[col] = f"{brand} Total" if col == 'Product/Barcode' else ""
                    elif col.startswith(f"{brand}_"):
                        # Only show totals in the first column of each type (Quantity and Tax_Incl)
                        if col == first_qty_col:
                            # Show total quantity only in first quantity column
                            total_row_data[col] = total_qty_brand
                        elif col == first_rev_col:
                            # Show total sold only in first tax incl column
                            total_row_data[col] = total_rev_brand
                        else:
                            # Leave other columns empty
                            total_row_data[col] = ""
                    else:
                        total_row_data[col] = ""
                
                # Insert row and write data
                ws_pivot.insert_rows(current_row)
                for col_idx, col_name in enumerate(pivot_df.columns, 1):
                    cell = ws_pivot.cell(row=current_row, column=col_idx)
                    value = total_row_data.get(col_name, "")
                    cell.value = value
                
                current_row += 1
            
            # Now add the overall Total Sellout row
            total_sellout_row_data = {}
            for col in pivot_df.columns:
                if col in ['Product/Barcode', 'Product']:
                    total_sellout_row_data[col] = "Total Sellout" if col == 'Product/Barcode' else ""
                elif col.startswith('Tax_Incl_') or '_Tax_Incl_' in col:
                    # Sum all Tax_Incl columns
                    total_sellout_row_data[col] = pivot_df[col].sum() if col in pivot_df.columns else 0
                elif col.startswith('Quantity_') or '_Quantity_' in col:
                    # Sum all Quantity columns
                    total_sellout_row_data[col] = pivot_df[col].sum() if col in pivot_df.columns else 0
                else:
                    total_sellout_row_data[col] = ""
            
            # Insert Total Sellout row at current_row (after brand totals)
            ws_pivot.insert_rows(current_row)
            for col_idx, col_name in enumerate(pivot_df.columns, 1):
                cell = ws_pivot.cell(row=current_row, column=col_idx)
                value = total_sellout_row_data.get(col_name, "")
                cell.value = value
    
    # Only add additional totals if not organizing by brand sections
    if not organize_by_brand and not is_brand_organized:
        # Original logic for non-brand-organized pivots (when not organizing by brand sections)
        # Add brand total sellout rows before overall Total Sellout
        
        current_row = 2  # Start after header row
        
        # Get unique brands from original data if available
        if df_group is not None and 'Brand' in df_group.columns:
            brands = sorted(df_group['Brand'].dropna().unique())
            
            # Create a row for each brand's total sellout
            for brand in brands:
                # Filter products for this brand
                brand_products = df_group[df_group['Brand'] == brand]
                
                if not brand_products.empty:
                    # Get product barcodes for this brand
                    brand_barcodes = set(brand_products['Product/Barcode'].astype(str))
                    
                    # Filter pivot_df to only include products of this brand
                    brand_pivot = pivot_df[pivot_df['Product/Barcode'].astype(str).isin(brand_barcodes)]
                    
                    # Calculate total sellout (Tax_Incl) for this brand
                    tax_incl_cols = [col for col in pivot_df.columns if col.startswith('Tax_Incl_')]
                    brand_total_sellout = brand_pivot[tax_incl_cols].sum().sum() if not brand_pivot.empty and tax_incl_cols else 0
                    
                    # Create brand total sellout row
                    brand_total_row_data = {}
                    for col in pivot_df.columns:
                        if col in ['Product/Barcode', 'Product']:
                            brand_total_row_data[col] = f"{brand} Total Sellout" if col == 'Product/Barcode' else ""
                        elif col.startswith('Tax_Incl_'):
                            # Show total sellout for this brand in all Tax_Incl columns
                            brand_total_row_data[col] = brand_total_sellout
                        elif col.startswith('Quantity_'):
                            # Leave quantity columns empty for brand totals
                            brand_total_row_data[col] = ""
                        else:
                            brand_total_row_data[col] = ""
                    
                    # Insert brand total sellout row
                    ws_pivot.insert_rows(current_row)
                    for col_idx, col_name in enumerate(pivot_df.columns, 1):
                        cell = ws_pivot.cell(row=current_row, column=col_idx)
                        value = brand_total_row_data.get(col_name, "")
                        cell.value = value
                    
                    current_row += 1
        
        # Calculate overall Total Sellout row
        total_row_data = {}
        
        # Base columns
        for col in ['Product/Barcode', 'Product']:
            if col in pivot_df.columns:
                total_row_data[col] = "Total Sellout" if col == 'Product/Barcode' else ""
        
        # Sum all Tax_Incl columns
        tax_incl_cols = [col for col in pivot_df.columns if col.startswith('Tax_Incl_')]
        for col in tax_incl_cols:
            total_row_data[col] = pivot_df[col].sum()
        
        # Sum all Quantity columns
        qty_cols = [col for col in pivot_df.columns if col.startswith('Quantity_')]
        for col in qty_cols:
            total_row_data[col] = pivot_df[col].sum()
        
        # Create a total row DataFrame with same column order as pivot_df
        total_row_df = pd.DataFrame([total_row_data])
        total_row_df = total_row_df.reindex(columns=pivot_df.columns, fill_value="")
        
        # Insert overall Total Sellout row at current_row (after brand totals)
        ws_pivot.insert_rows(current_row)
        
        # Write total row to Excel
        for col_idx, col_name in enumerate(pivot_df.columns, 1):
            cell = ws_pivot.cell(row=current_row, column=col_idx)
            value = total_row_df.iloc[0][col_name]
            cell.value = value
    
    # Ensure Product/Barcode column in pivot is formatted as text
    # Find Product/Barcode column index in pivot table
    header_row = list(ws_pivot.iter_rows(min_row=1, max_row=1))[0]
    barcode_col_idx_pivot = None
    for idx, cell in enumerate(header_row):
        if cell.value == 'Product/Barcode':
            barcode_col_idx_pivot = idx
            break
    
    # Format all barcode cells as text in pivot (skip header and total rows)
    # Determine how many total rows to skip
    if organize_by_brand:
        # For brand-organized sections, format barcodes starting from row 2 (after header)
        # Brand total sellout rows and product rows are already written, so we format all rows after header
        start_data_row = 2  # Start after header (row 1)
    elif is_brand_organized:
        # Skip header + brand totals + overall total sellout
        num_total_rows = len(brands) + 1  # brand totals + overall total
        start_data_row = 1 + num_total_rows + 1  # header + totals + 1
    else:
        # Skip header + brand total sellout rows + overall total sellout row
        if df_group is not None and 'Brand' in df_group.columns:
            num_brands = len(df_group['Brand'].dropna().unique())
            start_data_row = 1 + num_brands + 1 + 1  # header + brand totals + overall total + 1
        else:
            # Skip header + total sellout row
            start_data_row = 3
    
    if barcode_col_idx_pivot is not None:
        for row in ws_pivot.iter_rows(min_row=start_data_row):
            cell = row[barcode_col_idx_pivot]
            if cell.value is not None:
                cell.value = str(cell.value)
                cell.number_format = '@'  # Text format
    
    # Sheet 2: Detailed Report
    ws_detailed = wb.create_sheet("Detailed Report")
    for r in dataframe_to_rows(detailed_df, index=False, header=True):
        ws_detailed.append(r)
    
    # Format Product/Barcode column as text in detailed report
    # Find Product/Barcode column index
    header_row = list(ws_detailed.iter_rows(min_row=1, max_row=1))[0]
    barcode_col_idx = None
    for idx, cell in enumerate(header_row, 1):
        if cell.value == 'Product/Barcode':
            barcode_col_idx = idx
            break
    
    # Format all barcode cells as text
    if barcode_col_idx:
        for row in ws_detailed.iter_rows(min_row=2):  # Skip header
            cell = row[barcode_col_idx - 1]  # Convert to 0-based index
            if cell.value is not None:
                cell.value = str(cell.value)
                cell.number_format = '@'  # Text format
    
    # Save to BytesIO
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    
    return output

def create_zip_file(workbooks_dict):
    """Create zip file containing all workbooks"""
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for workbook_key, workbook_bytes in workbooks_dict.items():
            # workbook_key format: "ParentBrand_Brand_Date" or "ParentBrand_Date"
            sanitized_name = sanitize_filename(workbook_key)
            filename = f"{sanitized_name}.xlsx"
            zip_file.writestr(filename, workbook_bytes.getvalue())
    
    zip_buffer.seek(0)
    return zip_buffer

def process_sales_workbook(uploaded_file, separate_by_date=False):
    """Main processing function: load, sort, group, and create workbooks
    
    Args:
        uploaded_file: Uploaded Excel file
        separate_by_date: If True, create separate sheets for each date
    """
    try:
        # Load Excel file - ensure Product/Barcode is read as string
        df = pd.read_excel(uploaded_file, dtype={'Product/Barcode': str})
        
        # Validate required columns
        required_columns = ['Order Date', 'Product/Barcode', 'Product', 'Parent Brand', 'Brand', 'Quantity', 'Tax Incl.']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")
        
        # Clean data
        # Ensure Product/Barcode is string (convert if needed)
        df['Product/Barcode'] = df['Product/Barcode'].astype(str)
        
        # Ensure Order Date is datetime
        df['Order Date'] = pd.to_datetime(df['Order Date'], errors='coerce')
        
        # Ensure numeric columns are numeric
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(0)
        df['Tax Incl.'] = pd.to_numeric(df['Tax Incl.'], errors='coerce').fillna(0)
        
        # Remove rows with missing critical data
        df = df.dropna(subset=['Order Date', 'Product/Barcode'])
        
        if df.empty:
            raise ValueError("No valid data found in the file")
        
        # Sort data
        df_sorted = sort_sales_data(df)
        
        # Group by Parent Brand
        grouped_dfs = group_by_parent_brand(df_sorted)
        
        # Process each group
        workbooks_dict = {}
        for parent_brand, df_group in grouped_dfs.items():
            # Extract date range from the group data
            earliest_date = df_group['Order Date'].min()
            latest_date = df_group['Order Date'].max()
            
            # Format date string for filename
            if earliest_date.date() == latest_date.date():
                # Single date
                date_str = earliest_date.strftime('%d%m%Y')  # Format: DDMMYYYY (e.g., 03112025)
            else:
                # Date range
                date_str_start = earliest_date.strftime('%d%m%Y')
                date_str_end = latest_date.strftime('%d%m%Y')
                date_str = f"{date_str_start}_to_{date_str_end}"  # Format: DDMMYYYY_to_DDMMYYYY
            
            # Determine which pivot function to use
            # Extract actual parent brand name (remove brand suffix if present)
            actual_parent_brand = parent_brand.split('_')[0] if '_' in parent_brand else parent_brand
            
            # Create workbook with date in the name
            # For non-Paragon/Hebe, organize by brand sections
            # Pass df_group and parent brand info for brand section organization
            is_non_paragon_hebe = (actual_parent_brand not in ['Paragon', 'Hebe'])
            
            if separate_by_date:
                # Create workbook with separate sheets per date
                workbook_bytes = create_workbook_for_parent_brand(
                    None, None, parent_brand, date_str, 
                    is_brand_organized=False, 
                    df_group=df_group, 
                    organize_by_brand=is_non_paragon_hebe,
                    separate_by_date=True
                )
            else:
                # Use barcode-based pivot for all Parent Brands (standard format with Quantity_Date and Tax_Incl_Date)
                pivot_df = create_pivot_by_barcode(df_group)
                
                # Create detailed report
                detailed_df = create_detailed_report(df_group)
                
                workbook_bytes = create_workbook_for_parent_brand(
                    pivot_df, detailed_df, parent_brand, date_str, 
                    is_brand_organized=False, 
                    df_group=df_group, 
                    organize_by_brand=is_non_paragon_hebe,
                    separate_by_date=False
                )
            
            # Store with date in key for filename generation
            workbooks_dict[f"{parent_brand}_{date_str}"] = workbook_bytes
        
        # Create zip file
        zip_file = create_zip_file(workbooks_dict)
        
        # Create summary - count unique parent brands (not split groups)
        unique_parent_brands = set()
        for group_key in grouped_dfs.keys():
            # Extract parent brand name from group key
            # For Paragon_Brand format, extract "Paragon"
            # For regular format, use as is
            if '_' in group_key and any(pb in group_key for pb in ['Paragon', 'Hebe']):
                # Split by underscore and take first part (parent brand)
                parent_brand = group_key.split('_')[0]
                unique_parent_brands.add(parent_brand)
            else:
                unique_parent_brands.add(group_key)
        
        # Create summary
        summary = {
            'total_rows': len(df_sorted),
            'parent_brands_count': len(unique_parent_brands),
            'workbooks_count': len(workbooks_dict),  # Total number of workbooks (including splits and dates)
            'date_range': {
                'start': df_sorted['Order Date'].min().strftime('%Y-%m-%d'),
                'end': df_sorted['Order Date'].max().strftime('%Y-%m-%d')
            },
            'parent_brands': sorted(unique_parent_brands),
            'workbook_keys': sorted(workbooks_dict.keys())  # All workbook names (with dates)
        }
        
        return workbooks_dict, zip_file, summary, None
        
    except Exception as e:
        return None, None, None, str(e)

def ba_sales_report_page():
    """BA Sales Report page content"""
    st.title("💰 Laporan Sellout Beauty Advisor (BA)")
    st.markdown("### Pembuat Laporan Sellout untuk Beauty Advisor (BA) dengan data dari ERP.")
    
    # Initialize session state for processed data
    if 'processed_workbooks' not in st.session_state:
        st.session_state.processed_workbooks = None
    if 'processed_zip' not in st.session_state:
        st.session_state.processed_zip = None
    if 'processing_summary' not in st.session_state:
        st.session_state.processing_summary = None
    if 'processing_error' not in st.session_state:
        st.session_state.processing_error = None
    if 'date_organization_option' not in st.session_state:
        st.session_state.date_organization_option = "Satukan tanggal"  # Default: combine dates
    
    # Date Organization Option
    st.subheader("📅 Date Organization")
    date_option = st.radio(
        "Pilih cara pengorganisasian tanggal:",
        ["Satukan tanggal", "Pisahkan per tanggal"],
        index=0 if st.session_state.date_organization_option == "Satukan tanggal" else 1,
        help="Satukan tanggal: Semua tanggal dalam satu tabel pivot. Pisahkan per tanggal: Setiap tanggal memiliki sheet terpisah."
    )
    st.session_state.date_organization_option = date_option
    
    # File Upload Section
    st.subheader("📤 Upload Excel File")
    uploaded_file = st.file_uploader(
        "Choose an Excel file",
        type=['xlsx', 'xls'],
        help="Upload Excel file with sales data. Required columns: Order Date, Product/Barcode, Product, Parent Brand, Brand, Quantity, Tax Incl."
    )
    
    if uploaded_file is not None:
        # Display file info
        col1, col2 = st.columns(2)
        with col1:
            st.info(f"📄 File: {uploaded_file.name}")
        with col2:
            file_size = uploaded_file.size / 1024  # KB
            st.info(f"📊 Size: {file_size:.2f} KB")
        
        # Process button
        if st.button("🔄 Process File", type="primary", use_container_width=True):
            with st.spinner("Processing file... This may take a moment."):
                separate_by_date = (st.session_state.date_organization_option == "Pisahkan per tanggal")
                workbooks_dict, zip_file, summary, error = process_sales_workbook(uploaded_file, separate_by_date=separate_by_date)
                
                if error:
                    st.session_state.processing_error = error
                    st.session_state.processed_workbooks = None
                    st.session_state.processed_zip = None
                    st.session_state.processing_summary = None
                else:
                    st.session_state.processed_workbooks = workbooks_dict
                    st.session_state.processed_zip = zip_file
                    st.session_state.processing_summary = summary
                    st.session_state.processing_error = None
                    st.success("✅ File processed successfully!")
                    st.rerun()
    
    # Display error if any
    if st.session_state.processing_error:
        st.error(f"❌ Error: {st.session_state.processing_error}")
    
    # Display processing summary
    if st.session_state.processing_summary:
        st.markdown("---")
        st.subheader("📊 Processing Summary")
        
        summary = st.session_state.processing_summary
        col1, col2, col3, col4, col5 = st.columns(5)
        
        with col1:
            st.metric("Total Rows", f"{summary['total_rows']:,}")
        
        with col2:
            st.metric("Parent Brands", summary['parent_brands_count'])
        
        with col3:
            st.metric("Workbooks", summary.get('workbooks_count', summary['parent_brands_count']))
        
        with col4:
            st.metric("Start Date", summary['date_range']['start'])
        
        with col5:
            st.metric("End Date", summary['date_range']['end'])
        
        # Download Section
        st.markdown("---")
        st.subheader("📥 Download Reports")
        
        # Zip file download
        if st.session_state.processed_zip:
            zip_bytes = st.session_state.processed_zip.getvalue()
            st.download_button(
                label="📦 Download All Workbooks (ZIP)",
                data=zip_bytes,
                file_name=f"Laporan Penjualan BA {datetime.now().strftime('%d%m%Y')}.zip",
                mime="application/zip",
                use_container_width=True,
                type="primary"
            )
        
        st.markdown("---")
        st.subheader("📄 Individual Brand Downloads")
        
        # Individual workbook downloads
        if st.session_state.processed_workbooks:
            # Display in columns for better layout
            cols = st.columns(3)
            for idx, (workbook_key, workbook_bytes) in enumerate(st.session_state.processed_workbooks.items()):
                col_idx = idx % 3
                with cols[col_idx]:
                    sanitized_name = sanitize_filename(workbook_key)
                    filename = f"{sanitized_name}.xlsx"
                    workbook_data = workbook_bytes.getvalue()
                    
                    # Format label for display (replace underscores with spaces for readability)
                    display_label = workbook_key.replace('_', ' ')[:40]
                    
                    st.download_button(
                        label=f"📥 {display_label}",
                        data=workbook_data,
                        file_name=filename,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key=f"download_{sanitized_name}_{idx}"
                    )
        
        # Reset button
        st.markdown("---")
        if st.button("🔄 Process New File", use_container_width=True):
            st.session_state.processed_workbooks = None
            st.session_state.processed_zip = None
            st.session_state.processing_summary = None
            st.session_state.processing_error = None
            st.rerun()
    
    # Placeholder content if no file processed
    if not st.session_state.processing_summary and not uploaded_file:
        st.markdown("---")
        st.info("👆 Upload Excel laporan penjualan ke sini.")
        
        st.markdown("---")
        st.subheader("📋 Expected File Format")
        st.text("The Excel file should contain the following columns:")
        st.code("""
- Order Date (datetime)
- Product/Barcode (text)
- Product (text)
- Parent Brand (text, can be empty)
- Brand (text)
- Quantity (numeric)
- Tax Incl. (numeric)
        """)
        
        st.markdown("---")
        st.subheader("ℹ️ Cara Penggunaan")
        st.markdown("""
        1. **Upload**: Upload your Excel file with sales data
        2. **Process**: Click "Process File" to sort and group the data
        3. **Sorting**: Data is sorted by Parent Brand (alphabetically), then by Order Date (earliest first)
        4. **Grouping**: Data is split into separate workbooks by Parent Brand (uses Brand if Parent Brand is empty)
        5. **Reports**: Each workbook contains:
           - **Pivoted Sheet**: Pivot table with barcode as rows, dates as columns (grouped by day)
           - **Detailed Report Sheet**: All transactions for that Parent Brand
        6. **Download**: Download individual workbooks or all workbooks as a ZIP file
        """)

def stock_control_page():
    """Stock Control page content"""
    st.title("📦 Stock Control")
    st.markdown("### Inventory Management System")
    
    st.info("This page will provide tools for monitoring and managing inventory levels.")
    
    st.subheader("📊 Current Stock Levels")
    st.text("Real-time inventory status will be displayed here.")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("#### DSI Report")
        st.text("DSI level will be flagged here.")
    
    with col2:
        st.markdown("#### Area Overstock Report")
        st.text("Untuk SKU dengan jumlah terlalu banyak terpajang di area.")
    
    with col3:
        st.markdown("#### Area Understock Report")
        st.text("Untuk SKU dengan jumlah terlalu sedikit terpajang di area.")

    with col4:
        st.markdown("#### ABC Analysis")
        st.text("Prioritas barang berdasarkan ABC Analysis.")
    
    st.markdown("---")
    st.subheader("🔍 Stock Search & Filter")
    st.text("Advanced search and filtering capabilities will be available here.")
    
    st.markdown("---")
    st.subheader("➕ Stock Operations")
    st.text("Stock adjustments, transfers, and other operations will be performed here.")

def dsi_report_page():
    """DSI Report page content"""
    st.title("📋 DSI Report")
    st.markdown("### Days Sales of Inventory Report")
    
    st.info("This page will display Days Sales of Inventory (DSI) analysis and metrics.")
    
    st.subheader("📊 DSI Overview")
    st.text("Key DSI metrics and indicators will be displayed here.")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Current DSI")
        st.metric("Average DSI", "---", "---")
        st.text("Detailed DSI calculations will be shown here.")
    
    with col2:
        st.markdown("#### DSI Trends")
        st.text("Historical DSI trends and patterns will be visualized here.")
    
    st.markdown("---")
    st.subheader("📈 Analysis by Category")
    st.text("DSI breakdown by product category will be available here.")
    
    st.markdown("---")
    st.subheader("⚠️ Alerts & Recommendations")
    st.text("DSI-related alerts and optimization recommendations will be provided here.")

def main():
    """Main application"""
    # Check authentication
    if not st.session_state.authenticated:
        login()
        return
    
    # Main application with tabs
    st.sidebar.title("Navigation")
    
    # Logout button
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        st.session_state.authenticated = False
        st.rerun()
    
    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Dashboard", "💰 BA Sales Report", "📦 Stock Control", "📋 DSI Report"])
    
    with tab1:
        dashboard_page()
    
    with tab2:
        ba_sales_report_page()
    
    with tab3:
        stock_control_page()
    
    with tab4:
        dsi_report_page()

if __name__ == "__main__":
    main()


    st.markdown(
        """
        <hr style="margin-top: 3em; margin-bottom: 0.5em;">
        <div style="text-align: center; color: gray; font-size: 0.95em;">
            Dibuat dengan ❤️, dari Tim Data NK.
        </div>
        """,
        unsafe_allow_html=True
    )
