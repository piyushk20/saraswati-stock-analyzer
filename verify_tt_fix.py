
import sys
import os

# Add execution to path
sys.path.append(os.path.abspath("execution"))

from analyze_stock import analyze

def test_trend_template(symbol):
    print(f"\n--- Testing Trend Template for {symbol} ---")
    try:
        result = analyze(symbol)
        tt = result.get("trend_template")
        if tt:
            print(f"✅ Trend Template found for {symbol}")
            print(f"   Score: {tt.get('score_pct')}%")
            print(f"   Passed: {tt.get('passed')}/{tt.get('total')}")
            checks = tt.get("checks", [])
            print(f"   Checks count: {len(checks)}")
            # Show a few checks
            for c in checks[:3]:
                status = "PASS" if c.get("pass") else "FAIL"
                print(f"   - {status}: {c.get('label')} ({c.get('value')})")
        else:
            print(f"❌ Trend Template NOT found for {symbol}")
    except Exception as e:
        print(f"💥 Error analyzing {symbol}: {e}")

if __name__ == "__main__":
    test_trend_template("^NSEI")  # Index
    test_trend_template("RELIANCE.NS")  # Stock
