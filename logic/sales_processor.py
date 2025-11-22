"""Sales data processing logic module"""

import pandas as pd
import re
from datetime import datetime
from .excel_utils import (
    create_pivot_by_barcode, 
    create_grouped_detailed_report,
    create_workbook_for_parent_brand,
    create_zip_file,
    sanitize_filename
)

class SalesProcessor:
    """Handles sales data processing operations"""
    
    def __init__(self):
        pass
    
    def sort_sales_data(self, df):
        """Sort data by Parent Brand (alphabetically) then Order Date (earliest date, then earliest hour)"""
        df = df.copy()
        
        if not pd.api.types.is_datetime64_any_dtype(df['Order Date']):
            df['Order Date'] = pd.to_datetime(df['Order Date'], errors='coerce')
        
        df['sort_key_parent_brand'] = df['Parent Brand'].fillna(df['Brand'])
        df['sort_date'] = df['Order Date'].dt.date
        df['sort_hour'] = df['Order Date'].dt.hour
        
        df_sorted = df.sort_values(
            by=['sort_key_parent_brand', 'sort_date', 'sort_hour', 'Order Date'],
            ascending=[True, True, True, True],
            na_position='last'
        )
        
        df_sorted = df_sorted.drop(columns=['sort_key_parent_brand', 'sort_date', 'sort_hour'])
        
        return df_sorted.reset_index(drop=True)
    
    def group_by_parent_brand(self, df):
        """Group data by Parent Brand (use Brand if Parent Brand is None).
        For Paragon and Hebe, also split by Brand."""
        groups = {}
        split_by_brand_parents = ['Paragon', 'Hebe']
        
        for idx, row in df.iterrows():
            parent_brand = row['Parent Brand'] if pd.notna(row['Parent Brand']) else row['Brand']
            brand = row['Brand'] if pd.notna(row['Brand']) else 'Unknown'
            
            if parent_brand in split_by_brand_parents:
                group_key = f"{parent_brand}_{brand}"
            else:
                group_key = parent_brand
            
            if group_key not in groups:
                groups[group_key] = []
            groups[group_key].append(idx)
        
        grouped_dfs = {}
        for key, indices in groups.items():
            grouped_dfs[key] = df.loc[indices].reset_index(drop=True)
        
        return grouped_dfs
    
    def validate_sales_data(self, df):
        """Validate that the sales data has required columns"""
        required_columns = ['Order Date', 'Product/Barcode', 'Product', 'Parent Brand', 'Brand', 'Quantity', 'Tax Incl.']
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")
        
        return True
    
    def clean_sales_data(self, df):
        """Clean and preprocess sales data"""
        df['Product/Barcode'] = df['Product/Barcode'].astype(str)
        df['Order Date'] = pd.to_datetime(df['Order Date'], errors='coerce')
        df['Quantity'] = pd.to_numeric(df['Quantity'], errors='coerce').fillna(0)
        df['Tax Incl.'] = pd.to_numeric(df['Tax Incl.'], errors='coerce').fillna(0)
        
        df = df.dropna(subset=['Order Date', 'Product/Barcode'])
        
        if df.empty:
            raise ValueError("No valid data found in the file")
        
        return df
    
    def process_sales_workbook(self, uploaded_file, separate_by_date=False):
        """Main processing function for sales workbook"""
        try:
            df = pd.read_excel(uploaded_file, dtype={'Product/Barcode': str})
            
            self.validate_sales_data(df)
            df = self.clean_sales_data(df)
            
            df_sorted = self.sort_sales_data(df)
            grouped_dfs = self.group_by_parent_brand(df_sorted)
            
            workbooks_dict = {}
            for parent_brand, df_group in grouped_dfs.items():
                earliest_date = df_group['Order Date'].min()
                latest_date = df_group['Order Date'].max()
                
                if earliest_date.date() == latest_date.date():
                    date_str = earliest_date.strftime('%d%m%Y')
                else:
                    date_str_start = earliest_date.strftime('%d%m%Y')
                    date_str_end = latest_date.strftime('%d%m%Y')
                    date_str = f"{date_str_start}_to_{date_str_end}"
                
                actual_parent_brand = parent_brand.split('_')[0] if '_' in parent_brand else parent_brand
                is_non_paragon_hebe = (actual_parent_brand not in ['Paragon', 'Hebe'])
                
                if separate_by_date:
                    workbook_bytes = create_workbook_for_parent_brand(
                        None, None, parent_brand, date_str, 
                        is_brand_organized=False, 
                        df_group=df_group, 
                        organize_by_brand=is_non_paragon_hebe,
                        separate_by_date=True
                    )
                else:
                    pivot_df = create_pivot_by_barcode(df_group)
                    detailed_df = create_grouped_detailed_report(df_group, organize_by_brand=is_non_paragon_hebe)
                    
                    workbook_bytes = create_workbook_for_parent_brand(
                        pivot_df, detailed_df, parent_brand, date_str, 
                        is_brand_organized=False, 
                        df_group=df_group, 
                        organize_by_brand=is_non_paragon_hebe,
                        separate_by_date=False
                    )
                
                workbooks_dict[f"{parent_brand}_{date_str}"] = workbook_bytes
            
            zip_file = create_zip_file(workbooks_dict)
            
            unique_parent_brands = set()
            for group_key in grouped_dfs.keys():
                if '_' in group_key and any(pb in group_key for pb in ['Paragon', 'Hebe']):
                    parent_brand = group_key.split('_')[0]
                    unique_parent_brands.add(parent_brand)
                else:
                    unique_parent_brands.add(group_key)
            
            summary = {
                'total_rows': len(df_sorted),
                'parent_brands_count': len(unique_parent_brands),
                'workbooks_count': len(workbooks_dict),
                'date_range': {
                    'start': df_sorted['Order Date'].min().strftime('%Y-%m-%d'),
                    'end': df_sorted['Order Date'].max().strftime('%Y-%m-%d')
                },
                'parent_brands': sorted(unique_parent_brands),
                'workbook_keys': sorted(workbooks_dict.keys())
            }
            
            return workbooks_dict, zip_file, summary, None
            
        except Exception as e:
            return None, None, None, str(e)
