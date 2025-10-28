import asyncio
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from langchain.tools import tool
import requests
from collections import Counter

@tool
def get_summary_html(url: str) -> str:
    """
    Summarizes the HTML from a URL.
    
    Returns the full HTML string (decoded as text).
    """
    response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
    soup = BeautifulSoup(response.content, 'html.parser')
    
    links = soup.find_all('a', href=True)
    job_links = [a for a in links if any(keyword in a.get_text().lower() or keyword in a['href'].lower() 
                                          for keyword in ['job', 'career', 'position', 'opening', 'apply', 'vacancy'])]
    
    forms = soup.find_all('form')
    buttons = soup.find_all('button')
    inputs = soup.find_all('input')
    
    classes = [cls for elem in soup.find_all(class_=True) for cls in elem.get('class', [])]
    class_counts = Counter(classes).most_common(20)
    
    ids = [elem.get('id') for elem in soup.find_all(id=True)]
    id_counts = Counter(ids).most_common(20)
    
    job_containers = soup.find_all(['div', 'li', 'article', 'section'], 
                                    class_=re.compile(r'job|career|position|listing|card', re.I))
    
    pagination = soup.find_all(['a', 'button', 'div'], 
                                class_=re.compile(r'pag|next|prev|page', re.I))
    
    scripts = soup.find_all('script')
    api_patterns = [s for s in scripts if 'api' in s.get_text().lower() or 'fetch' in s.get_text().lower()]
    
    html_summary = f"""
    <html>
    <head><title>Career Page Analysis: {url}</title></head>
    <body>
        <h1>Career Page Analysis</h1>
        <h2>URL: {url}</h2>
        
        <h3>Strategy Summary</h3>
        <ul>
            <li><strong>Total Links:</strong> {len(links)}</li>
            <li><strong>Job-related Links:</strong> {len(job_links)}</li>
            <li><strong>Forms:</strong> {len(forms)}</li>
            <li><strong>Potential Job Containers:</strong> {len(job_containers)}</li>
            <li><strong>Pagination Elements:</strong> {len(pagination)}</li>
            <li><strong>API/Dynamic Content Scripts:</strong> {len(api_patterns)}</li>
        </ul>
        
        <h3>Sample Job Links (First 10)</h3>
        <ul>
            {''.join(f'<li><a href="{a["href"]}">{a.get_text(strip=True)[:100]}</a></li>' for a in job_links[:10])}
        </ul>
        
        <h3>Top Classes (for targeting)</h3>
        <ul>
            {''.join(f'<li>{cls}: {count}</li>' for cls, count in class_counts[:10])}
        </ul>
        
        <h3>Top IDs (for targeting)</h3>
        <ul>
            {''.join(f'<li>{id_}: {count}</li>' for id_, count in id_counts[:10])}
        </ul>
        
        <h3>Job Container Samples</h3>
        <ul>
            {''.join(f'<li>{elem.name} class="{elem.get("class")}"</li>' for elem in job_containers[:5])}
        </ul>
        
        <h3>Extraction Strategy</h3>
        <ol>
            <li>{'Use API scraping - detected dynamic content' if api_patterns else 'Use direct HTML parsing'}</li>
            <li>{'Target pagination elements for multi-page scraping' if pagination else 'Single page listing'}</li>
            <li>Job selector: {job_containers[0].name + '.' + '.'.join(job_containers[0].get('class', [])) if job_containers else 'Manual inspection needed'}</li>
            <li>Link extraction: {'Filter links containing job keywords' if job_links else 'Check for dynamic loading'}</li>
        </ol>
    </body>
    </html>
    """
    
    return html_summary

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
    # print(joblist)
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
            l = (f"- {title} - {link}\n")
            joblist += l
            # print(f"{title}\t{link}")
        return joblist


    joblist = asyncio.run(list_jobs(URL))
    # print(joblist)
    return str('Here is the job list, each line contain the job name followed by the url:\n'+joblist)

@tool
def get_YPSOMED_jobs():
    """This tool function helps you get YPSOMED current job list"""
    
    async def get_ypsomed_jobs():    
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto('https://careers.ypsomed.com/ypsomed/en/professional/', wait_until='networkidle')
            
            await page.wait_for_timeout(5000)
            
            try:
                await page.wait_for_selector('[data-ph-at-id="jobs-list"]', timeout=10000)
            except:
                pass
            
            content = await page.content()
            
            jobs_data = await page.evaluate('''() => {
                const jobs = [];
                const jobElements = document.querySelectorAll('[data-ph-at-id="job-link"]');
                jobElements.forEach(job => {
                    const title = job.textContent.trim();
                    const link = job.href;
                    const parent = job.closest('tr') || job.closest('div');
                    let location = '';
                    if (parent) {
                        const locationElem = parent.querySelector('[data-ph-at-id="job-location"]');
                        if (locationElem) location = locationElem.textContent.trim();
                    }
                    jobs.push({title, link, location});
                });
                return jobs;
            }''')
            
            await browser.close()
            
            if not jobs_data:
                soup = BeautifulSoup(content, 'html.parser')
                all_links = soup.find_all('a', href=True)
                jobs_data = []
                for link in all_links:
                    href = link.get('href', '')
                    if 'job' in href.lower() and len(link.get_text(strip=True)) > 5:
                        title = link.get_text(strip=True)
                        full_link = href if href.startswith('http') else 'https://careers.ypsomed.com' + href
                        jobs_data.append({'title': title, 'link': full_link, 'location': ''})
            
            if not jobs_data:
                return "No jobs found or page structure has changed"
            
            result = []
            for job in jobs_data:
                location_str = f" - {job['location']}" if job['location'] else ""
                result.append(f"- {job['title']}{location_str} - {job['link']}")
            
            return "\n".join(result)
    ## MAIN ##
    # =========================================
    # this runs outside of async
    ## await get_YPSOMED_jobs() # from juypyter
    result = asyncio.run(get_ypsomed_jobs())
    # print(result)
    return result

@tool
def get_VISIUM_jobs():
    """This tool function helps you get VISIUM current job list"""
    async def get_visium_jobs():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto('https://www.visium.com/join-us#open-positions', wait_until='networkidle')
            await page.wait_for_timeout(5000)
            
            await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            await page.wait_for_timeout(3000)
            
            try:
                await page.wait_for_selector('[id*="open-position"], [class*="job"], [class*="position"], [class*="career"], [data-job], [role="listitem"]', timeout=5000)
            except:
                pass
            
            content = await page.content()
            await browser.close()
            
            soup = BeautifulSoup(content, 'html.parser')
            
            jobs = []
            
            open_positions_section = soup.find(id=lambda x: x and 'open-position' in x.lower()) or soup.find(class_=lambda x: x and any(term in str(x).lower() for term in ['open-position', 'job-list', 'career-list', 'position-list']))
            
            if open_positions_section:
                job_elements = open_positions_section.find_all(['a', 'div', 'li'], recursive=True)
                
                for elem in job_elements:
                    text = elem.get_text(strip=True)
                    
                    if 15 < len(text) < 150 and not any(skip in text.lower() for skip in ['view open position', 'explore benefit', 'apply now', 'learn more', 'read more', 'click here']):
                        link = ''
                        if elem.name == 'a':
                            link = elem.get('href', '')
                        else:
                            link_elem = elem.find('a', recursive=False)
                            if link_elem:
                                link = link_elem.get('href', '')
                        
                        if link and not link.startswith('http'):
                            if link.startswith('/'):
                                link = 'https://www.visium.com' + link
                            else:
                                link = 'https://www.visium.com/' + link
                        
                        if link and 'job' in link.lower() or 'career' in link.lower() or 'position' in link.lower():
                            job_entry = f"{text} - {link}"
                            if job_entry not in jobs:
                                jobs.append(job_entry)
            
            if not jobs:
                all_links = soup.find_all('a', href=True)
                for link_elem in all_links:
                    href = link_elem.get('href', '')
                    if any(term in href.lower() for term in ['greenhouse', 'lever', 'workday', 'bamboohr', 'job', 'career', 'position', 'apply']):
                        text = link_elem.get_text(strip=True)
                        if 10 < len(text) < 150:
                            if not href.startswith('http'):
                                if href.startswith('/'):
                                    href = 'https://www.visium.com' + href
                                else:
                                    href = 'https://www.visium.com/' + href
                            job_entry = f"{text} - {href}"
                            if job_entry not in jobs:
                                jobs.append(job_entry)
            
            if not jobs:
                return "No job listings found on the page. The page may not have open positions or uses a different structure."
            
            return '\n'.join(jobs[:30])
    
    # def main():
    result = asyncio.run(get_visium_jobs())
    # print(result)
    return result
