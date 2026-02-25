from SmartApi import SmartConnect
import pyotp
import urllib.request
import json
import logging
import sys
import pickle
import os

logging.getLogger("urllib3").setLevel(logging.WARNING)

def test_option_chain():
    api_key = "jeCM89TR"
    client_code = "P306112"
    password = "0673"
    totp_secret = "WF75HNPE7V4YJRXFEFG6LLNHBM"
    
    smartApi = SmartConnect(api_key=api_key)
    try:
        smartApi.generateSession(client_code, password, pyotp.TOTP(totp_secret).now())
        
        # Load instrument list from disk if it exists to be much faster
        master_file = "OpenAPIScripMaster.pkl"
        if os.path.exists(master_file):
            print("Loading from cache...")
            with open(master_file, "rb") as f:
                instrument_list = pickle.load(f)
        else:
            print("Downloading instrument list...")
            inst_url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            req = urllib.request.Request(inst_url)
            with urllib.request.urlopen(req) as response:
                instrument_list = json.loads(response.read().decode())
                # Cache it
                with open(master_file, "wb") as f:
                    pickle.dump(instrument_list, f)
            
        hdfc_options = [x for x in instrument_list if x['name'] == 'NIFTY' and x['exch_seg'] == 'NFO' and x['instrumenttype'] == 'OPTIDX']
        
        if len(hdfc_options) > 0:
            hdfc_options.sort(key=lambda x: x['expiry'])
            nearest_expiry = hdfc_options[0]['expiry']
            print("Nearest expiry:", nearest_expiry)
            
            opts_for_expiry = [x for x in hdfc_options if x['expiry'] == nearest_expiry]
            
            # Extract just 2 tokens
            tokens = [x['token'] for x in opts_for_expiry[:2]]
            
            res = smartApi.getMarketData("FULL", {"NFO": tokens})
            if res.get('status'):
                fetched = res.get('data', {}).get('fetched', [])
                for item in fetched:
                    print(json.dumps(item, indent=2))
            else:
                 print("Error fetching market data:", res)
                 
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    test_option_chain()
