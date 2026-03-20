from nsefin import NSEClient
import json
import pandas as pd

def fetch_manual_options(symbol, is_index=False):
    nse = NSEClient()
    # Ensure session is ready
    nse.session.get("https://www.nseindia.com/", timeout=10)
    
    kind = "indices" if is_index else "equities"
    url = f"https://www.nseindia.com/api/option-chain-{kind}?symbol={symbol}"
    
    print(f"Fetching from: {url}")
    r = nse.session.get(url, timeout=10)
    if r.status_code == 200:
        data = r.json()
        print("Keys:", data.keys())
        if "records" in data:
            records = data["records"]
            first_data = records["data"][0]
            print("First Record Data keys:", first_data.keys())
            if "CE" in first_data:
                print("CE keys:", first_data["CE"].keys())
            return data
    else:
        print(f"Error {r.status_code}")
    return None

if __name__ == "__main__":
    fetch_manual_options("TCS")
    fetch_manual_options("NIFTY", is_index=True)
