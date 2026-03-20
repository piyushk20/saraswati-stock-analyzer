from playwright.sync_api import sync_playwright

def run_debug():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda msg: print(f"Browser Console [{msg.type}]: {msg.text}".encode('ascii', 'replace').decode('ascii')))
        
        print("Loading application frontend...")
        page.goto('http://127.0.0.1:8081?noscan=1')
        page.wait_for_load_state("domcontentloaded")
        print("Waiting for stock list to load...")
        page.wait_for_timeout(5000) # Wait for nse500 population
        
        symbols_to_test = [
            {"name": "NIFTY_BANK", "id": "^NSEBANK"},
            {"name": "RELIANCE", "id": "RELIANCE.NS"},
            {"name": "TCS", "id": "TCS.NS"}
        ]
        
        for item in symbols_to_test:
            print(f"\n--- Testing {item['name']} ({item['id']}) ---")
            
            try:
                print(f"Selecting {item['id']} from dropdown...")
                page.select_option("#stockSelector", value=item["id"])
                
                print("Waiting for dashboard to be visible...")
                page.wait_for_selector("#dashboardEl", state="visible", timeout=25000)
                
                print("Waiting for mainChart...")
                page.wait_for_selector("#mainChart", state="visible", timeout=15000)
                
                print("Waiting for charts to settle...")
                page.wait_for_timeout(4000)
                
                print("Scrolling slightly...")
                page.evaluate('window.scrollTo(0, 500)')
                page.wait_for_timeout(1000)
                
                safe_name = item['name'].replace(' ', '_')
                screenshot_path = f'C:/Users/HP/.gemini/antigravity/brain/88f397de-0a51-410b-876f-88049ab40cd9/final_test_{safe_name}.png'
                page.screenshot(path=screenshot_path, full_page=True)
                print(f"Captured full analysis screenshot for {item['name']} at {screenshot_path}")
                
            except Exception as e:
                print(f"!!! Error during {item['name']} verification !!!")
                print(str(e))

        browser.close()

if __name__ == "__main__":
    run_debug()
