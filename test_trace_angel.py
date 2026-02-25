import traceback
from execution.angel_options import get_angel_option_chain

try:
    print("Testing RELIANCE.NS options...")
    res = get_angel_option_chain('RELIANCE.NS', False)
    print("Success:", res)
except Exception as e:
    traceback.print_exc()
