from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto('http://localhost:3000')
    time.sleep(5) 
    
    # Select a stock from the dropdown
    page.select_option('select#stockSelector', 'RELIANCE.NS')
    time.sleep(10) # wait for the analysis to load

    page.screenshot(path='c:\\Users\\HP\\indianstock\\stock_analysis_reliance.png', full_page=True)
    browser.close()
    print("Screenshot captured successfully.")
