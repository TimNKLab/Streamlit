"""Convert Excel products to DuckDB for faster lookups"""
import os
import pandas as pd

try:
    import duckdb
    HAS_DUCKDB = True
except ImportError:
    HAS_DUCKDB = False
    print("DuckDB not installed. Run: pip install duckdb")
    exit(1)

def convert_excel_to_duckdb(excel_path="data/products.xlsx", duckdb_path="data/products.duckdb"):
    """Convert Excel to DuckDB with index for fast lookups."""
    
    if not os.path.exists(excel_path):
        print(f"[ERROR] Excel file not found: {excel_path}")
        return False
    
    print(f"[READ] {excel_path}...")
    df = pd.read_excel(excel_path)
    
    # Clean data
    df = df.dropna(subset=['barcode', 'name', 'het'])
    df['barcode'] = df['barcode'].astype(str).str.strip()
    
    print(f"[LOADED] {len(df)} products")
    
    # Create DuckDB
    print(f"[CREATE] DuckDB: {duckdb_path}")
    
    # Remove old file if exists
    if os.path.exists(duckdb_path):
        os.remove(duckdb_path)
        print("[CLEAN] Removed old DuckDB file")
    
    conn = duckdb.connect(duckdb_path)
    
    # Create table
    conn.execute("CREATE TABLE products AS SELECT * FROM df")
    
    # Create index for fast lookups
    conn.execute("CREATE UNIQUE INDEX idx_barcode ON products(barcode)")
    
    # Verify
    count = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
    conn.close()
    
    print(f"[DONE] DuckDB created with {count} products")
    print(f"[SIZE] {os.path.getsize(duckdb_path) / 1024 / 1024:.1f} MB")
    
    return True

if __name__ == "__main__":
    convert_excel_to_duckdb()
