import requests

def test_nse_analyzer_logic():
    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
        'accept-language': 'en,gu;q=0.9,hi;q=0.8',
        'accept-encoding': 'gzip, deflate, br'
    }
    session = requests.Session()
    print("Getting cookies from /option-chain...")
    req = session.get("https://www.nseindia.com/option-chain", headers=headers, timeout=5)
    cookies = dict(req.cookies)
    print("Cookies:", cookies)
    
    url = "https://www.nseindia.com/api/option-chain-equities?symbol=HDFCBANK"
    print("Getting API data...")
    res = session.get(url, headers=headers, timeout=5, cookies=cookies)
    
    print("Status:", res.status_code)
    try:
        data = res.json()
        if 'records' in data:
            print("Records count:", len(data['records'].get('data', [])))
        else:
            print("Dict received without records. Keys:", data.keys())
    except Exception as e:
        print("Error parsing json:", e)

if __name__ == "__main__":
    test_nse_analyzer_logic()
