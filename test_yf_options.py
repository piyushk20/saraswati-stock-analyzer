import yfinance as yf

t = yf.Ticker("HDFCBANK.NS")
print("Options len:", len(t.options))
print("Options list:", t.options)
