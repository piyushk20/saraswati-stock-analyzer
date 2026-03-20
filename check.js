const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  
  page.on('console', msg => console.log('PAGE LOG:', msg.text()));
  page.on('pageerror', err => console.log('PAGE ERROR:', err.message));

  await page.goto('http://localhost:8080/');
  
  // Wait for 3 seconds to let fetch complete
  await page.waitForTimeout(3000);
  
  const gainersHTML = await page.evaluate(() => {
    const el = document.getElementById('gainersTableBody');
    return el ? el.outerHTML : 'NOT FOUND';
  });
  console.log("GAINERS HTML:", gainersHTML);
  
  const losersHTML = await page.evaluate(() => {
    const el = document.getElementById('losersTableBody');
    return el ? el.outerHTML : 'NOT FOUND';
  });
  console.log("LOSERS HTML:", losersHTML);
  
  const indicesHTML = await page.evaluate(() => {
    const el = document.getElementById('indicesRow');
    return el ? el.outerHTML : 'NOT FOUND';
  });
  console.log("INDICES HTML:", indicesHTML);
  
  await browser.close();
})();
