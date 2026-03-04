import asyncio
import re
import json
import os
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from langchain.tools import tool
import requests
from collections import Counter

# Load company career page URLs from JSON file
def _load_career_urls() -> dict:
    """Load company to career page URL mapping from JSON file."""
    # Try multiple possible paths
    possible_paths = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'company2careerpage.json'),
        './data/company2careerpage.json',
        '../data/company2careerpage.json',
    ]
    for path in possible_paths:
        if os.path.exists(path):
            with open(path, 'r') as f:
                return json.load(f)
    return {}

COMPANY_URLS = _load_career_urls()


def _jobs_to_json(jobs: list) -> str:
    """
    Convert a list of job tuples/dicts to JSON format.
    Accepts either:
    - List of (name, url) tuples
    - List of dicts with 'name'/'title' and 'url' keys
    Returns JSON string: {"jobs": [{"name": "...", "url": "..."}, ...]}
    """
    job_list = []
    for job in jobs:
        if isinstance(job, tuple):
            name, url = job[0], job[1]
        elif isinstance(job, dict):
            name = job.get('name') or job.get('title', '')
            url = job.get('url', '')
        else:
            continue
        if name and url:
            job_list.append({"name": name, "url": url})
    return json.dumps({"jobs": job_list})

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
    URL = COMPANY_URLS.get("NOVARTIS", "https://www.novartis.com/careers/career-search?search_api_fulltext=data&country%5B0%5D=LOC_CH&field_job_posted_date=All&op=Submit&page=0")


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
            await browser.close()
            return jobs

    ## MAIN ##
    jobs = asyncio.run(main())
    return _jobs_to_json(jobs)

@tool
def get_AWS_jobs() -> str:
    """
    This tool function helps you get AWS current job list
    """
    URL = COMPANY_URLS.get("AWS", "https://www.amazon.jobs/content/en/locations/switzerland/zurich?category%5B%5D=Solutions+Architect")

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
        return jobs

    jobs = asyncio.run(list_jobs(URL))
    return _jobs_to_json(jobs)

@tool
def get_YPSOMED_jobs():
    """This tool function helps you get YPSOMED current job list"""
    URL = COMPANY_URLS.get("YPSOMED", "https://careers.ypsomed.com/ypsomed/en/professional/")

    async def get_ypsomed_jobs():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until='networkidle')
            
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
                return _jobs_to_json([])

            # Convert to standard format
            jobs = [(job.get('title', ''), job.get('link', '')) for job in jobs_data]
            return jobs

    jobs = asyncio.run(get_ypsomed_jobs())
    if isinstance(jobs, str):  # Error message
        return jobs
    return _jobs_to_json(jobs)

@tool
def get_VISIUM_jobs():
    """This tool function helps you get VISIUM current job list"""
    URL = COMPANY_URLS.get("VISIUM", "https://www.visium.com/join-us#open-positions")

    async def get_visium_jobs():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until='networkidle')
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
            seen = set()

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

                        if link and ('job' in link.lower() or 'career' in link.lower() or 'position' in link.lower()):
                            if link not in seen:
                                seen.add(link)
                                jobs.append((text, link))

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
                            if href not in seen:
                                seen.add(href)
                                jobs.append((text, href))

            return jobs[:30]

    jobs = asyncio.run(get_visium_jobs())
    return _jobs_to_json(jobs)

@tool
def get_ROCHE_jobs() -> str:
    """This tool function helps you get ROCHE current job list"""
    URL = COMPANY_URLS.get("ROCHE", "https://roche.wd3.myworkdayjobs.com/en-US/roche-ext?q=machine%20learning&locations=3543744a0e67010b8e1b9bd75b7637a4")
    
    async def get_roche_jobs(url: str):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            await page.goto(url, wait_until='domcontentloaded')
            await asyncio.sleep(5)
            
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(3)
            
            content = await page.content()
            await browser.close()
            
            soup = BeautifulSoup(content, 'html.parser')
            
            job_items = soup.find_all('li', {'data-automation-id': 'listItem'})
            
            if not job_items:
                job_items = soup.find_all('li', class_=lambda x: x and 'job' in x.lower())
            
            if not job_items:
                all_links = soup.find_all('a', href=True)
                job_links = [link for link in all_links if '/job/' in link.get('href', '')]
                
                jobs_list = []
                for idx, link in enumerate(job_links, 1):
                    job_title = link.get_text(strip=True)
                    job_url = link.get('href', '')
                    if not job_url.startswith('http'):
                        job_url = 'https://roche.wd3.myworkdayjobs.com' + job_url
                    
                    jobs_list.append({
                        'number': idx,
                        'title': job_title,
                        'url': job_url,
                        'location': 'N/A',
                        'posted_date': 'N/A',
                        'job_id': 'N/A'
                    })
            else:
                jobs_list = []
                for idx, job in enumerate(job_items, 1):
                    title_elem = job.find('a', {'data-automation-id': 'jobTitle'})
                    
                    if not title_elem:
                        title_elem = job.find('a', href=True)
                    
                    if title_elem:
                        job_title = title_elem.get_text(strip=True)
                        job_url = title_elem.get('href', '')
                        if not job_url.startswith('http'):
                            job_url = 'https://roche.wd3.myworkdayjobs.com' + job_url
                        
                        location_elem = job.find('dd', {'data-automation-id': 'location'})
                        location = location_elem.get_text(strip=True) if location_elem else "N/A"
                        
                        posted_elem = job.find('dd', {'data-automation-id': 'postedOn'})
                        posted_date = posted_elem.get_text(strip=True) if posted_elem else "N/A"
                        
                        job_id_elem = job.find('dd', {'data-automation-id': 'requisitionId'})
                        job_id = job_id_elem.get_text(strip=True) if job_id_elem else "N/A"
                        
                        jobs_list.append({
                            'number': idx,
                            'title': job_title,
                            'url': job_url,
                            'location': location,
                            'posted_date': posted_date,
                            'job_id': job_id
                        })
            
            if not jobs_list:
                return _jobs_to_json([])

            # Convert to standard format for _jobs_to_json
            jobs = [(job['title'], job['url']) for job in jobs_list]
            return jobs

    jobs = asyncio.run(get_roche_jobs(URL))
    if isinstance(jobs, str):  # Error or empty JSON
        return jobs
    return _jobs_to_json(jobs)

@tool
def get_CSL_jobs() -> str:
    """This tool function helps you get CSL current job list"""
    URL = COMPANY_URLS.get("CSL", "https://csl.wd1.myworkdayjobs.com/en-EN/CSL_External?locationCountry=187134fccb084a0ea9b4b95f23890dbe")

    async def get_csl_jobs():
        url = URL
        jobs_list = []
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            try:
                await page.goto(url, wait_until='domcontentloaded', timeout=60000)
                await asyncio.sleep(5)
                
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                
                job_links = soup.find_all('a', attrs={'data-automation-id': 'jobTitle'})
                
                if not job_links:
                    await asyncio.sleep(5)
                    content = await page.content()
                    soup = BeautifulSoup(content, 'html.parser')
                    job_links = soup.find_all('a', href=lambda x: x and '/job/' in x)
                
                for link in job_links:
                    try:
                        job_title = link.get_text(strip=True)
                        job_url = link.get('href', '')
                        
                        if job_url and not job_url.startswith('http'):
                            job_url = f"https://csl.wd1.myworkdayjobs.com{job_url}"
                        
                        parent = link.find_parent('li')
                        if parent:
                            location_elem = parent.find('dd', attrs={'data-automation-id': 'location'})
                            location = location_elem.get_text(strip=True) if location_elem else "N/A"
                            
                            job_id_elem = parent.find('dd', attrs={'data-automation-id': 'requisitionId'})
                            job_id = job_id_elem.get_text(strip=True) if job_id_elem else "N/A"
                            
                            posted_elem = parent.find('dd', attrs={'data-automation-id': 'postedOn'})
                            posted_date = posted_elem.get_text(strip=True) if posted_elem else "N/A"
                        else:
                            location = "N/A"
                            job_id = "N/A"
                            posted_date = "N/A"
                        
                        if job_title and job_url:
                            jobs_list.append({
                                'job_title': job_title,
                                'job_url': job_url,
                                'location': location,
                                'job_id': job_id,
                                'posted_date': posted_date
                            })
                    except Exception as e:
                        continue
                
            finally:
                await browser.close()

        if not jobs_list:
            return _jobs_to_json([])

        # Convert to standard format for _jobs_to_json
        jobs = [(job['job_title'], job['job_url']) for job in jobs_list]
        return jobs

    jobs = asyncio.run(get_csl_jobs())
    if isinstance(jobs, str):  # Error or empty JSON
        return jobs
    return _jobs_to_json(jobs)

@tool
def get_JJ_jobs() -> str:
    """This tool function helps you get J&J current job list"""
    URL = COMPANY_URLS.get("J&J", "https://www.careers.jnj.com/en/jobs/?search=&team=Data+Analytics+%26+Computational+Sciences&country=Switzerland&pagesize=20#results")

    async def get_jnj_jobs():
        url = URL
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()
            
            try:
                await page.goto(url, wait_until='networkidle', timeout=30000)
                await page.wait_for_timeout(5000)
                
                content = await page.content()
                soup = BeautifulSoup(content, 'html.parser')
                
                jobs_list = []
                
                job_links = soup.find_all('a', href=lambda x: x and '/job/' in x)
                
                if not job_links:
                    job_links = soup.find_all('a', class_=lambda x: x and 'job' in str(x).lower())
                
                seen_urls = set()
                
                for idx, link in enumerate(job_links, 1):
                    job_url = link.get('href', '')
                    job_title = link.get_text(strip=True)
                    
                    if job_url and job_title and job_url not in seen_urls:
                        if not job_url.startswith('http'):
                            job_url = f"https://www.careers.jnj.com{job_url}"
                        
                        seen_urls.add(job_url)
                        
                        parent = link.find_parent()
                        location = 'N/A'
                        if parent:
                            location_elem = parent.find(class_=lambda x: x and 'location' in str(x).lower())
                            if location_elem:
                                location = location_elem.get_text(strip=True)
                        
                        jobs_list.append({
                            'job_number': len(jobs_list) + 1,
                            'job_title': job_title,
                            'location': location,
                            'job_url': job_url
                        })
                
                await browser.close()

                if jobs_list:
                    # Convert to standard format for _jobs_to_json
                    jobs = [(job['job_title'], job['job_url']) for job in jobs_list]
                    return jobs
                else:
                    return []

            except Exception as e:
                await browser.close()
                return []

    jobs = asyncio.run(get_jnj_jobs())
    return _jobs_to_json(jobs)

@tool
def get_ISO_jobs() -> str:
    """This tool function helps you get ISO current job list"""
    URL = COMPANY_URLS.get("ISO", "https://job-boards.greenhouse.io/isomorphiclabs")

    def list_iso_jobs() -> str:
        async def _run() -> str:
            board_url = URL
            job_url_re = re.compile(r"^https://job-boards\.greenhouse\.io/isomorphiclabs/jobs/\d+")
    
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(board_url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(1500)
    
                html = await page.content()
                await browser.close()
    
            soup = BeautifulSoup(html, "html.parser")
    
            jobs = []
            for a in soup.select('a[href*="/isomorphiclabs/jobs/"]'):
                href = (a.get("href") or "").strip()
                if not href:
                    continue
                if href.startswith("/"):
                    href = "https://job-boards.greenhouse.io" + href
    
                if not job_url_re.match(href):
                    continue
    
                title = a.get_text(" ", strip=True)
                if not title or title.lower() == "apply":
                    continue
    
                jobs.append((title, href))
    
            # de-dupe while preserving order
            seen = set()
            unique_jobs = []
            for title, url in jobs:
                key = (title, url)
                if key in seen:
                    continue
                seen.add(key)
                unique_jobs.append((title, url))

            return unique_jobs

        return asyncio.run(_run())

    jobs = list_iso_jobs()
    return _jobs_to_json(jobs)

@tool
def get_MONTEROSA_jobs() -> str:
    """This tool function helps you get MONTEROSA current job list"""
    URL = COMPANY_URLS.get("MONTEROSA", "https://www.monterosatx.com/careers/")

    def list_monterosa_jobs() -> str:
        async def _run() -> str:
            careers_url = URL
    
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(careers_url, wait_until="domcontentloaded",timeout=60000)
                html = await page.content()
                await browser.close()
    
            soup = BeautifulSoup(html, "html.parser")
    
            jobs = []
            seen = set()
    
            for a in soup.select('a[href*="careers-monterosatx.icims.com/jobs/"]'):
                href = (a.get("href") or "").strip()
                if not href:
                    continue
    
                job_url = urljoin(careers_url, href)
                if job_url in seen:
                    continue
                seen.add(job_url)
    
                title = " ".join(a.get_text(" ", strip=True).split())
    
                if not title or title.lower() in {"more info", "apply", "careers"}:
                    container = a.find_parent(["div", "li", "article", "section"])
                    if container:
                        h = container.find(["h1", "h2", "h3", "h4"])
                        if h:
                            title = " ".join(h.get_text(" ", strip=True).split())
    
                if not title:
                    slug = job_url.rstrip("/").split("/")[-2]
                    title = slug.replace("-", " ").replace("%e2%80%93", "–").strip()
    
                jobs.append((title, job_url))

            return jobs

        return asyncio.run(_run())

    jobs = list_monterosa_jobs()
    return _jobs_to_json(jobs)

@tool
def get_IDORSIA_jobs() -> str:
    """This tool function helps you get IDORSIA current job list"""
    URL = COMPANY_URLS.get("IDORSIA", "https://careers.idorsia.com/search/?createNewAlert=false&q=&locationsearch=switzerland")

    def list_idorsia_jobs() -> str:
        async def _run() -> str:
            url = URL
    
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded")
    
                try:
                    await page.wait_for_selector('a[href*="/job/"]', timeout=20000)
                except Exception:
                    pass
    
                # Grab DOM after the JS has had a chance to render job links
                html = await page.content()
                await browser.close()
    
            soup = BeautifulSoup(html, "html.parser")
    
            # Prefer the expected selector, but fall back to any "/job/" anchors
            anchors = soup.select("a.jobTitle-link[href]") or soup.select('a[href*="/job/"]')
    
            jobs = []
            for a in anchors:
                href = (a.get("href") or "").strip()
                if "/job/" not in href:
                    continue
    
                title = a.get_text(" ", strip=True)
                if not title:
                    m = re.search(r"/job/([^/]+)/\d+/?", href)
                    if m:
                        title = m.group(1).replace("-", " ").strip()
                    else:
                        continue
    
                full_url = urljoin(url, href)
    
                date_posted = ""
                container = a.find_parent("tr") or a.find_parent("li") or a.find_parent("div")
                if container:
                    date_el = container.select_one(".jobDate")
                    if date_el:
                        date_posted = date_el.get_text(" ", strip=True)
    
                jobs.append((full_url, title, date_posted))
    
            # de-dup by URL, preserve order
            seen = set()
            unique_jobs = []
            for full_url, title, date_posted in jobs:
                if full_url in seen:
                    continue
                seen.add(full_url)
                unique_jobs.append((title, full_url))

            return unique_jobs

        return asyncio.run(_run())

    jobs = list_idorsia_jobs()
    return _jobs_to_json(jobs)

@tool
def get_MERCK_jobs() -> str:
    """This tool function helps you get MERCK current job list filtered for Switzerland positions"""
    # Use keywords=Switzerland to search for Swiss jobs (l= parameter doesn't work properly)
    URL = COMPANY_URLS.get("MERCK", "https://careers.merckgroup.com/global/en/search-results?keywords=Switzerland&s=1")

    def list_merck_jobs() -> str:
        async def _run() -> str:
            # Use URL with Switzerland keyword search
            url = URL if "Switzerland" in URL else "https://careers.merckgroup.com/global/en/search-results?keywords=Switzerland&s=1"

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="domcontentloaded")

                try:
                    await page.wait_for_selector('[data-ph-at-id="job-link"]', timeout=20000)
                except Exception:
                    pass

                await page.wait_for_timeout(5000)

                # Scroll multiple times to load all results
                for _ in range(5):
                    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    await page.wait_for_timeout(2000)

                html = await page.content()
                await browser.close()

            soup = BeautifulSoup(html, "html.parser")
            anchors = soup.select('a[data-ph-at-id="job-link"]')

            jobs = []
            for a in anchors:
                href = (a.get("href") or "").strip()
                if not href or href == "#":
                    continue

                title = a.get_text(" ", strip=True)
                if not title:
                    m = re.search(r"/job/\d+/([^?]+)", href)
                    if m:
                        title = m.group(1).replace("-", " ").strip()
                    else:
                        continue

                # Get location from job-info element
                location = ""
                parent = a.find_parent("li") or a.find_parent("div", class_=lambda x: x and "job" in str(x).lower())
                if parent:
                    # Try job-info first (contains location)
                    info_elem = parent.select_one('[data-ph-at-id="job-info"]')
                    if info_elem:
                        location = info_elem.get_text(" ", strip=True)
                    else:
                        # Fallback to job-location
                        loc_elem = parent.select_one('[data-ph-at-id="job-location"]')
                        if loc_elem:
                            location = loc_elem.get_text(" ", strip=True)

                # Filter for Switzerland only - include all Swiss cantons/cities
                swiss_locations = ['switzerland', 'zürich', 'zurich', 'basel', 'geneva', 'genève', 'bern', 'swiss', 'buchs', 'schaffhausen', 'zug', 'lausanne', 'lugano', 'winterthur', 'st. gallen', 'lucerne', 'luzern', 'visp', 'stein', 'vaud', 'aubonne', 'corsier', 'vevey', 'eysins', 'nyon']
                if not any(loc in location.lower() for loc in swiss_locations):
                    # Skip non-Swiss jobs
                    continue

                if href.startswith("/"):
                    full_url = urljoin("https://careers.merckgroup.com", href)
                elif href.startswith("http"):
                    full_url = href
                else:
                    full_url = urljoin(url, href)

                jobs.append((full_url, title))

            # De-duplicate by URL, preserve order
            seen = set()
            unique_jobs = []
            for full_url, title in jobs:
                if full_url in seen:
                    continue
                seen.add(full_url)
                unique_jobs.append((title, full_url))

            return unique_jobs

        return asyncio.run(_run())

    jobs = list_merck_jobs()
    return _jobs_to_json(jobs)

@tool
def get_HAYA_jobs() -> str:
    """This tool function helps you get HAYA Therapeutics current job list"""
    URL = COMPANY_URLS.get("HAYA", "https://www.hayatx.com/careers/")

    def list_haya_jobs() -> str:
        async def _run() -> str:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(URL, wait_until="networkidle")

                await page.wait_for_timeout(5000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

                html = await page.content()
                await browser.close()

            soup = BeautifulSoup(html, "html.parser")

            jobs = []
            seen = set()

            # Find job links - BambooHR and LinkedIn job postings
            for a in soup.select('a[href*="bamboohr.com/careers"], a[href*="linkedin.com/jobs"]'):
                href = (a.get("href") or "").strip()
                if not href or href in seen:
                    continue
                seen.add(href)

                # Get title from link text directly
                link_text = a.get_text(" ", strip=True)

                # Filter for Switzerland (Lausanne/CH) positions only
                if "Lausanne" not in link_text and "(CH)" not in link_text:
                    continue

                # Extract title from pattern: "[New] Location (XX) Title Location (XX) Details"
                # Pattern matches: location, then captures everything until next location
                match = re.search(
                    r'(?:New\s+)?Lausanne\s*\(CH\)\s+(.+?)\s+Lausanne\s*\(CH\)',
                    link_text
                )
                if match:
                    title = match.group(1).strip()
                else:
                    # Fallback: clean up the link text
                    title = link_text
                    title = re.sub(r'^New\s+', '', title)
                    title = re.sub(r'^Lausanne\s*\(CH\)\s*', '', title)
                    title = re.sub(r'\s+Lausanne\s*\(CH\).*$', '', title)

                if title and len(title) > 5:
                    jobs.append((title, href))

            return jobs

        return asyncio.run(_run())

    jobs = list_haya_jobs()
    return _jobs_to_json(jobs)

@tool
def get_TAKEDA_jobs() -> str:
    """This tool function helps you get TAKEDA current job list for Switzerland"""
    URL = COMPANY_URLS.get("TAKEDA", "https://www.takeda.com/careers/search-jobs/?country=Switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/job/"], a[href*="/jobs/"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if '/job/' in href or '/jobs/' in href:
                if href.startswith('/'):
                    href = 'https://www.takeda.com' + href
                if href in seen:
                    continue
                seen.add(href)

                title = a.get_text(strip=True)
                if title and len(title) > 5 and title.lower() not in ['apply', 'learn more', 'view']:
                    jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_SYNGENTA_jobs() -> str:
    """This tool function helps you get SYNGENTA current job list for Switzerland"""
    URL = COMPANY_URLS.get("SYNGENTA", "https://jobs.syngenta.com/?country=CH")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('[data-ph-at-id="job-link"], a[href*="/job/"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        # Try PhenomPeople selector first
        anchors = soup.select('a[data-ph-at-id="job-link"]')
        if not anchors:
            anchors = soup.find_all('a', href=lambda x: x and '/job/' in x)

        for a in anchors:
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://jobs.syngenta.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_LONZA_jobs() -> str:
    """This tool function helps you get LONZA current job list for Switzerland (via Workday)"""
    # Use Workday URL directly - Lonza's main site blocks headless browsers
    URL = "https://lonza.wd3.myworkdayjobs.com/Lonza_Careers?locationCountry=187134fccb084a0ea9b4b95f23890dbe"

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            await page.wait_for_timeout(5000)

            # Scroll to load more jobs
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        # Workday job links have data-automation-id="jobTitle" or /job/ in href
        job_links = soup.find_all('a', attrs={'data-automation-id': 'jobTitle'})
        if not job_links:
            job_links = soup.find_all('a', href=lambda x: x and '/job/' in x)

        for link in job_links:
            title = link.get_text(strip=True)
            href = link.get('href', '')

            if href and not href.startswith('http'):
                href = f"https://lonza.wd3.myworkdayjobs.com{href}"

            if href in seen:
                continue
            seen.add(href)

            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_BIOGEN_jobs() -> str:
    """This tool function helps you get BIOGEN current job list for Switzerland (Workday)"""
    URL = COMPANY_URLS.get("BIOGEN", "https://biibhr.wd3.myworkdayjobs.com/en-US/external?locationCountry=187134fccb084a0ea9b4b95f23890dbe")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            await page.wait_for_timeout(5000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        # Workday pattern
        for a in soup.find_all('a', attrs={'data-automation-id': 'jobTitle'}):
            href = a.get('href', '')
            if href and not href.startswith('http'):
                href = 'https://biibhr.wd3.myworkdayjobs.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title:
                jobs.append((title, href))

        # Fallback
        if not jobs:
            for a in soup.find_all('a', href=lambda x: x and '/job/' in x):
                href = a.get('href', '')
                if not href.startswith('http'):
                    href = 'https://biibhr.wd3.myworkdayjobs.com' + href
                if href in seen:
                    continue
                seen.add(href)
                title = a.get_text(strip=True)
                if title and len(title) > 5:
                    jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_SANDOZ_jobs() -> str:
    """This tool function helps you get SANDOZ current job list for Switzerland"""
    URL = COMPANY_URLS.get("SANDOZ", "https://www.sandoz.com/careers/job-search/?field_job_country=LOC_CH")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(5000)

            # Scroll to load more jobs
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        # Look for job-details links (pattern: /careers/career-search/job-details/REQ-XXXXX)
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if '/career-search/job-details/' in href or '/job-details/' in href:
                if href.startswith('/'):
                    href = 'https://www.sandoz.com' + href
                if href in seen:
                    continue
                seen.add(href)

                # Get title from link text or parent element
                title = a.get_text(strip=True)
                if not title or len(title) < 5:
                    parent = a.find_parent(['div', 'li', 'article'])
                    if parent:
                        h = parent.find(['h2', 'h3', 'h4', 'strong'])
                        if h:
                            title = h.get_text(strip=True)

                if title and len(title) > 5:
                    jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_ABBVIE_jobs() -> str:
    """This tool function helps you get ABBVIE current job list for Switzerland"""
    URL = COMPANY_URLS.get("ABBVIE", "https://careers.abbvie.com/en/jobs?ln=Z%C3%BCrich%2C+Switzerland&lr=200")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/job/"], [data-ph-at-id="job-link"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        anchors = soup.select('a[data-ph-at-id="job-link"]')
        if not anchors:
            anchors = soup.find_all('a', href=lambda x: x and '/job/' in x)

        for a in anchors:
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://careers.abbvie.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_SANOFI_jobs() -> str:
    """This tool function helps you get SANOFI current job list for Switzerland"""
    URL = COMPANY_URLS.get("SANOFI", "https://jobs.sanofi.com/en/search-jobs/Switzerland/2649/2/2658434/47x00016/8x01427/50/2")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/job/"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=lambda x: x and '/job/' in x):
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://jobs.sanofi.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5 and title.lower() not in ['apply', 'view job']:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_BAYER_jobs() -> str:
    """This tool function helps you get BAYER current job list for Switzerland"""
    URL = COMPANY_URLS.get("BAYER", "https://career.bayer.com/en/job-search?country=Switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/job/"], [data-ph-at-id="job-link"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        anchors = soup.select('a[data-ph-at-id="job-link"]')
        if not anchors:
            anchors = soup.find_all('a', href=lambda x: x and '/job/' in x)

        for a in anchors:
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://talent.bayer.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_AZ_jobs() -> str:
    """This tool function helps you get AstraZeneca current job list for Switzerland"""
    URL = COMPANY_URLS.get("AZ", "https://careers.astrazeneca.com/search-jobs/Switzerland/7684/2/2658434/47x00016/8x01427/100/2")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/job/"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=lambda x: x and '/job/' in x):
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://careers.astrazeneca.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5 and title.lower() not in ['apply', 'view job']:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_BMS_jobs() -> str:
    """This tool function helps you get Bristol-Myers Squibb current job list for Switzerland"""
    URL = COMPANY_URLS.get("BMS", "https://jobs.bms.com/careers?location=switzerland&domain=bms.com")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/job/"], [data-ph-at-id="job-link"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        anchors = soup.select('a[data-ph-at-id="job-link"]')
        if not anchors:
            anchors = soup.find_all('a', href=lambda x: x and '/job/' in x)

        for a in anchors:
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://jobs.bms.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_BASILEA_jobs() -> str:
    """This tool function helps you get BASILEA current job list (Personio-based)"""
    URL = COMPANY_URLS.get("BASILEA", "https://basilea.jobs.personio.de/")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/job/"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=lambda x: x and '/job/' in x):
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://basilea.jobs.personio.de' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_DEBIOPHARM_jobs() -> str:
    """This tool function helps you get DEBIOPHARM current job list"""
    URL = COMPANY_URLS.get("DEBIOPHARM", "https://www.debiopharm.com/careers/#latest-open-positions")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(3000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        # Look for job links - they may use various patterns
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.get_text(strip=True)

            # Check if it looks like a job posting
            if any(kw in href.lower() for kw in ['job', 'career', 'position', 'apply', 'bamboohr', 'greenhouse', 'lever']):
                if href.startswith('/'):
                    href = 'https://www.debiopharm.com' + href
                if href in seen:
                    continue
                seen.add(href)

                if text and len(text) > 5 and text.lower() not in ['apply', 'learn more', 'careers']:
                    jobs.append((text, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_FERRING_jobs() -> str:
    """This tool function helps you get FERRING current job list for Switzerland (Workday)"""
    URL = COMPANY_URLS.get("FERRING", "https://ferring.wd3.myworkdayjobs.com/Ferring?locations=dd8155745d350150f89fb94e4649a7eb")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            await page.wait_for_timeout(5000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        # Workday pattern
        for a in soup.find_all('a', attrs={'data-automation-id': 'jobTitle'}):
            href = a.get('href', '')
            if href and not href.startswith('http'):
                href = 'https://ferring.wd3.myworkdayjobs.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title:
                jobs.append((title, href))

        # Fallback
        if not jobs:
            for a in soup.find_all('a', href=lambda x: x and '/job/' in x):
                href = a.get('href', '')
                if not href.startswith('http'):
                    href = 'https://ferring.wd3.myworkdayjobs.com' + href
                if href in seen:
                    continue
                seen.add(href)
                title = a.get_text(strip=True)
                if title and len(title) > 5:
                    jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_UCB_jobs() -> str:
    """This tool function helps you get UCB current job list - filtering for Switzerland"""
    URL = COMPANY_URLS.get("UCB", "https://careers.ucb.com/global/en/search-results?s=1")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('[data-ph-at-id="job-link"], a[href*="/job/"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        anchors = soup.select('a[data-ph-at-id="job-link"]')
        if not anchors:
            anchors = soup.find_all('a', href=lambda x: x and '/job/' in x)

        for a in anchors:
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://careers.ucb.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)

            # Check for Switzerland in location
            parent = a.find_parent(['li', 'div', 'tr'])
            location = ""
            if parent:
                loc_elem = parent.select_one('[data-ph-at-id="job-location"]')
                if loc_elem:
                    location = loc_elem.get_text(strip=True).lower()

            # Filter for Switzerland
            if 'switzerland' in location or 'zurich' in location or 'basel' in location or 'bern' in location:
                if title and len(title) > 5:
                    jobs.append((title, href))
            elif not location:  # If no location found, include it anyway
                if title and len(title) > 5:
                    jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_RIDGELINE_jobs() -> str:
    """This tool function helps you get RIDGELINE current job list (Greenhouse-based)"""
    URL = COMPANY_URLS.get("RIDGELINE", "https://careers.ridgelinediscovery.com/jobs")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        # Greenhouse pattern
        for a in soup.find_all('a', href=lambda x: x and '/jobs/' in x):
            href = a.get('href', '').strip()
            if not href or 'ridgelinediscovery.com/jobs' == href.rstrip('/'):
                continue
            if href.startswith('/'):
                href = 'https://careers.ridgelinediscovery.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5 and title.lower() not in ['apply', 'jobs']:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_INTERAX_jobs() -> str:
    """This tool function helps you get INTERAX current job list"""
    URL = COMPANY_URLS.get("INTERAX", "https://interaxbiotech.com/interax-homepage/careers/")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        # Look for PDF job listings (InterAx posts jobs as PDF downloads)
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.get_text(strip=True)

            # Check for PDF job postings in uploads folder
            if '/wp-content/uploads/' in href and href.endswith('.pdf'):
                if href in seen:
                    continue
                seen.add(href)
                if text and len(text) > 5:
                    jobs.append((text, href))
                continue

            # Also check for standard job board links
            if any(kw in href.lower() for kw in ['job', 'position', 'apply', 'bamboohr', 'greenhouse', 'lever']):
                if href.startswith('/'):
                    href = 'https://interaxbiotech.com' + href
                if href in seen:
                    continue
                seen.add(href)

                if text and len(text) > 5 and text.lower() not in ['apply', 'learn more', 'careers']:
                    jobs.append((text, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_PHILOCHEM_jobs() -> str:
    """This tool function helps you get PHILOCHEM current job list"""
    URL = COMPANY_URLS.get("PHILOCHEM", "https://www.philochem.ch/work-with-us/careers/")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.get_text(strip=True)

            if any(kw in href.lower() or kw in text.lower() for kw in ['job', 'position', 'scientist', 'engineer', 'manager', 'apply']):
                if href.startswith('/'):
                    href = 'https://www.philochem.ch' + href
                if href in seen or href == URL:
                    continue
                seen.add(href)

                if text and len(text) > 5 and text.lower() not in ['apply', 'learn more', 'careers', 'work with us']:
                    jobs.append((text, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_SPIROCHEM_jobs() -> str:
    """This tool function helps you get SPIROCHEM current job list"""
    URL = COMPANY_URLS.get("SPIROCHEM", "https://spirochem.com/careers")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.get_text(strip=True)

            if any(kw in href.lower() or kw in text.lower() for kw in ['job', 'position', 'scientist', 'chemist', 'apply']):
                if href.startswith('/'):
                    href = 'https://spirochem.com' + href
                if href in seen or href == URL:
                    continue
                seen.add(href)

                if text and len(text) > 5 and text.lower() not in ['apply', 'learn more', 'careers']:
                    jobs.append((text, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_NBE_jobs() -> str:
    """This tool function helps you get NBE Therapeutics current job list"""
    URL = COMPANY_URLS.get("NBE", "https://nbe-therapeutics.com/employment/vacancies/")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.get_text(strip=True)

            if '/employment/' in href or '/vacancies/' in href or '/job/' in href:
                if href.startswith('/'):
                    href = 'https://nbe-therapeutics.com' + href
                if href in seen or href == URL:
                    continue
                seen.add(href)

                if text and len(text) > 5 and text.lower() not in ['apply', 'vacancies', 'employment']:
                    jobs.append((text, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_CRADLE_jobs() -> str:
    """This tool function helps you get CRADLE current job list"""
    URL = COMPANY_URLS.get("CRADLE", "https://www.cradle.bio/careers#careers")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(3000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(2000)

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        # Look for Lever or Greenhouse links (common for startups)
        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.get_text(strip=True)

            if any(kw in href.lower() for kw in ['lever.co', 'greenhouse.io', 'jobs.', 'careers.', '/job/', '/jobs/']):
                if href in seen:
                    continue
                seen.add(href)

                if text and len(text) > 5 and text.lower() not in ['apply', 'learn more', 'careers']:
                    jobs.append((text, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_LEADXPRO_jobs() -> str:
    """This tool function helps you get LEADXPRO current job list"""
    URL = COMPANY_URLS.get("LEADXPRO", "https://careers.leadxpro.com/")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.get_text(strip=True)

            if '/job/' in href or '/jobs/' in href or 'apply' in href.lower():
                if href.startswith('/'):
                    href = 'https://careers.leadxpro.com' + href
                if href in seen:
                    continue
                seen.add(href)

                if text and len(text) > 5 and text.lower() not in ['apply now', 'careers']:
                    jobs.append((text, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_BRIGHTPEAK_jobs() -> str:
    """This tool function helps you get BRIGHTPEAK current job list"""
    URL = COMPANY_URLS.get("BRIGHTPEAK", "https://brightpeaktx.com/careers/")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.get_text(strip=True)

            if any(kw in href.lower() for kw in ['greenhouse', 'lever', 'job', 'apply', 'bamboohr']):
                if href in seen:
                    continue
                seen.add(href)

                if text and len(text) > 5 and text.lower() not in ['apply', 'learn more', 'careers']:
                    jobs.append((text, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_SOPHIA_jobs() -> str:
    """This tool function helps you get SOPHiA GENETICS current job list for Switzerland"""
    URL = COMPANY_URLS.get("SOPHIA", "https://careers.sophiagenetics.com/jobs/search?query=switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/jobs/"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=lambda x: x and '/jobs/' in x):
            href = a.get('href', '').strip()
            if not href or '/jobs/search' in href:
                continue
            if href.startswith('/'):
                href = 'https://careers.sophiagenetics.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_DANAHER_jobs() -> str:
    """This tool function helps you get DANAHER current job list for Switzerland"""
    # Use Switzerland location filter in URL
    URL = "https://jobs.danaher.com/global/en/search-results?l=Switzerland&s=1"

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(5000)

            # Scroll to load more jobs
            for _ in range(2):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        # Look for job links
        for a in soup.find_all('a', href=lambda x: x and '/job/' in x):
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://jobs.danaher.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_DSM_jobs() -> str:
    """This tool function helps you get DSM-Firmenich current job list for Switzerland"""
    URL = COMPANY_URLS.get("DSM", "https://jobs.dsm-firmenich.com/careers?location=Switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('[data-ph-at-id="job-link"], a[href*="/job/"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        anchors = soup.select('a[data-ph-at-id="job-link"]')
        if not anchors:
            anchors = soup.find_all('a', href=lambda x: x and '/job/' in x)

        for a in anchors:
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://jobs.dsm-firmenich.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_TETRASCIENCE_jobs() -> str:
    """This tool function helps you get TETRASCIENCE current job list (Workable)"""
    URL = COMPANY_URLS.get("TETRASCIENCE", "https://apply.workable.com/tetrascience/#jobs")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(5000)

            # Scroll to load jobs
            for _ in range(2):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        # Workable pattern - find job links
        for a in soup.find_all('a', href=lambda x: x and '/j/' in x):
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://apply.workable.com' + href
            if href in seen:
                continue
            seen.add(href)

            # Get title from link text or parent element
            title = a.get_text(strip=True)
            if not title or len(title) < 5:
                # Try to get title from parent container
                parent = a.find_parent(['li', 'div', 'article'])
                if parent:
                    # Look for heading or strong text
                    h = parent.find(['h2', 'h3', 'h4', 'strong', 'span'])
                    if h:
                        title = h.get_text(strip=True)
                    else:
                        # Get first significant text
                        title = parent.get_text(strip=True)[:100]

            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_DEEPMIND_jobs() -> str:
    """This tool function helps you get DEEPMIND current job list - filtering for Switzerland/Zurich"""
    URL = COMPANY_URLS.get("DEEPMIND", "https://deepmind.google/careers/")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(3000)
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if '/careers/' in href and href != URL:
                if href.startswith('/'):
                    href = 'https://deepmind.google' + href
                if href in seen:
                    continue
                seen.add(href)

                # Check for Zurich/Switzerland
                parent = a.find_parent(['div', 'li', 'article'])
                text = parent.get_text().lower() if parent else ''

                if 'zurich' in text or 'zürich' in text or 'switzerland' in text:
                    title = a.get_text(strip=True)
                    if title and len(title) > 5:
                        jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_FMI_jobs() -> str:
    """This tool function helps you get FMI (Friedrich Miescher Institute) current job list"""
    URL = COMPANY_URLS.get("FMI", "https://www.fmi.ch/education-careers/positions/")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.get_text(strip=True)

            if '/positions/' in href or '/job' in href.lower():
                if href.startswith('/'):
                    href = 'https://www.fmi.ch' + href
                if href in seen or href == URL:
                    continue
                seen.add(href)

                if text and len(text) > 5 and text.lower() not in ['positions', 'careers']:
                    jobs.append((text, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_HELSINN_jobs() -> str:
    """This tool function helps you get HELSINN current job list"""
    URL = COMPANY_URLS.get("HELSINN", "https://www.e-lavoro.ch/node/76")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            text = a.get_text(strip=True)

            if '/node/' in href and href != URL:
                if href.startswith('/'):
                    href = 'https://www.e-lavoro.ch' + href
                if href in seen:
                    continue
                seen.add(href)

                if text and len(text) > 5:
                    jobs.append((text, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_GIVAUDAN_jobs() -> str:
    """This tool function helps you get GIVAUDAN current job list for Switzerland"""
    URL = COMPANY_URLS.get("GIVAUDAN", "https://jobs.givaudan.com/search/?q=switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/job/"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=lambda x: x and '/job/' in x):
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://jobs.givaudan.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_CLARIANT_jobs() -> str:
    """This tool function helps you get CLARIANT current job list for Switzerland"""
    URL = COMPANY_URLS.get("CLARIANT", "https://careers.clariant.com/search/?q=switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/job/"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=lambda x: x and '/job/' in x):
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://careers.clariant.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_CERTARA_jobs() -> str:
    """This tool function helps you get CERTARA current job list for Switzerland"""
    URL = COMPANY_URLS.get("CERTARA", "https://careers.certara.com/jobs?location=Switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/jobs/"]', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=lambda x: x and '/jobs/' in x):
            href = a.get('href', '').strip()
            if not href or href.endswith('/jobs/') or href.endswith('/jobs'):
                continue
            if href.startswith('/'):
                href = 'https://careers.certara.com' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_BIOTECHJOBS_jobs() -> str:
    """This tool function helps you get Swiss Biotech job board listings"""
    URL = COMPANY_URLS.get("BIOTECHJOBS", "https://www.swissbiotech.org/jobs/?type=job&search_location=Switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)

            try:
                await page.wait_for_selector('a[href*="/job/"], .job-listing', timeout=15000)
            except:
                pass

            await page.wait_for_timeout(3000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=lambda x: x and '/job/' in x):
            href = a.get('href', '').strip()
            if not href:
                continue
            if href.startswith('/'):
                href = 'https://www.swissbiotech.org' + href
            if href in seen:
                continue
            seen.add(href)

            title = a.get_text(strip=True)
            if title and len(title) > 5:
                jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_GOOGLE_jobs() -> str:
    """This tool function helps you get GOOGLE current job list for Zurich, Switzerland"""
    URL = COMPANY_URLS.get("GOOGLE", "https://www.google.com/about/careers/applications/jobs/results/?location=Zurich%2C%20Switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(5000)
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if '/jobs/results/' in href and href != URL:
                if href.startswith('/'):
                    href = 'https://www.google.com' + href
                if href in seen:
                    continue
                seen.add(href)

                title = a.get_text(strip=True)
                if title and len(title) > 5 and title.lower() not in ['apply', 'learn more']:
                    jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_IBM_jobs() -> str:
    """This tool function helps you get IBM current job list for Switzerland"""
    URL = COMPANY_URLS.get("IBM", "https://www.ibm.com/careers/search?field_keyword_05%5B0%5D=Switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(5000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if '/job/' in href or 'careers' in href and 'job' in href.lower():
                if href.startswith('/'):
                    href = 'https://www.ibm.com' + href
                if href in seen or href == URL:
                    continue
                seen.add(href)

                title = a.get_text(strip=True)
                if title and len(title) > 5 and title.lower() not in ['apply', 'careers', 'search']:
                    jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_APPLE_jobs() -> str:
    """This tool function helps you get APPLE current job list for Switzerland (ML/AI teams)"""
    URL = COMPANY_URLS.get("APPLE", "https://jobs.apple.com/en-us/search?location=switzerland-CHEC")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(5000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if '/details/' in href or '/job/' in href:
                if href.startswith('/'):
                    href = 'https://jobs.apple.com' + href
                if href in seen:
                    continue
                seen.add(href)

                title = a.get_text(strip=True)
                if title and len(title) > 5 and title.lower() not in ['apply', 'learn more']:
                    jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_MICROSOFT_jobs() -> str:
    """This tool function helps you get MICROSOFT current job list for Switzerland"""
    URL = COMPANY_URLS.get("MICROSOFT", "https://careers.microsoft.com/v2/global/en/search?l=en_us&pg=1&pgSz=20&o=Relevance&flt=true&loc=Switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(5000)
            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if '/job/' in href or '/jobs/' in href:
                if href.startswith('/'):
                    href = 'https://careers.microsoft.com' + href
                if href in seen:
                    continue
                seen.add(href)

                title = a.get_text(strip=True)
                if title and len(title) > 5 and title.lower() not in ['apply', 'learn more', 'search']:
                    jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)

@tool
def get_META_jobs() -> str:
    """This tool function helps you get META current job list for Switzerland (AI teams)"""
    URL = COMPANY_URLS.get("META", "https://www.metacareers.com/jobs?q=switzerland")

    async def _run():
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(URL, wait_until="networkidle", timeout=60000)

            await page.wait_for_timeout(5000)
            for _ in range(3):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

            html = await page.content()
            await browser.close()

        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        seen = set()

        for a in soup.find_all('a', href=True):
            href = a.get('href', '')
            if '/jobs/' in href and 'jobsearch' not in href:
                if href.startswith('/'):
                    href = 'https://www.metacareers.com' + href
                if href in seen:
                    continue
                seen.add(href)

                title = a.get_text(strip=True)
                if title and len(title) > 5 and title.lower() not in ['apply', 'view job']:
                    jobs.append((title, href))

        return jobs

    jobs = asyncio.run(_run())
    return _jobs_to_json(jobs)
