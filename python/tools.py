import asyncio
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from langchain.agents import load_tools, initialize_agent, AgentType, tool

@tool
# def coolest_guy(text:str) -> str:
#     '''
#     Returns the name of the coolest person in the universe.
#     Expects an input of an empty string '' and returns the name of the coolest
#     person in the universe
#     '''
#     return 'Jose Portilla'

@tool
def get_NOVARTIS_jobs() -> str:
    """
    This tool function helps you get NOVARTIS current job list 
    """
    URL = "https://www.novartis.com/careers/career-search?search_api_fulltext=data&country%5B0%5D=LOC_CH&field_job_posted_date=All&op=Submit&page=0"


    def _norm(text: str) -> str:
        return " ".join((text or "").split())
    
    
    def _has_digit(s: str) -> bool:
        return any(ch.isdigit() for ch in s)
    
    
    def _is_bad_label(s: str) -> bool:
        t = s.strip().lower()
        return t in {"date posted", "hide lower priority columns"} or t.startswith("hide lower priority")
    
    
    def _extract_date(container) -> str or None:
        # 1) Prefer a <time> tag with digits
        for t in container.find_all("time"):
            val = t.get("datetime") or _norm(t.get_text())
            if val and _has_digit(val) and not _is_bad_label(val):
                return val
    
        # 2) Cells marked as Date Posted via attributes/classes
        selectors = [
            '[data-label*="Date"]',
            '[data-title*="Date"]',
            '[aria-label*="Date"]',
            '[class*="date"]',
            '[class*="posted"]',
            '.views-field-field-job-posted-date',
        ]
        for sel in selectors:
            for el in container.select(sel):
                val = _norm(el.get_text())
                if val and _has_digit(val) and not _is_bad_label(val):
                    return val
    
        # 3) If it's a table row, try the last cell(s)
        if container.name == "tr":
            tds = container.find_all("td")
            for td in reversed(tds[-3:]):  # check last few cells
                val = _norm(td.get_text())
                if val and _has_digit(val) and not _is_bad_label(val):
                    return val
    
        # 4) Lookup label "Date Posted" then grab the next meaningful text with digits
        for el in container.find_all(True):
            txt = _norm(el.get_text())
            if txt.lower() == "date posted":
                # check siblings and next elements
                sibs = [el.find_next_sibling(), el.find_next()]
                for s in sibs:
                    if not s:
                        continue
                    val = _norm(getattr(s, "get_text", lambda: "")())
                    if val and _has_digit(val) and not _is_bad_label(val):
                        return val
    
        # 5) Fallback: regex for date-like patterns within the container
        txt = " ".join(container.stripped_strings)
        m = re.search(
            r"(\b\d{4}-\d{2}-\d{2}\b|"
            r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
            r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b|"
            r"\b\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|"
            r"Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{4}\b|"
            r"\b\d{1,2}/\d{1,2}/\d{2,4}\b)",
            txt,
            flags=re.I,
        )
        if m:
            val = _norm(m.group(1))
            if val and _has_digit(val) and not _is_bad_label(val):
                return val
    
        return None
    
    
    def extract_jobs(html: str, base_url: str):
        soup = BeautifulSoup(html, "html.parser")
        jobs = {}
    
        for a in soup.select('a[href*="/careers/career-search/job/details/"]'):
            href = a.get("href")
            if not href:
                continue
            url = urljoin(base_url, href)
            title = _norm(a.get_text())
            if not title or title.lower() in {"apply", "learn more"}:
                # Try a heading in the same container
                container = a.find_parent(["tr", "article", "li", "div"])
                if container:
                    h = container.find(re.compile(r"^h[1-6]$"))
                    if h:
                        title = _norm(h.get_text())
            if not title or title.lower() in {"apply", "learn more"}:
                continue
    
            # Prefer table row as container; fallback to nearest block
            container = a.find_parent("tr") or a.find_parent(["article", "li", "div"])
            date_text = _extract_date(container) if container else None
    
            jobs[url] = {"title": title, "url": url, "date": date_text if date_text else None}
    
        return list(jobs.values())
    
    
    async def main():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context()
            page = await ctx.new_page()
    
            await page.goto(URL, wait_until="domcontentloaded")
            try:
                await page.wait_for_selector('a[href*="/careers/career-search/job/details/"]', timeout=20000)
            except Exception:
                try:
                    await page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
    
            html = await page.content()
            jobs = extract_jobs(html, URL)
            joblist = ''
            for j in jobs:
                if j.get("date"):
                    l = f"- {j['title']} — {j['url']} — {j['date']}\n"
                    joblist += l
                    # print(l)
                else:
                    l = f"- {j['title']} — {j['url']}\n"
                    joblist += l
                    # print(l)
    
            await browser.close()
            return joblist

    ## MAIN ##
    joblist = asyncio.run(main())
    print(joblist)
    return str('Here is the job list:\n'+joblist)

@tool
def get_AWS_jobs() -> str:
    """
    This tool function helps you get AWS current job list 
    """
    URL = "https://www.amazon.jobs/content/en/locations/switzerland/zurich?category%5B%5D=Solutions+Architect"

    async def list_jobs(url: str):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36", locale="en-US")
            page = await context.new_page()
            await page.goto(url, wait_until="domcontentloaded")
            for text in ["Accept", "Accept All", "Accept all", "Accept Cookies", "I Accept", "Allow all", "Allow All"]:
                btn = page.locator(f"button:has-text('{text}')")
                if await btn.count() > 0:
                    try:
                        await btn.first.click()
                        break
                    except:
                        pass
            for _ in range(10):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(800)
            try:
                await page.wait_for_selector("a[href*='/jobs/'], a[href*='/job/']", timeout=5000)
            except:
                pass
            html = await page.content()
            await browser.close()
        soup = BeautifulSoup(html, "html.parser")
        links = soup.select("a[href*='/jobs/'], a[href*='/job/']")
        seen = set()
        jobs = []
        for a in links:
            href = a.get("href") or ""
            if not href:
                continue
            full = urljoin(url, href)
            if full in seen:
                continue
            title = a.get_text(strip=True)
            if not title:
                continue
            if "job" not in full and "jobs" not in full:
                continue
            seen.add(full)
            jobs.append((title, full))
        
        joblist = ''
        for title, link in jobs:
            l = (f"{title} - {link}\n")
            joblist += l
            # print(f"{title}\t{link}")
        return joblist


    joblist = asyncio.run(list_jobs(URL))
    print(joblist)
    return str('Here is the job list:\n'+joblist)
    