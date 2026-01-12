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
import numpy as np
import subprocess as sub
from copy import deepcopy
from datetime import datetime


## langchain:
from langchain_core.messages import ToolMessage, BaseMessage, AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver, InMemorySaver
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain.tools import tool

## LLMs from providers:
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

## Langgraph:
from langgraph.graph import START, END, StateGraph, MessagesState
from langgraph.prebuilt import ToolNode
from langgraph.graph.message import add_messages

## Typing
from pydantic import BaseModel, Field
from typing import List,Sequence,TypedDict,Annotated,Literal

## Custom scripts:
import Constants as C
from graph.nodes import *
from graph.edges import *
from graph.state import *
from python.tools import *
from python.functions import *

os.environ['OPENAI_API_KEY'] = C.OPENAI_API_KEY
os.environ['SERPAPI_API_KEY'] = C.SERPAPI_API_KEY # make sure it spelled as: SERPAPI_API_KEY
os.environ['ANTHROPIC_API_KEY'] = C.ANTHROPIC_API_KEY
os.environ['GMAIL_USER'] = C.GMAIL_USER
os.environ['GMAIL_APP_PASS'] = C.GMAIL_APP_PASS


## Get all company career pages from JSON file
with open(os.path.join(PROJECT_ROOT, 'data', 'company2careerpage.json'), 'r') as f:
    company2careerpage = json.load(f)

async def main():
    for select in company2careerpage.keys():

        ## 1. Building the graph
        ## --------------------------
        # Defining tool nodes (from graph.nodes)
        job_tool_node = ToolNode(job_tools)
        web_tool_node = ToolNode(web_tools)

        workflow  = StateGraph(ChatMessages) # from graph.state

        ## adding nodes
        workflow.add_node('agent',call_agent)
        workflow.add_node('jobTools',job_tool_node)
        workflow.add_node('filterer',joblist_filtering)
        workflow.add_node('formatter',joblist_formatting)
        workflow.add_node('codeWriter',code_writing)
        workflow.add_node('codePlanner',code_planning)
        workflow.add_node('webTools',web_tool_node)
        workflow.add_node('codeEval',code_eval)

        ## adding edges and routing
        workflow.add_edge(START,'agent')
        workflow.add_conditional_edges('agent',Router1) # setting router function for the agent
        workflow.add_edge('jobTools','agent') # you want to link tools to agent because agent is responsible for giving an answer to human
        workflow.add_edge('filterer','formatter')
        workflow.add_conditional_edges('codePlanner',Router2)
        workflow.add_edge('webTools','codePlanner')
        workflow.add_edge('codeWriter','codeEval')
        workflow.add_conditional_edges('codeEval',Is_code_ok_YN) # setting router function for the agent

        checkpointer = MemorySaver() # set memory
        graph = workflow.compile(checkpointer=checkpointer) #

        ## 2. running the graph
        ## --------------------------
        print('\n>> looking for jobs for',select)
        print('>> ------------------------------------')
        question   = f'can you simply get the current jobs associated with this company {select}?'
        input_data = {"messages": HumanMessage(content=question),'company':select,'company2careerpage':company2careerpage,'codeiter': 0}
        messages   = await graph.ainvoke(input=input_data, config={"configurable": {"thread_id": 1}})
        print('>> done, if new code was written, please add to tools.py and add to tool list')
        update_joblist(messages,select)

## --------------------------------
## Main
## --------------------------------

if __name__ == "__main__":
    ## get the company career pages
    asyncio.run(main())

    ## send email with todays jobs:
    # find jobs matching todays date
    todate = datetime.today().strftime('%Y-%m-%d')
    df = pd.read_csv('./output/updated_joblist.csv')
    df_td = df.sort_values('date',ascending=False)
    df_td = df_td[df_td['date']==todate]

    html_table = df_to_gmail_html(df_td)

    send_gmail_smtp(
        from_addr=os.environ["GMAIL_USER"],
        to_addr="giorgiotamo@gmail.com",
        subject=f"Job Listings - {todate}",
        body=html_table,
        html=True  # <-- set this to True
    )


    
