import nsefin
from datetime import datetime, timedelta
import pandas as pd

def test_nsefin():
    try:
        # Create a new nse instance with a higher timeout
        nse = nsefin.NSEClient(timeout=30.0)
        symbol = "RELIANCE"
        
        # history(symbol, day_count=30, from_date=None, to_date=None)
        # Using day_count=90 for more data
        print(f"Fetching history for {symbol} with 30s timeout...")
        df = nse.history(symbol, day_count=90)
        
        if df is not None and not df.empty:
            print(f"Data for {symbol}:")
            print(df.head())
            print(f"Columns: {df.columns.tolist()}")
            print(f"Shape: {df.shape}")
        else:
            print("Received empty DataFrame")
            
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_nsefin()
