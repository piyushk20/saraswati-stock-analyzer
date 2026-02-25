from nsepython import nsefetch
    
    url = "https://www.nseindia.com/api/option-chain-equities?symbol=HDFCBANK"
    try:
        data = nsefetch(url)
        print("Keys:", data.keys() if isinstance(data, dict) else type(data))
        if isinstance(data, dict):
            print("Records count:", len(data.get('records', {}).get('data', [])))
    except Exception as e:
        print("Error:", e)
    
