from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto('http://localhost:3000')
    time.sleep(10) # Wait 10 seconds for initial fetch payload to resolve
    page.screenshot(path='c:\\Users\\HP\\indianstock\\dashboard_fixed.png', full_page=True)
    browser.close()
    print("Screenshot captured successfully.")
