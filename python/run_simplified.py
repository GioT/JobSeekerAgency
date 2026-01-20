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
from langchain_core.prompts import ChatPromptTemplate, HumanMessagePromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

## LLMs from providers:
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

## Typing
from pydantic import BaseModel, Field

## Custom scripts:
import Constants as C
from python.tools import *
from python.functions import update_joblist, df_to_gmail_html, send_gmail_smtp

os.environ['OPENAI_API_KEY'] = C.OPENAI_API_KEY
os.environ['ANTHROPIC_API_KEY'] = C.ANTHROPIC_API_KEY
os.environ['GMAIL_USER'] = C.GMAIL_USER
os.environ['GMAIL_APP_PASS'] = C.GMAIL_APP_PASS


# Pydantic classes for structured output
class Job(BaseModel):
    name: str = Field(description='Name of the job')
    url: str = Field(description='The url of the job')

class JobList(BaseModel):
    jobs: list[Job] = Field(description='List of jobs')


# Map company names to their job scraping functions
COMPANY_JOB_FUNCTIONS = {
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
}


async def filter_jobs(joblist: str) -> str:
    """Filter job listings to only relevant roles."""
    print('>> Filtering relevant jobs...')

    system_message = SystemMessage(content="""You are a strict job filter. ONLY return jobs that are directly related to:
- Machine Learning / AI
- Cheminformatics
- Computational Assisted Drug Discovery (CADD)
- Computational Chemistry
- Data Science

EXCLUDE jobs like: DevOps, statistician, Software Engineering, Tech Lead, general Post-Doc positions, general scientific associate, or any role not directly involving the above fields.
Return ONLY the filtered job list in the same format.""")

    human_message = HumanMessage(content=f"Filter and return ONLY relevant jobs from:\n{joblist}")

    model = ChatOpenAI(model='gpt-4o-mini', temperature=0)
    result = await model.ainvoke([system_message, human_message])

    return result.content


async def format_jobs(joblist: str) -> str:
    """Format job listings into JSON structure."""
    print('>> Formatting job list...')

    parser = PydanticOutputParser(pydantic_object=JobList)
    human_prompt = HumanMessagePromptTemplate.from_template("{request}\n{format_instructions}")
    chat_prompt = ChatPromptTemplate.from_messages([human_prompt])

    question = f"""can you split this list {joblist}, which contains job name and url into a nice json format?
    ONLY ouput a json format without JSON block markers (```json and ```)"""

    request = chat_prompt.format_prompt(
        request=question,
        format_instructions=parser.get_format_instructions()
    ).to_messages()

    model = ChatAnthropic(model='claude-sonnet-4-5', temperature=0)
    response = await model.ainvoke(request)

    return response.content


def collect_all_jobs() -> dict[str, str]:
    """
    Call each job scraping function and collect results.
    Returns a dict mapping company name -> job listings string.
    """
    results = {}

    for company, func in COMPANY_JOB_FUNCTIONS.items():
        print(f'\n>> Fetching jobs for {company.upper()}...')
        try:
            # Call the tool function directly (invoke returns the result)
            job_list = func.invoke({})
            if job_list and job_list.strip():
                results[company] = job_list
                print(f'   Found {len(job_list.splitlines())} job listings')
            else:
                print(f'   No jobs found')
        except Exception as e:
            print(f'   Error fetching jobs: {e}')

    return results


async def process_company_jobs(company: str, joblist: str) -> dict | None:
    """Process a single company's job list through filtering and formatting."""
    print(f'\n>> Processing {company.upper()}...')

    # Step 1: Filter jobs
    filtered = await filter_jobs(joblist)

    if not filtered or not filtered.strip():
        print(f'   No relevant jobs after filtering')
        return None

    # Step 2: Format to JSON
    formatted = await format_jobs(filtered)

    # Return as messages dict for update_joblist compatibility
    return {"messages": [type('Message', (), {'content': formatted})()]}


async def process_all_jobs(all_jobs: dict[str, str]):
    """Process all collected jobs (filter + format) asynchronously."""
    print('\n' + '=' * 50)
    print('STEP 2: Filtering and formatting jobs')
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

    all_jobs = collect_all_jobs()

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
        send_gmail_smtp(
            from_addr=os.environ["GMAIL_USER"],
            to_addr="giorgiotamo@gmail.com",
            subject=f"Job Listings - {todate}",
            body=html_table,
            html=True
        )
    else:
        print('No new jobs found today, skipping email.')
