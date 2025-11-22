"""Stock control processing logic module"""

import pandas as pd
from datetime import datetime

class StockProcessor:
    """Handles stock control data processing operations"""
    
    def __init__(self):
        pass
    
    def process_stock_files(self, files, include_source=True):
        """Process multiple stock files and combine them"""
        combined_data = []
        
        for file in files:
            try:
                # Read the Excel file
                df = pd.read_excel(file, dtype={'Barcode': str})
                
                if include_source:
                    df['Source_File'] = file.name.replace('.xlsx', '').replace('.xls', '')
                
                combined_data.append(df)
                
            except Exception as e:
                raise Exception(f"Error processing {file.name}: {str(e)}")
        
        if not combined_data:
            raise ValueError("No data could be read from files")
        
        # Combine all data
        final_df = pd.concat(combined_data, ignore_index=True, sort=False)
        
        return self.transform_stock_data(final_df)
    
    def transform_stock_data(self, df):
        """Transform and clean stock data"""
        # Rename columns
        rename_map = {}
        if 'Quantity' in df.columns:
            rename_map['Quantity'] = 'Gudang'
        if 'Product/Quantity On Hand' in df.columns:
            rename_map['Product/Quantity On Hand'] = 'Sistem'
        
        if rename_map:
            df = df.rename(columns=rename_map)
        
        # Remove items with 0 quantity in Gudang column
        if 'Gudang' in df.columns:
            original_count = len(df)
            df = df[df['Gudang'] != 0]
            removed_count = original_count - len(df)
        
        # Add Area column
        if 'Gudang' in df.columns and 'Sistem' in df.columns:
            gudang_idx = df.columns.get_loc('Gudang')
            area_values = df['Sistem'] - df['Gudang']
            df.insert(gudang_idx + 1, 'Area', area_values)
        
        # Clean up Barcode column
        if 'Barcode' in df.columns:
            df['Barcode'] = df['Barcode'].astype(str).replace('nan', '')
        
        # Clean up Product/Product Category
        if 'Product/Product Category' in df.columns:
            df['Product/Product Category'] = df['Product/Product Category'].apply(
                lambda x: x.split('/')[-1].strip() if pd.notna(x) and '/' in str(x) else x
            )
        
        return df
    
    def sort_stock_data(self, df, sort_option="Urgency"):
        """Sort stock data based on selected option"""
        if sort_option == "Brand/Name":
            sort_columns = []
            
            if 'Product/Brand' in df.columns:
                sort_columns.append('Product/Brand')
            if 'Product/Name' in df.columns:
                sort_columns.append('Product/Name')
            
            if sort_columns:
                df = df.sort_values(by=sort_columns, ascending=True)
                df = df.reset_index(drop=True)
        
        return df
    
    def process_reference_lookup(self, df, reference_file):
        """Process reference file lookup and add status column"""
        if 'Barcode' not in df.columns:
            return df
        
        try:
            ref_df = pd.read_excel(reference_file, dtype={'Barcode': str})
            
            if 'Barcode' in ref_df.columns and 'Quantity' in ref_df.columns:
                df['Barcode'] = df['Barcode'].astype(str).str.strip()
                ref_df['Barcode'] = ref_df['Barcode'].astype(str).str.strip()
                
                ref_lookup = dict(zip(ref_df['Barcode'], ref_df['Quantity']))
                
                # Remove rows where Area > 6
                if 'Area' in df.columns:
                    original_count = len(df)
                    df = df[df['Area'] <= 6]
                    removed_count = original_count - len(df)
                
                # Create Status column
                def determine_status(row):
                    barcode = row['Barcode']
                    if barcode in ref_lookup:
                        return ""
                    else:
                        if 'Area' in df.columns:
                            return "URGENT" if row['Area'] == 0 else "Recheck"
                        else:
                            return "Recheck"
                
                df['Status'] = df.apply(determine_status, axis=1)
                
                # Move Status column to before Source_File
                if 'Source_File' in df.columns:
                    cols = list(df.columns)
                    cols.remove('Status')
                    source_idx = cols.index('Source_File')
                    cols.insert(source_idx, 'Status')
                    df = df[cols]
            
        except Exception as e:
            raise Exception(f"Error processing reference file: {str(e)}")
        
        return df
    
    def apply_urgency_sorting(self, df):
        """Apply urgency sorting after status column is created"""
        if 'Status' in df.columns:
            # Create urgency order for descending sort: URGENT = 2, Recheck = 1, others = 0
            urgency_order = {'URGENT': 2, 'Recheck': 1}
            df['urgency_sort'] = df['Status'].map(urgency_order).fillna(0)
            
            # Sort by urgency descending
            df = df.sort_values(by='urgency_sort', ascending=False)
            df = df.reset_index(drop=True)
            
            # Remove the temporary sort column
            df = df.drop('urgency_sort', axis=1)
        
        return df
    
    def get_stock_metrics(self, df):
        """Calculate metrics for stock data"""
        metrics = {
            'total_rows': len(df),
            'total_columns': len(df.columns),
            'max_area': df['Area'].max() if 'Area' in df.columns else None,
            'urgent_count': (df['Status'] == 'URGENT').sum() if 'Status' in df.columns else None
        }
        return metrics
    
    def get_status_analysis(self, df):
        """Get status analysis for stock data"""
        if 'Status' not in df.columns:
            return None
        
        status_counts = df['Status'].value_counts()
        total_count = len(df)
        
        analysis = []
        for status, count in status_counts.items():
            percentage = (count / total_count) * 100
            analysis.append({
                'status': status if status else "Found",
                'count': count,
                'percentage': percentage
            })
        
        return analysis
    
    def create_download_data(self, df):
        """Create downloadable data in Excel and CSV formats"""
        # Excel output
        excel_output = pd.ExcelWriter('temp.xlsx', engine='openpyxl')
        df.to_excel(excel_output, index=False, sheet_name='Combined Data')
        
        # CSV output
        csv_output = df.to_csv(index=False).encode('utf-8')
        
        return excel_output, csv_output
