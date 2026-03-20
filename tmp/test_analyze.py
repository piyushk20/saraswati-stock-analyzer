import sys
import os
import json

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

try:
    from execution.analyze_stock import analyze
    
    print("Testing analyze('RELIANCE.NS')...")
    data = analyze("RELIANCE.NS")
    
    if "error" in data:
        print(f"ERROR: {data['error']}")
    else:
        chart = data.get("chart", {})
        print(f"Chart keys: {list(chart.keys())}")
        print(f"Dates length: {len(chart.get('dates', []))}")
        print(f"Opens length: {len(chart.get('opens', []))}")
        
        # Check Trend Template
        tt = data.get("trend_template", {})
        print(f"Trend Template found: {bool(tt)}")
        if tt:
            print(f"TT summary: {tt.get('summary', 'No summary')}")
            print(f"TT criteria count: {len(tt.get('criteria', []))}")
            # Safely print criteria (avoiding non-ascii)
            for c in tt.get('criteria', []):
                desc = c.get('description', '').encode('ascii', 'ignore').decode()
                status = "PASS" if c.get('status') else "FAIL"
                print(f"  - {status}: {desc}")
        
except Exception as e:
    import traceback
    traceback.print_exc()
