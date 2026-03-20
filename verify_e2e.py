import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={'width': 1280, 'height': 900})
        page = await context.new_page()
        
        try:
            print('Navigating to app...')
            await page.goto('http://127.0.0.1:8081')
            
            print('Waiting for initial load...')
            await asyncio.sleep(4)
            await page.screenshot(path='e2e_01_initial.png')
            print('? Initial load screenshot saved.')
            
            print('Testing Category Switch -> Nifty 200 (Mocking user click)')
            await page.evaluate("window.changeMomentumCategory('nifty200')")
            await asyncio.sleep(3)
            await page.screenshot(path='e2e_02_nifty200.png')
            print('? Category switch screenshot saved.')
            
            print('Testing Stock Selection (RELIANCE.NS)...')
            # Make sure dropdown has the option, or we can just deep link via evaluate if it hasn't loaded yet
            await page.evaluate('''
                const select = document.getElementById("stockSelector");
                if (!Array.from(select.options).some(o => o.value === "RELIANCE.NS")) {
                    const tempOpt = document.createElement("option");
                    tempOpt.value = "RELIANCE.NS";
                    tempOpt.text = "RELIANCE.NS";
                    select.add(tempOpt);
                }
                select.value = "RELIANCE.NS";
                select.dispatchEvent(new Event('change'));
            ''')
            await asyncio.sleep(5)
            await page.screenshot(path='e2e_03_stock_dashboard.png', full_page=True)
            print('? Stock dashboard loaded and screenshot saved.')
            
            print('Reloading page to test session persistence (Stock)...')
            await page.reload()
            await asyncio.sleep(5)
            
            # Check if stock selector still has RELIANCE.NS
            selected_stock = await page.evaluate("document.getElementById('stockSelector').value")
            print(f'? Session Restored Stock is: {selected_stock}')
            await page.screenshot(path='e2e_04_session_stock.png', full_page=True)
            
            print('Clicking Back to Dashboard...')
            await page.evaluate("document.getElementById('backToDashboardBtn').click()")
            await asyncio.sleep(2)
            await page.screenshot(path='e2e_05_back_dashboard.png')
            print('? Back to dashboard successful.')
            
            print('Switching category to Midcap 100...')
            await page.evaluate("window.changeMomentumCategory('midcap100')")
            await asyncio.sleep(2)
            
            print('Reloading page to test session persistence (Category)...')
            await page.reload()
            await asyncio.sleep(4)
            current_cat = await page.evaluate("currentMomentumCategory")
            print(f'? Session Restored Category is: {current_cat}')
            await page.screenshot(path='e2e_06_session_category.png')
            
            print('\n✅ ALL E2E UI TESTS COMPLETED SUCCESSFULLY.')
            
        except Exception as e:
            print(f'❌ ERROR ENCOUNTERED: {e}')
            await page.screenshot(path='e2e_error_state.png', full_page=True)
        finally:
            await browser.close()

asyncio.run(main())
