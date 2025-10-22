import asyncio
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

URL = "https://csl.wd1.myworkdayjobs.com/en-EN/CSL_External?locationCountry=187134fccb084a0ea9b4b95f23890dbe"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(URL, wait_until="domcontentloaded")
        # Wait for job cards to render
        try:
            await page.wait_for_selector('a[data-automation-id="jobTitle"], a[data-automation-id="jobTitleLink"]', timeout=20000)
        except:
            pass
        html = await page.content()
        await browser.close()

    soup = BeautifulSoup(html, "html.parser")
    jobs = []
    for a in soup.select('a[data-automation-id="jobTitle"], a[data-automation-id="jobTitleLink"]'):
        title = a.get_text(strip=True)
        href = urljoin(URL, a.get("href") or "")
        if title and href:
            jobs.append({"title": title, "url": href})

    for j in jobs:
        print(f"{j['title']} - {j['url']}")
   
if __name__ == "__main__":
    asyncio.run(main())
    #  await main()  