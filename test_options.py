import yfinance as yf
import pandas as pd

def test_options(symbol):
    ticker = yf.Ticker(symbol)
    try:
        expirations = ticker.options
        print(f"Expirations for {symbol}: {expirations}")
        if expirations:
            chain = ticker.option_chain(expirations[0])
            print(f"Calls for {symbol} at {expirations[0]}:")
            print(chain.calls.head())
    except Exception as e:
        print(f"Error for {symbol}: {e}")

if __name__ == "__main__":
    test_options("TCS.NS")
    test_options("RELIANCE.NS")
