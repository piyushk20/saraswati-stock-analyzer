import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")
api_key = os.environ.get("API_KEY", "")

test_stocks = [
    ("RELIANCE.NS",   "Energy Large Cap"),
    ("TCS.NS",        "IT Large Cap"),
    ("^NSEI",         "Nifty 50 Index"),
    ("SBIN.NS",       "PSU Bank"),
    ("TATAMOTORS.NS", "Auto Large Cap"),
]

print("=" * 60)
print("  Multi-Timeframe RSI Verification")
print("=" * 60)

all_ok = True
for sym, cat in test_stocks:
    try:
        url = f"http://127.0.0.1:8000/api/analyze/{sym}"
        req = urllib.request.Request(url, headers={"X-API-Key": api_key})
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read())
        rsi = data.get("rsi") or {}
        price = data.get("price", "N/A")
        daily   = rsi.get("daily")
        weekly  = rsi.get("weekly")
        monthly = rsi.get("monthly")
        status = "OK" if (daily is not None and weekly is not None and monthly is not None) else "PARTIAL/FAIL"
        if status != "OK":
            all_ok = False
        print(f"\n[{status}] {sym} — {cat}")
        print(f"  Price  : {price}")
        print(f"  RSI Daily  : {daily}")
        print(f"  RSI Weekly : {weekly}")
        print(f"  RSI Monthly: {monthly}")
    except Exception as ex:
        all_ok = False
        print(f"\n[ERROR] {sym} — {cat}: {ex}")

print("\n" + "=" * 60)
print("  Overall result:", "PASS — All RSI values present" if all_ok else "FAIL — Some RSI values missing")
print("=" * 60)
sys.exit(0 if all_ok else 1)
