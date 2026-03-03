from playwright.sync_api import sync_playwright
import time
import os
import shutil

def verify_app():
    # Save to the artifacts directory
    artifact_dir = r"C:\Users\HP\.gemini\antigravity\brain\077bd537-774f-4067-ae1a-6f357ce6772e"
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("console", lambda msg: print(f"Browser Console [{msg.type}]: {msg.text}"))
        print('Loading index.html...')
        page.goto('http://127.0.0.1:8081/index.html')
        page.wait_for_load_state('networkidle')
        time.sleep(3) # allow fetch to finish
        
        # Check NSE 500 Dropdown
        print('Verifying NSE 500 Dropdown...')
        page.locator('#stockSelector').click()
        time.sleep(1)
        dropdown_path = os.path.join(artifact_dir, 'final_dropdown_verified.png')
        page.screenshot(path=dropdown_path, full_page=True)
        print(f"Dropdown screenshot saved to {dropdown_path}")
        
        # Pick RELIANCE.NS to verify data load
        print('Selecting RELIANCE.NS...')
        page.locator('#stockSelector').select_option(value='RELIANCE.NS')
        time.sleep(10) # Wait for chart and data to load
        
        dashboard_path = os.path.join(artifact_dir, 'final_dashboard_verified.png')
        page.screenshot(path=dashboard_path, full_page=True)
        print(f"Dashboard screenshot saved to {dashboard_path}")
        
        browser.close()
        print('Verification Complete.')

if __name__ == "__main__":
    verify_app()
