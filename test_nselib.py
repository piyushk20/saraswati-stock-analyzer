from nselib import derivatives

try:
    df = derivatives.nse_live_option_chain("HDFCBANK")
    print("Success. Rows:", len(df))
    print(df.head(2))
except Exception as e:
    print("Error:", e)
