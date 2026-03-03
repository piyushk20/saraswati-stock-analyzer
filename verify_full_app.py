from playwright.sync_api import sync_playwright

def run_debug():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda msg: print(f"Browser Console [{msg.type}]: {msg.text}"))
        
        print("Loading application frontend...")
        page.goto('http://127.0.0.1:8081')
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)
        
        symbols_to_test = [
            {"name": "NIFTY_BANK", "id": "^NSEBANK"},
            {"name": "RELIANCE", "id": "RELIANCE.NS"},
            {"name": "TCS", "id": "TCS.NS"}
        ]
        
        for item in symbols_to_test:
            print(f"\n--- Testing {item['name']} ({item['id']}) ---")
            
            try:
                print("Selecting from dropdown...")
                page.evaluate(f'''
                    const select = document.getElementById('stockSelector');
                    select.value = '{item["id"]}';
                    select.dispatchEvent(new Event('change'));
                ''')
                
                print("Waiting for dashboard to be visible...")
                page.wait_for_selector("#dashboardEl", state="visible", timeout=20000)
                
                print("Waiting for mainChart...")
                page.wait_for_selector("#mainChart", state="visible", timeout=15000)
                
                print("Waiting for charts to settle...")
                page.wait_for_timeout(4000)
                
                print("Scrolling slightly...")
                page.evaluate('window.scrollTo(0, 500)')
                page.wait_for_timeout(1000)
                
                safe_name = item['name'].replace(' ', '_')
                screenshot_path = f'c:/Users/HP/.gemini/antigravity/brain/077bd537-774f-4067-ae1a-6f357ce6772e/final_test_{safe_name}.png'
                page.screenshot(path=screenshot_path, full_page=True)
                print(f"Captured full analysis screenshot for {item['name']} at {screenshot_path}")
                
            except Exception as e:
                print(f"!!! Error during {item['name']} verification !!!")
                print(str(e))

            finally:
                page.reload()
                page.wait_for_timeout(2000)

        browser.close()

if __name__ == "__main__":
    run_debug()
