import cloudscraper

def test_scraper():
    scraper = cloudscraper.create_scraper(browser={
        'browser': 'chrome',
        'platform': 'windows',
        'desktop': True
    })
    print("Getting base cookies...")
    scraper.get("https://www.nseindia.com/option-chain", timeout=10)
    
    url = "https://www.nseindia.com/api/option-chain-equities?symbol=HDFCBANK"
    print("Getting NSE API...")
    res = scraper.get(url, timeout=10)
    print("Status code:", res.status_code)
    try:
        data = res.json()
        print("Keys:", data.keys())
        if 'records' in data:
            print("Records data length:", len(data['records'].get('data', [])))
    except Exception as e:
        print("Scraper JSON error:", e)

if __name__ == "__main__":
    test_scraper()
