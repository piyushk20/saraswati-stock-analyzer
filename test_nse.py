import requests

headers = {
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'accept-language': 'en-US,en;q=0.9',
    'accept-encoding': 'gzip, deflate, br'
}
s = requests.Session()
s.headers.update(headers)

print("Getting base...")
res = s.get("https://www.nseindia.com", timeout=10)
print("Base status:", res.status_code)

url = "https://www.nseindia.com/api/option-chain-equities?symbol=HDFCBANK"
print("Getting api...")
res2 = s.get(url, timeout=10)
print("API status:", res2.status_code)
try:
    d = res2.json()
    print("Keys:", d.keys())
    print("Has records:", 'records' in d)
except Exception as e:
    print("Error parsing JSON:", e)
