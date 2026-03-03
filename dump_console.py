from playwright.sync_api import sync_playwright
import time

def get_console():
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page()
        page.on('console', lambda msg: print(f'Console: {msg.text}'))
        page.on('pageerror', lambda e: print(f'Page Error: {e}'))
        print("Opening Page...")
        # Remove wait_until="networkidle" so it doesn't hang if a fetch fails or takes too long
        page.goto('http://127.0.0.1:8081')
        print("Waiting 10 seconds for execution...")
        time.sleep(10)
        b.close()

if __name__=='__main__':
    get_console()
