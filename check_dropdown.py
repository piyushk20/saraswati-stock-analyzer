from playwright.sync_api import sync_playwright
import time

def check_dropdown():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda msg: print(f"Browser Console [{msg.type}]: {msg.text}"))
        print('Loading page...')
        page.goto('http://127.0.0.1:8081')
        print('Waiting for network idle...')
        page.wait_for_load_state('networkidle')
        time.sleep(3) # Wait extra time for fetch to populate
        
        options_count = page.evaluate('document.querySelectorAll("#nse500Group option").length')
        print(f'Options in NSE500 group: {options_count}')
        
        if options_count > 0:
            first_few = page.evaluate('Array.from(document.querySelectorAll("#nse500Group option")).slice(0, 5).map(o => o.text)')
            last_few = page.evaluate('Array.from(document.querySelectorAll("#nse500Group option")).slice(-5).map(o => o.text)')
            print(f'First few options: {first_few}')
            print(f'Last few options: {last_few}')
        else:
            print("Dropdown is EMPTY!")
            
        browser.close()

if __name__ == "__main__":
    check_dropdown()
