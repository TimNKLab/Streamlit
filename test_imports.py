#!/usr/bin/env python3

# Test script to verify all required imports work
try:
    import streamlit as st
    print("✅ Streamlit imported successfully")
    
    import pandas as pd
    print("✅ Pandas imported successfully")
    
    import numpy as np
    print("✅ NumPy imported successfully")
    
    import openpyxl
    print("✅ OpenPyXL imported successfully")
    
    import plotly.express as px
    print("✅ Plotly imported successfully")
    
    # Test basic functionality
    df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
    print(f"✅ Pandas DataFrame created: {df.shape}")
    
    # Test plotly pie chart creation
    fig = px.pie(values=[1, 2, 3], names=['A', 'B', 'C'], title="Test")
    print("✅ Plotly pie chart created successfully")
    
    print("\n🎉 All imports and basic functionality working!")
    
except ImportError as e:
    print(f"❌ Import error: {e}")
except Exception as e:
    print(f"❌ Error: {e}")
