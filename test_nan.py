import math
import json
from execution.market_overview import fetch_market_overview

data = fetch_market_overview('nifty50')

def has_nan(obj):
    if isinstance(obj, float): return math.isnan(obj)
    if isinstance(obj, dict): return any(has_nan(v) for v in obj.values())
    if isinstance(obj, list): return any(has_nan(v) for v in obj)
    return False

print('HAS_NAN:', has_nan(data))
