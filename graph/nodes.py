import os
from typing import List,Sequence,TypedDict,Annotated,Literal
import subprocess as sub
## langchain
from langchain_core.messages import ToolMessage, BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain.tools import tool
## LLMs from providers:
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
## langgraph
from langgraph.graph import START, END, StateGraph, MessagesState
## Typing
from pydantic import BaseModel, Field
from typing import List,Sequence,TypedDict,Annotated,Literal

## Custom scripts:
from python.tools import *

# Tools
# =======================

job_tools = [get_NOVARTIS_jobs,get_AWS_jobs,get_YPSOMED_jobs,get_VISIUM_jobs,get_ROCHE_jobs,
             get_CSL_jobs,get_JJ_jobs,get_ISO_jobs,get_MONTEROSA_jobs,get_IDORSIA_jobs,get_MERCK_jobs] # 
web_tools = [get_summary_html]

# CLASSES
# =======================

## suggestion from Claude on how propertly format job list
class Job(BaseModel):
    name: str = Field(description='Name of the job')
    url: str = Field(description='The url of the job')

class JobList(BaseModel):
    jobs: list[Job] = Field(description='List of jobs')
    
    
# FUNCTIONS
# =======================

async def call_agent(state):
    """
    First pass to know what to do, if it cannot find a tool to extract job list, then refer to code-writing agent
    """

    print(f'>> 0. First pass >>')

    system_message = SystemMessage(content="""You must ONLY use the available tools to extract job listings based on the provided url.
- If a tool matches: use it and return the results using the url as input
- If NO tool matches: respond with exactly one word: No

Do not explain, do not apologize, do not add any other text.
    """) # 
    
    # model    = ChatAnthropic(model="claude-sonnet-4-5",temperature=0).bind_tools(job_tools)
    model    = ChatOpenAI(model=['gpt-4o-mini','gpt-5'][1],temperature=0).bind_tools(job_tools)
    state['question'] = ''
    response = { "messages": [await model.ainvoke([system_message]+ state["messages"])],"question": ''}
    return response

async def code_planning(state):
    """
    Extracts raw html from webpage and uses it to plan code writing for job extraction
    """
    print(f'>> 1. Code planning >>')

    # 1. get company webpage
    sel_               = state['company']
    company2careerpage = state['company2careerpage']
    webpage            = company2careerpage[sel_]
    # 2. define human and system messages
    system_message = SystemMessage(content="""You are a helpful assistant with the following tasks:
    Design a strategy to write a python code aimed to extract the jobs and associated urls listed in the html page provided as input
    """) # 
    question   = f"""can you design a strategy to extract jobs and urls from this career webpage: '{webpage}'?""" 
    human_message = HumanMessage(content=question)
    # 3. ask model
    model = ChatAnthropic(model="claude-sonnet-4-5",temperature=0).bind_tools(web_tools)
    messages = [system_message]+ [human_message] + state["messages"]
    # print(messages)
    result= await model.ainvoke(messages)
    # print(result)
    response = { "messages": [result], "question":result.content }
    
    # print(response['question'])
    
    return response

async def joblist_filtering(state):
    """
    Takes the list of job and filter
    """

    print(f'>> 1.a filtering relevant jobs >>')
    
    messages = state['messages']
    state['joblist'] = messages[-1].content

    system_message = SystemMessage(content="""You are a strict job filter. ONLY return jobs that are directly related to:
- Machine Learning / AI
- Cheminformatics
- Computational Assisted Drug Discovery (CADD)
- Computational Chemistry
- Data Science

EXCLUDE jobs like: DevOps, statistician, Software Engineering, Tech Lead, general Post-Doc positions, general scientific associate, or any role not directly involving the above fields.
Return ONLY the filtered job list in the same format.""")

    question   = f"Filter and return ONLY relevant jobs from:\n{state['joblist']}"
    human_message = HumanMessage(content=question)
    # 3. ask model
    model = ChatOpenAI(model=['gpt-4o-mini','gpt-5','gpt-5.2-2025-12-11'][-1],temperature=0)
    messages = [system_message]+ [human_message]
    # print(messages)
    result = await model.ainvoke(messages)
    # print(result)
    response = { "messages": [result], "joblist":result.content }
        
    return response


async def joblist_formatting(state):
    """
    Simply takes the list of job list string and formats to json
    """

    print(f'>> 2.a Formatting job list >>')
    
    messages = state['messages']
    # state["messages"].append(system_message)
    # state['joblist'] = messages[-1].content
    
    # require output to match JobList from Pydantic
    parser       = PydanticOutputParser(pydantic_object=JobList)
    human_prompt = HumanMessagePromptTemplate.from_template("{request}\n{format_instructions}")
    chat_prompt  = ChatPromptTemplate.from_messages([human_prompt])
    question     = f"""can you split this list {state['joblist']}, which contains job name and url into a nice json format?
    ONLY ouput a json format without JSON block markers (```json and ```)"""
    request      = chat_prompt.format_prompt(request=question,format_instructions=parser.get_format_instructions()).to_messages()
    model        = ChatAnthropic(model='claude-sonnet-4-5',temperature=0)
    response     = await model.ainvoke(request)

    state['messages'].append(response)
    
    return state
    
async def code_writing(state):
    """
    Agent writing the code to retrieve jobs for companies
    """
    
    print(f'>> 1.b Code Writing, iteration {state['codeiter']}>>')

    # define the system message
    system_message = SystemMessage(
        content="""You are an expert programmer that is ready to help write some clean and concise python code. Please ensure that:

        1. you use beautiful soup, async_playwright and asyncio.run()
        2. you should only output python code
        3. DO NOT include Python code block markers (```python and ```) in your output
        4. write the code as a function that outputs a string
        """
    ) # 3. the ouptut of the code should be a list of job names followed by their application url
    # 3. you end with with 'await main()' instead of 'asyncio.run(main())
    sel_               = state['company']
    company2careerpage = state['company2careerpage']
    question   = f"""can you write a short python code to list the jobs from the company {sel_} career page ({company2careerpage[sel_]})?\n
    {state['question']}""" 

    state["messages"].append(HumanMessage(content=question))
    state["messages"].append(system_message)
    # print('> question:',state["question"])
    
    if 1<3:
        # define the messages
        prompt   = ChatPromptTemplate.from_messages(state['messages']).format()
        # select coding model (here gpt 5)
        model    = ChatOpenAI(model=['gpt-4o-mini','gpt-5','gpt-5.2-2025-12-11'][-1],temperature=0)
        # model      = ChatAnthropic(model="claude-sonnet-4-5",temperature=0)
        # get response and prb
        response = await model.ainvoke(prompt) # you are calling the llm here!
        state['messages'].append(response) # don't forget to add message to the response!
        state['codescript'] = state['messages'][-1].content #
        state['codeiter'] += 1
        
    return state

# making sure the answer is in a correct structure

# class Grade_code_eval(BaseModel):
#     """
#     Boolean value to check whether the code passed all criteria
#     """
#     score: str = Field(
#         description="Did the code generate the desired output without errors? If yes -> 'Yes' if not not -> 'No'"
#     )

async def code_eval(state):
    """
    Agent responsible for making sure the code is running
    """

    print('>> 2. Code Evaluation >>')

    if 1 < 3:
        # save code to file to check whether it works
        with open("./tmp/tmp.py", "w") as f:
            f.write(state['codescript'])
        f.close()
    
    # run and check outputs
    p = sub.run( 'python ./tmp/tmp.py',shell=True, capture_output=True )
    exit_status = '\n* exit status: '+ str(p.returncode)
    stdout      = '\n* stdout: ' + p.stdout.decode()
    stderr      = '\n* stderr:' + p.stderr.decode()
    print( exit_status )
    print( stdout )
    print( stderr )

    state['joblist'] = p.stdout.decode()
    
    ## use LLM to check whether the code was run correcly and ouptut matches expectation, otherwise return code to code writer
    # define the system message
    system_message = SystemMessage(
        content="""You are an expert code evaluator, you will carefully check that the code runs by making sure that:

        1. the exit status is 0
        2. there is no stderr
        3. the stdout output looks like a list of job description followed by their application link and date posted (if date posted is available)

        If all pass, respond with 'Yes'. Otherwise, respond with the error message.
        """
    )
    
    question   = f'Check whether the code ran successfully based on the following output {exit_status+stdout+stderr} '

    state["messages"].append(HumanMessage(content=question))
    state["messages"].append(system_message)

    # define the messages
    messages = state['messages']
    prompt   = ChatPromptTemplate.from_messages(messages).format()
    # select coding model (here gpt 5)
    # model    = ChatOpenAI(model=['gpt-4o-mini','gpt-5'][1],openai_api_key=os.environ['OPENAI_API_KEY'],temperature=0)
    model    = ChatAnthropic(model="claude-sonnet-4-5",temperature=0)
    # get response and prb
    response = await model.ainvoke(prompt)    # you are calling the llm here!
    print('\n> response:',response.content)
    state['messages'].append(response) # don't forget to add message to the response!
    # update the request in case we need to re-write the code
    question = f'Here is the code that you previously wrote:\n "{state['codescript']}"\n, which got this output "{p.stdout.decode()}" and got this error: "{response.content}" - can you re-write the code by fixing the error?'
    state["question"] = question
    
    return state
pass

# MAIN
# =======================

