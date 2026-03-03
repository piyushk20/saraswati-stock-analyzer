from playwright.sync_api import sync_playwright

def capture():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 800})
        # Load the frontend
        page.goto('file:///C:/Users/HP/indianstock/frontend/index.html')
        page.wait_for_load_state("networkidle")
        
        # Search for NIFTY to open the detailed view
        page.click("text=NIFTY 50")
        
        # Wait for options data to load
        page.wait_for_selector("#optionsGrid .data-row")
        page.wait_for_timeout(2000)
        
        # Scroll down
        page.evaluate('window.scrollBy(0, 500)')
        page.wait_for_timeout(500)
        
        page.screenshot(path='c:/Users/HP/.gemini/antigravity/brain/c314a0a5-d73f-4a61-a727-72a805e93789/options_final_rendered.png', full_page=True)
        print("Captured screenshot!")
        browser.close()

if __name__ == "__main__":
    capture()
