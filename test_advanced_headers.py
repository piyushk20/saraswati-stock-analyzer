import requests
from bs4 import BeautifulSoup
import json
import base64

def fetch_options():
    url = "https://www.nseindia.com/api/option-chain-equities?symbol=HDFCBANK"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/option-chain",
        "sec-ch-ua": "\"Chromium\";v=\"122\", \"Not(A:Brand\";v=\"24\", \"Google Chrome\";v=\"122\"",
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": "\"Windows\"",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin"
    }

    session = requests.Session()
    session.get("https://www.nseindia.com", headers=headers, timeout=10)
    
    response = session.get(url, headers=headers, timeout=10)
    print("Status:", response.status_code)
    try:
        data = response.json()
        print("Success, keys:", data.keys())
        if 'records' in data:
            print("Records count:", len(data['records'].get('data', [])))
    except Exception as e:
        print("Failed to decode JSON:", e)

if __name__ == "__main__":
    fetch_options()
