from curl_cffi import requests
import json

def fetch_options_cffi():
    url = "https://www.nseindia.com/api/option-chain-equities?symbol=HDFCBANK"
    session = requests.Session(impersonate="chrome110")
    
    # Needs base cookies first
    print("Getting base NSE cookies...")
    r1 = session.get("https://www.nseindia.com", timeout=10)
    print("Base status:", r1.status_code)
    
    print("Getting API...")
    r2 = session.get(url, timeout=10)
    print("API status:", r2.status_code)
    try:
        data = r2.json()
        print("Success, keys:", data.keys())
        if 'records' in data:
            print("Records count:", len(data['records'].get('data', [])))
    except Exception as e:
        print("Failed to decode JSON:", e)
        print("Response text:", r2.text[:200])

if __name__ == "__main__":
    fetch_options_cffi()
