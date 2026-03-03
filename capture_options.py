from playwright.sync_api import sync_playwright
import time

def capture():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_viewport_size({"width": 1280, "height": 800})
        # Load the frontend
        page.goto('file:///C:/Users/HP/indianstock/frontend/index.html')
        page.wait_for_timeout(2000)
        # Search for NIFTY to open the detailed view
        page.evaluate('showStockDetails("^NSEI", "NIFTY 50")')
        page.wait_for_timeout(5000)
        # Scroll down slightly to make sure the options box is fully visible
        page.evaluate('window.scrollBy(0, 300)')
        page.wait_for_timeout(500)
        page.screenshot(path='c:/Users/HP/.gemini/antigravity/brain/c314a0a5-d73f-4a61-a727-72a805e93789/options_final_rendered.png', full_page=True)
        print("Captured screenshot!")
        browser.close()

if __name__ == "__main__":
    capture()
