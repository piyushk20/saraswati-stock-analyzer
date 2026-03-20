import requests
import pandas as pd
import json

def get_nse_option_chain(symbol, indices=False):
    base_url = "https://www.nseindia.com/"
    if indices:
        api_url = f"https://www.nseindia.com/api/option-chain-indices?symbol={symbol}"
    else:
        api_url = f"https://www.nseindia.com/api/option-chain-equities?symbol={symbol}"
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/option-chain"
    }
    
    session = requests.Session()
    session.headers.update(headers)
    
    # Hit home page to set cookies
    session.get(base_url, timeout=10)
    
    # Hit API
    response = session.get(api_url, timeout=10)
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error {response.status_code}: {response.text}")
        return None

if __name__ == "__main__":
    data = get_nse_option_chain("TCS")
    if data:
        print("Keys in response:", data.keys())
        # The data is in 'records' or 'filtered'
        if 'filtered' in data:
            print("First filtered record:", data['filtered']['data'][0] if data['filtered']['data'] else "No data")
    
    data_index = get_nse_option_chain("NIFTY", indices=True)
    if data_index:
        print("NIFTY Keys:", data_index.keys())
