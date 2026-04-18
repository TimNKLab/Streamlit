import pandas as pd

df = pd.read_excel('data/products.xlsx')
print('# HARDCODED_PRODUCTS entries from Excel:')
for _, row in df.iterrows():
    barcode = str(row['barcode']).strip()
    name = str(row['name']).replace('"', '\\"')
    het = row['het']
    if pd.isna(het):
        continue  # Skip rows with no price
    het = int(het)
    diskon = row.get('diskon')
    if pd.isna(diskon):
        diskon_str = 'None'
    else:
        diskon_str = str(int(diskon))
    print(f'    "{barcode}": {{"name": "{name}", "het": {het}, "diskon": {diskon_str}}},')
