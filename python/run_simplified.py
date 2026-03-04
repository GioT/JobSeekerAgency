import sys
import os

# Get absolute paths based on script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)  # Parent of python/

# Add project root and keys to path
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'keys'))
sys.path.append('../keys')

# Change working directory to project root (for relative file paths like ./output/)
os.chdir(PROJECT_ROOT)

import asyncio
import json
import pandas as pd
from datetime import datetime

## langchain:
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

## Custom scripts:
import Constants as C
from python.tools import *
from python.functions import update_joblist, df_to_gmail_html, send_gmail_smtp

os.environ['OPENAI_API_KEY'] = C.OPENAI_API_KEY
os.environ['ANTHROPIC_API_KEY'] = C.ANTHROPIC_API_KEY
os.environ['GMAIL_USER'] = C.GMAIL_USER
os.environ['GMAIL_APP_PASS'] = C.GMAIL_APP_PASS


# Map company names to their job scraping functions
COMPANY_JOB_FUNCTIONS = {
    # Original companies
    'novartis': get_NOVARTIS_jobs,
    'aws': get_AWS_jobs,
    'ypsomed': get_YPSOMED_jobs,
    'visium': get_VISIUM_jobs,
    'roche': get_ROCHE_jobs,
    'csl': get_CSL_jobs,
    'jj': get_JJ_jobs,
    'iso': get_ISO_jobs,
    'monterosa': get_MONTEROSA_jobs,
    'idorsia': get_IDORSIA_jobs,
    'merck': get_MERCK_jobs,
    'haya': get_HAYA_jobs,
    # Big Pharma
    'takeda': get_TAKEDA_jobs,
    'syngenta': get_SYNGENTA_jobs,
    'lonza': get_LONZA_jobs,
    'biogen': get_BIOGEN_jobs,
    'sandoz': get_SANDOZ_jobs,
    'abbvie': get_ABBVIE_jobs,
    'sanofi': get_SANOFI_jobs,
    'az': get_AZ_jobs,
    'bms': get_BMS_jobs,
    'basilea': get_BASILEA_jobs,
    'debiopharm': get_DEBIOPHARM_jobs,
    'ferring': get_FERRING_jobs,
    'ucb': get_UCB_jobs,
    # Biotech startups
    'ridgeline': get_RIDGELINE_jobs,
    'interax': get_INTERAX_jobs,
    'philochem': get_PHILOCHEM_jobs,
    'spirochem': get_SPIROCHEM_jobs,
    'nbe': get_NBE_jobs,
    'cradle': get_CRADLE_jobs,
    'leadxpro': get_LEADXPRO_jobs,
    'brightpeak': get_BRIGHTPEAK_jobs,
    # Enterprise / Other
    'sophia': get_SOPHIA_jobs,
    'danaher': get_DANAHER_jobs,
    'dsm': get_DSM_jobs,
    'tetrascience': get_TETRASCIENCE_jobs,
    'deepmind': get_DEEPMIND_jobs,
    'fmi': get_FMI_jobs,
    'helsinn': get_HELSINN_jobs,
    'givaudan': get_GIVAUDAN_jobs,
    'clariant': get_CLARIANT_jobs,
    'certara': get_CERTARA_jobs,
    # Tech giants
    'ibm': get_IBM_jobs,
    'apple': get_APPLE_jobs,
    'microsoft': get_MICROSOFT_jobs,
}


async def filter_jobs(joblist_json: str) -> str:
    """Filter job listings to only relevant roles. Input and output are JSON format."""
    print('>> Filtering relevant jobs...')

    system_message = SystemMessage(content="""You are a strict job filter. You receive job listings in JSON format.
ONLY return jobs that are directly related to:
- Machine Learning / AI
- Cheminformatics
- Computational Assisted Drug Discovery (CADD)
- Computational Chemistry
- Data Science

EXCLUDE jobs like: DevOps, statistician, Software Engineering, Tech Lead, general Post-Doc positions, general scientific associate, or any role not directly involving the above fields.

Return ONLY the filtered jobs in the SAME JSON format: {"jobs": [{"name": "...", "url": "..."}, ...]}
Do NOT include any markdown code blocks or explanations, just the raw JSON.""")

    human_message = HumanMessage(content=f"Filter and return ONLY relevant jobs from:\n{joblist_json}")

    model = ChatOpenAI(model='gpt-4o-mini', temperature=0)
    result = await model.ainvoke([system_message, human_message])

    return result.content


def collect_all_jobs() -> tuple[dict[str, str], list[str]]:
    """
    Call each job scraping function and collect results.
    Returns a tuple of:
        - dict mapping company name -> job listings JSON string
        - list of company names that returned 0 jobs
    """
    results = {}
    empty_companies = []

    for company, func in COMPANY_JOB_FUNCTIONS.items():
        print(f'\n>> Fetching jobs for {company.upper()}...')
        try:
            # Call the tool function directly (invoke returns JSON)
            job_list_json = func.invoke({})
            if job_list_json and job_list_json.strip():
                # Parse JSON to count jobs
                try:
                    data = json.loads(job_list_json)
                    job_count = len(data.get('jobs', []))
                    print(f'   Found {job_count} job listings')
                    if job_count > 0:
                        results[company] = job_list_json
                    else:
                        empty_companies.append(company)
                except json.JSONDecodeError:
                    print(f'   Invalid JSON response')
                    empty_companies.append(company)
            else:
                print(f'   No jobs found')
                empty_companies.append(company)
        except Exception as e:
            print(f'   Error fetching jobs: {e}')
            empty_companies.append(company)

    return results, empty_companies


async def process_company_jobs(company: str, joblist_json: str) -> dict | None:
    """Process a single company's job list through filtering. Jobs are already in JSON format."""
    print(f'\n>> Processing {company.upper()}...')

    # Filter jobs (input and output are JSON)
    filtered_json = await filter_jobs(joblist_json)

    if not filtered_json or not filtered_json.strip():
        print(f'   No relevant jobs after filtering')
        return None

    # Return as messages dict for update_joblist compatibility
    return {"messages": [type('Message', (), {'content': filtered_json})()]}


async def process_all_jobs(all_jobs: dict[str, str]):
    """Process all collected jobs (filter) asynchronously."""
    print('\n' + '=' * 50)
    print('STEP 2: Filtering jobs')
    print('=' * 50)

    for company, joblist in all_jobs.items():
        try:
            messages = await process_company_jobs(company, joblist)
            if messages:
                update_joblist(messages, company)
        except Exception as e:
            print(f'   Error processing {company}: {e}')

    print('\n>> Done processing all companies!')


if __name__ == "__main__":
    # Step 1: Collect all jobs SYNCHRONOUSLY (tool functions use asyncio.run internally)
    print('=' * 50)
    print('STEP 1: Collecting jobs from all companies')
    print('=' * 50)

    all_jobs, empty_companies = collect_all_jobs()

    if not all_jobs:
        print('No jobs collected from any company!')
    else:
        # Step 2: Process jobs asynchronously
        asyncio.run(process_all_jobs(all_jobs))

    # Send email with today's jobs
    todate = datetime.today().strftime('%Y-%m-%d')
    df = pd.read_csv('./output/updated_joblist.csv')
    df_td = df.sort_values('date', ascending=False)
    df_td = df_td[df_td['date'] == todate]

    print(df_td)

    if not df_td.empty:
        html_table = df_to_gmail_html(df_td)

        # Add list of companies with 0 jobs
        if empty_companies:
            empty_list = ', '.join(sorted(empty_companies))
            html_table += f'<p style="color: #666; font-size: 12px; margin-top: 20px;">Returned 0 matches: {empty_list}</p>'

        send_gmail_smtp(
            from_addr=os.environ["GMAIL_USER"],
            to_addr="giorgiotamo@gmail.com",
            subject=f"Job Listings - {todate}",
            body=html_table,
            html=True
        )
    else:
        print('No new jobs found today, skipping email.')
