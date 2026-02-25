from SmartApi import SmartConnect
import pyotp
import urllib.request
import json
import logging
import os
import pickle
from datetime import datetime

from dotenv import load_dotenv

logging.getLogger("urllib3").setLevel(logging.WARNING)

load_dotenv()
API_KEY = os.getenv("ANGEL_API_KEY", "")
CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE", "")
PASSWORD = os.getenv("ANGEL_PASSWORD", "")
TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")

def get_angel_option_chain(symbol, is_index=False):
    # Mapping normal symbol to Angel One base name
    # In Angel One, Nifty 50 might be NIFTY, BankNifty is BANKNIFTY
    if symbol == "^NSEI" or symbol == "NIFTY 50":
        search_name = "NIFTY"
    elif symbol == "^NSEBANK":
        search_name = "BANKNIFTY"
    elif symbol.endswith(".NS"):
        search_name = symbol.replace(".NS", "")
    else:
        search_name = symbol

    options_data = {"current": None, "next": None}

    try:
        smartApi = SmartConnect(api_key=API_KEY)
        smartApi.generateSession(CLIENT_CODE, PASSWORD, pyotp.TOTP(TOTP_SECRET).now())
        
        master_file = os.path.join(os.path.dirname(__file__), "OpenAPIScripMaster.pkl")
        if os.path.exists(master_file):
            with open(master_file, "rb") as f:
                instrument_list = pickle.load(f)
        else:
            inst_url = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
            req = urllib.request.Request(inst_url)
            with urllib.request.urlopen(req) as response:
                instrument_list = json.loads(response.read().decode())
                with open(master_file, "wb") as f:
                    pickle.dump(instrument_list, f)

        # Filter option contracts for this symbol
        options = [x for x in instrument_list if x['name'] == search_name and x['exch_seg'] == 'NFO' and x['instrumenttype'] in ('OPTIDX', 'OPTSTK')]
        
        if not options:
            return options_data

        options.sort(key=lambda x: datetime.strptime(x['expiry'], "%d%b%Y"))
        
        expiries = list(dict.fromkeys([x['expiry'] for x in options]))
        if len(expiries) == 0:
            return options_data
            
        current_expiry = expiries[0]
        next_expiry = expiries[1] if len(expiries) > 1 else None
        
        for exp_key, exp_date in [("current", current_expiry), ("next", next_expiry)]:
            if not exp_date: continue
            
            opts_for_exp = [x for x in options if x['expiry'] == exp_date]
            
            # SmartAPI has a limit of tokens per request, let's take all of them usually there are ~50-100 per expiry
            # We will split into chunks of 45 just in case
            all_data = []
            chunk_size = 40
            for i in range(0, len(opts_for_exp), chunk_size):
                chunk = opts_for_exp[i:i+chunk_size]
                tokens = [x['token'] for x in chunk]
                res = smartApi.getMarketData("FULL", {"NFO": tokens})
                if res.get('status') and res.get('data'):
                    fetched = res.get('data', {}).get('fetched', [])
                    all_data.extend(fetched)
            
            if all_data:
                # Find max call OI and max put OI
                # We need to map token back to strike and type
                token_to_info = {x['token']: x for x in opts_for_exp}
                
                max_call_oi = 0
                max_call_strike = 0
                max_put_oi = 0
                max_put_strike = 0
                
                for item in all_data:
                    token = item.get('symbolToken')
                    oi = item.get('opnInterest', 0)
                    info = token_to_info.get(token)
                    if not info: continue
                    
                    strike = float(info['strike']) / 100 # Angel stores strike * 100
                    opt_type = info['symbol'][-2:] # CE or PE
                    
                    if opt_type == 'CE' and oi > max_call_oi:
                        max_call_oi = oi
                        max_call_strike = strike
                    elif opt_type == 'PE' and oi > max_put_oi:
                        max_put_oi = oi
                        max_put_strike = strike
                
                if max_call_oi > 0 or max_put_oi > 0:
                    options_data[exp_key] = {
                        "expiry_date": exp_date,
                        "max_call_oi_strike": max_call_strike,
                        "max_call_oi_vol": max_call_oi,
                        "max_put_oi_strike": max_put_strike,
                        "max_put_oi_vol": max_put_oi,
                        "pcr": round(sum(i.get('opnInterest',0) for i in all_data if token_to_info.get(i.get('symbolToken'),{}).get('symbol', '')[-2:]=='PE') / 
                                     max(1, sum(i.get('opnInterest',0) for i in all_data if token_to_info.get(i.get('symbolToken'),{}).get('symbol', '')[-2:]=='CE')), 2)
                    }
                    
    except Exception as e:
        print("Angel One Fetch Error:", e)

    return options_data
