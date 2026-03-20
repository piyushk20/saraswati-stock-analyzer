from nsefin import NSEClient
import pandas as pd

def test_options(symbol):
    nse = NSEClient()
    try:
        print(f"Fetching option chain for {symbol}...")
        df = nse.get_option_chain(symbol)
        print(f"Columns: {df.columns.tolist()}")
        print(df.head(2))
    except Exception as e:
        print(f"Error for {symbol}: {e}")

if __name__ == "__main__":
    test_options("RELIANCE")
    test_options("NIFTY")
