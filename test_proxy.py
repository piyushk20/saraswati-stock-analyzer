import requests
import json
import urllib.parse

def test_proxy():
    target_url = "https://www.nseindia.com/api/option-chain-equities?symbol=HDFCBANK"
    encoded_url = urllib.parse.quote(target_url)
    proxy_url = f"https://api.allorigins.win/raw?url={encoded_url}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
    }
    
    print("Fetching via AllOrigins proxy...")
    res = requests.get(proxy_url, headers=headers, timeout=15)
    print("Status code:", res.status_code)
    try:
        data = res.json()
        print("Keys:", data.keys())
        if 'records' in data:
            print("Records data length:", len(data['records'].get('data', [])))
    except Exception as e:
        print("JSON parse error:", e)
        print("Response:", res.text[:200])

if __name__ == "__main__":
    test_proxy()
