import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        print('navigating...')
        await page.goto('http://127.0.0.1:8081')
        print('waiting 3 seconds...')
        await asyncio.sleep(3)
        print('setting local storage and reloading...')
        await page.evaluate('''
            localStorage.setItem("lastCategory", "nifty200");
            localStorage.setItem("lastStock", "RELIANCE.NS");
        ''')
        await page.reload()
        
        await asyncio.sleep(5)
        
        print('taking screenshot...')
        await page.screenshot(path='session_restore.png', full_page=True)
        print('done!')
        await browser.close()

asyncio.run(main())
