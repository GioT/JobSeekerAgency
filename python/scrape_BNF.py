import sys
import os
import time

# Get absolute paths based on script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)  # Parent of python/

# Add project root and keys to path
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'keys'))
sys.path.append('../keys')

# Change working directory to project root (for relative file paths like ./output/)
os.chdir(PROJECT_ROOT)

import json
import re
import pandas as pd
from playwright.sync_api import sync_playwright

## Custom scripts:
import Constants as C

os.environ['OPENAI_API_KEY'] = C.OPENAI_API_KEY

# BNF Portal URL
BNF_LOGIN_URL = "https://bnf.tocco.ch/en/Project-Database"
BNF_BASE_URL = "https://bnf.tocco.ch"

BATCH_SIZE_TRANSLATE = 50  # Larger batches for translation (shorter messages)
BATCH_SIZE_FLAG = 20  # Smaller batches for flagging (longer messages)
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds
BATCH_DELAY = 1  # seconds between batches to avoid rate limiting


def call_openai_direct(messages: list[dict], max_retries: int = MAX_RETRIES) -> str | None:
    """Call OpenAI API directly with explicit timeout."""
    from openai import OpenAI
    import httpx

    # Create client with explicit timeout
    client = OpenAI(
        api_key=os.environ['OPENAI_API_KEY'],
        timeout=httpx.Timeout(60.0, connect=10.0)
    )

    for attempt in range(max_retries):
        try:
            # print(f"      Calling OpenAI API (attempt {attempt + 1}/{max_retries})...")
            response = client.chat.completions.create(
                model='gpt-5.2-2025-12-11', # use latest available model
                messages=messages,
                temperature=0)
            # print(f"      Got response!")
            return response.choices[0].message.content
        except Exception as e:
            print(f"      Error on attempt {attempt + 1}/{max_retries}: {type(e).__name__}: {e}")

        if attempt < max_retries - 1:
            delay = RETRY_DELAY * (attempt + 1)
            print(f"      Retrying in {delay}s...")
            time.sleep(delay)

    return None


def translate_job_names(jobs: list[dict]) -> list[dict]:
    """Translate job names to English using LLM."""
    print("\n>> Translating job names to English...")

    # Process in batches
    for i in range(0, len(jobs), BATCH_SIZE_TRANSLATE):
        batch = jobs[i:i + BATCH_SIZE_TRANSLATE]
        batch_num = i // BATCH_SIZE_TRANSLATE + 1
        total_batches = (len(jobs) + BATCH_SIZE_TRANSLATE - 1) // BATCH_SIZE_TRANSLATE
        print(f"   Processing batch {batch_num}/{total_batches}...")

        # Create list of names to translate
        names_to_translate = [job['name'] for job in batch]

        messages = [
            {"role": "system", "content": """You are a translator. Translate job/project titles to English.
Return ONLY a JSON array of translated strings, in the same order as the input.
Keep technical terms and proper nouns as-is. If already in English, return as-is.
Example input: ["Analyse du microbiote humain", "AI Consulting Engineer"]
Example output: ["Human microbiome analysis", "AI Consulting Engineer"]"""},
            {"role": "user", "content": json.dumps(names_to_translate, ensure_ascii=False)}
        ]

        content = call_openai_direct(messages)

        if content:
            try:
                translations = json.loads(content)
                # Update job names with translations
                for j, translation in enumerate(translations):
                    if j < len(batch):
                        batch[j]['name_en'] = translation
            except json.JSONDecodeError as e:
                print(f"   JSON parse error in batch {batch_num}: {e}")
                for job in batch:
                    job['name_en'] = job['name']
        else:
            print(f"   Failed to get translations for batch {batch_num}, using original names")
            for job in batch:
                job['name_en'] = job['name']

        # Delay between batches to avoid rate limiting
        if i + BATCH_SIZE_TRANSLATE < len(jobs):
            time.sleep(BATCH_DELAY)

    return jobs


def flag_relevant_jobs(jobs: list[dict]) -> list[dict]:
    """Flag jobs as relevant (1) or not (0) based on ML/AI/Data Science/Cheminformatics/CADD/Comp Chem."""
    print("\n>> Flagging relevant jobs...")

    # Process in smaller batches (flagging sends more data per job)
    for i in range(0, len(jobs), BATCH_SIZE_FLAG):
        batch = jobs[i:i + BATCH_SIZE_FLAG]
        batch_num = i // BATCH_SIZE_FLAG + 1
        total_batches = (len(jobs) + BATCH_SIZE_FLAG - 1) // BATCH_SIZE_FLAG
        print(f"   Processing batch {batch_num}/{total_batches}...")

        # Create list of job info for relevance check (just name for smaller payload)
        job_names = [job.get('name_en', job['name']) for job in batch]

        messages = [
            {"role": "system", "content": """You are a job classifier. For each job title, return 1 if relevant to:
- Machine Learning / AI / Deep Learning
- Data Science / Data Analysis
- Cheminformatics
- Computational Assisted Drug Discovery (CADD)
- Computational Chemistry / Molecular Modeling

Return ONLY a JSON array of 1s and 0s. Example: [1, 0, 1, 0, 1]"""},
            {"role": "user", "content": json.dumps(job_names, ensure_ascii=False)}
        ]

        content = call_openai_direct(messages)

        if content:
            try:
                # Parse the response - handle potential formatting issues
                content = content.strip()
                if content.startswith('['):
                    flags = json.loads(content)
                else:
                    # Try to extract array from response
                    match = re.search(r'\[[\d,\s]+\]', content)
                    if match:
                        flags = json.loads(match.group())
                    else:
                        flags = [0] * len(batch)

                # Update jobs with relevance flags
                for j, flag in enumerate(flags):
                    if j < len(batch):
                        batch[j]['relevant'] = int(flag)
            except json.JSONDecodeError as e:
                print(f"   JSON parse error in batch {batch_num}: {e}")
                for job in batch:
                    job['relevant'] = 0
        else:
            print(f"   Failed to get flags for batch {batch_num}, marking as not relevant")
            for job in batch:
                job['relevant'] = 0

        # Delay between batches to avoid rate limiting
        if i + BATCH_SIZE_FLAG < len(jobs):
            time.sleep(BATCH_DELAY)

    return jobs


def scrape_bnf_jobs() -> list[dict]:
    """
    Login to BNF portal and scrape job listings from the Project Database.
    Returns list of dicts with 'name' and 'url' keys.
    """
    jobs = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        try:
            # Navigate to the Project Database (will trigger 401 auth)
            print(">> Navigating to BNF portal...")

            response = page.goto(BNF_LOGIN_URL, wait_until='domcontentloaded', timeout=60000)
            print(f"   Response status: {response.status if response else 'None'}")
            page.wait_for_timeout(3000)

            # Check current URL and page title
            current_url = page.url
            title = page.title()
            print(f"   Current URL: {current_url}")
            print(f"   Page title: {title}")

            # Look for login form and fill credentials
            print(">> Attempting login...")

            # BNF uses name="user" for username and name="password" for password
            print("   Filling login form...")
            page.fill('input[name="user"]', C.BNF_EMAIL)
            print("   Filled username: [redacted]")
            page.fill('input[name="password"]', C.BNF_PASSWORD)
            print("   Filled password")

            # Click submit/login button
            try:
                submit_btn = page.locator('button[type="submit"], input[type="submit"]').first
                if submit_btn.count() > 0:
                    submit_btn.click()
                    print("   Clicked submit button")
                else:
                    page.press('input[name="password"]', 'Enter')
                    print("   Pressed Enter to submit")
            except Exception as e:
                print(f"   Submit error: {e}")
                page.press('input[name="password"]', 'Enter')

            # Wait for navigation after login
            print("   Waiting for login to complete...")
            page.wait_for_timeout(5000)
            try:
                page.wait_for_load_state('domcontentloaded', timeout=15000)
            except:
                pass

            # Check if login was successful
            current_url = page.url
            new_title = page.title()
            print(f"   Current URL after login: {current_url}")
            print(f"   Page title after login: {new_title}")

            # Navigate to Project Database if not already there
            if 'Project-Database' not in current_url or 'Login' in new_title:
                print("   Navigating to Project Database...")
                try:
                    page.goto(BNF_LOGIN_URL, wait_until='domcontentloaded', timeout=30000)
                    page.wait_for_timeout(3000)
                except:
                    pass

            # Now scrape the job listings from the ExtJS grid
            print(">> Scraping job listings...")

            # Wait for grid data to load
            print("   Waiting for grid to load...")
            page.wait_for_timeout(3000)

            # Wait for grid rows to appear
            try:
                page.wait_for_selector('.x-grid3-row', timeout=10000)
                print("   Grid loaded successfully")
            except:
                print("   Warning: Grid selector timeout, continuing anyway...")

            total_pages = 1
            current_page = 1

            # Try to get total pages from pagination
            try:
                page_info = page.locator('#ext-comp-1037').inner_text()
                # Format is "of 23"
                if 'of' in page_info:
                    total_pages = int(page_info.replace('of', '').strip())
                    print(f"   Total pages: {total_pages}")
            except:
                pass

            # Scrape all pages
            while current_page <= total_pages:
                print(f"   Scraping page {current_page}/{total_pages}...")

                # Get all rows on current page
                rows = page.locator('.x-grid3-row').all()

                for row in rows:
                    try:
                        # Extract project title (column 0)
                        title_cell = row.locator('.x-grid3-col-0')
                        title = title_cell.inner_text()
                        title = title.strip() if title else ''

                        # Extract subject area (column 1)
                        subject_cell = row.locator('.x-grid3-col-1')
                        subject = subject_cell.inner_text()
                        subject = subject.strip() if subject else ''

                        # Extract city (column 2)
                        city_cell = row.locator('.x-grid3-col-2')
                        city = city_cell.inner_text()
                        city = city.strip() if city else ''

                        if title:
                            # BNF doesn't have direct URLs for individual projects
                            jobs.append({
                                'name': title,
                                'subject': subject,
                                'city': city,
                                'url': BNF_LOGIN_URL
                            })
                    except Exception as e:
                        continue

                # Go to next page if not on last page
                if current_page < total_pages:
                    try:
                        # Click next page button
                        next_btn = page.locator('.x-tbar-page-next').first
                        if next_btn.count() > 0:
                            next_btn.click()
                            page.wait_for_timeout(2000)
                            # Wait for new data to load
                            page.wait_for_selector('.x-grid3-row', timeout=10000)
                    except Exception as e:
                        print(f"   Error navigating to next page: {e}")
                        break

                current_page += 1

            print(f"   Total projects found: {len(jobs)}")

        except Exception as e:
            print(f"   Error: {e}")
        finally:
            browser.close()

    return jobs


def process_bnf_jobs(skip_scrape: bool = False, skip_translate: bool = False) -> list[dict]:
    """
    Scrape, translate, and flag BNF jobs.

    Args:
        skip_scrape: If True, load from intermediate CSV instead of scraping
        skip_translate: If True, skip translation (assumes translations exist in intermediate file)
    """
    intermediate_file = './output/bnf_projects_intermediate.csv'

    if skip_scrape:
        # Load from intermediate file
        print(f">> Loading from intermediate file: {intermediate_file}")
        try:
            df = pd.read_csv(intermediate_file)
            jobs = df.to_dict('records')
            print(f"   Loaded {len(jobs)} jobs from intermediate file")
        except FileNotFoundError:
            print(f"   ERROR: Intermediate file not found. Run without skip_scrape first.")
            return []
    else:
        # Step 1: Scrape jobs
        jobs = scrape_bnf_jobs()
        if not jobs:
            return []

    # Step 2: Translate job names to English (if not skipping)
    if not skip_translate:
        jobs = translate_job_names(jobs)

        # Save intermediate results after translation
        print(f"\n>> Saving intermediate results to {intermediate_file}")
        df_intermediate = pd.DataFrame(jobs)
        df_intermediate.to_csv(intermediate_file, index=False)
        print(f"   Saved {len(jobs)} jobs with translations")

    # Step 3: Flag relevant jobs
    jobs = flag_relevant_jobs(jobs)

    return jobs


def get_bnf_jobs_json() -> str:
    """Run the scraper and return JSON string."""
    jobs = scrape_bnf_jobs()
    return json.dumps({"jobs": jobs}, indent=2)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="BNF Job Scraper")
    parser.add_argument('--resume', action='store_true',
                        help='Resume from intermediate file (skip scraping and translation)')
    parser.add_argument('--skip-scrape', action='store_true',
                        help='Skip scraping, load from intermediate file')
    parser.add_argument('--skip-translate', action='store_true',
                        help='Skip translation step')
    args = parser.parse_args()

    print("=" * 50)
    print("BNF Job Scraper")
    print("=" * 50)

    # Handle --resume as shortcut for --skip-scrape --skip-translate
    skip_scrape = args.skip_scrape or args.resume
    skip_translate = args.skip_translate or args.resume

    if skip_scrape:
        print(">> Resuming from intermediate file (skipping scrape)")
    if skip_translate:
        print(">> Skipping translation step")

    # Run the pipeline
    jobs = process_bnf_jobs(skip_scrape=skip_scrape, skip_translate=skip_translate)

    print(f"\nTotal projects found: {len(jobs)}")

    # Count relevant jobs
    relevant_count = sum(1 for job in jobs if job.get('relevant', 0) == 1)
    print(f"Relevant projects: {relevant_count}")

    # Show first 20 projects
    print("\nFirst 20 projects:")
    for i, job in enumerate(jobs[:20]):
        relevant_marker = "[*]" if job.get('relevant', 0) == 1 else "[ ]"
        print(f"  {relevant_marker} {i+1}. {job.get('name_en', job['name'])}")
        print(f"         Original: {job['name']}")
        print(f"         Subject: {job.get('subject', 'N/A')}")
        print(f"         City: {job.get('city', 'N/A')}")

    # Save to CSV
    if jobs:
        df = pd.DataFrame(jobs)
        # Reorder columns for better readability
        cols = ['name_en', 'name', 'subject', 'city', 'relevant', 'url']
        cols = [c for c in cols if c in df.columns]
        df = df[cols]
        df.to_csv('./output/bnf_projects.csv', index=False)
        print(f"\nSaved all {len(jobs)} projects to ./output/bnf_projects.csv")

        # Also save only relevant jobs
        df_relevant = df[df['relevant'] == 1]
        df_relevant.to_csv('./output/bnf_projects_relevant.csv', index=False)
        print(f"Saved {len(df_relevant)} relevant projects to ./output/bnf_projects_relevant.csv")
