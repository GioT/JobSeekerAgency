import sys
sys.path.append('../python')
sys.path.append('../../keys')

import os
import subprocess as sub

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
from nodes import *
from edges import *
from tools import *

## Visualize the graph:
# from IPython.display import Image, display
# from langchain_core.runnables.graph import MermaidDrawMethod

os.environ['OPENAI_API_KEY'] = C.OPENAI_API_KEY
os.environ['SERPAPI_API_KEY'] = C.SERPAPI_API_KEY # make sure it spelled as: SERPAPI_API_KEY
os.environ['ANTHROPIC_API_KEY'] = C.ANTHROPIC_API_KEY

class ChatMessages(TypedDict):
    """
    the State to be passed internally within the graph
    """
    messages: Annotated[Sequence[BaseMessage],add_messages] # the BaseMessages for agents
    question: str
    company: str
    codescript: str # the script written by code-writer agent
    codeiter: int # keeps track of many times code has been modified
    joblist: str # the job list results from parsing career page
    # mytools: List[{}] # the list of tools to access the company jobs # !! YOU CANNOT PASS TOOLS HERE, OTHERWISE ERROR!!
    company2careerpage: dict # associates the company with their jobs postings
    codeplan: str # holds the string describing how to write code from planner
    
    
## Workflow

job_tool_node = ToolNode(job_tools)
web_tool_node = ToolNode(web_tools) 

workflow  = StateGraph(ChatMessages)

## adding nodes
workflow.add_node('agent',call_agent)
workflow.add_node('jobTools',job_tool_node)
workflow.add_node('formatter',joblist_formatting)

## adding edges and routing
workflow.add_edge(START,'agent')
workflow.add_conditional_edges('agent',Router1) # setting router function for the agent
workflow.add_edge('jobTools','agent') # you want to link tools to agent because agent is responsible for giving an answer to human

if 1<3:
    # Nodes
    workflow.add_node('codeWriter',code_writing)
    workflow.add_node('codePlanner',code_planning)
    workflow.add_node('webTools',web_tool_node)
    workflow.add_node('codeEval',code_eval)
    
    # edges
    # workflow.add_edge('codePlanner','codeWriter')
    workflow.add_conditional_edges('codePlanner',Router2)
    workflow.add_edge('webTools','codePlanner')
    workflow.add_edge('codeWriter','codeEval')
    workflow.add_conditional_edges('codeEval',Is_code_ok_YN) # setting router function for the agent


checkpointer = MemorySaver() # set memory
graph = workflow.compile(checkpointer=checkpointer ) # 


## RUN
company2careerpage = {
    'CSL':'https://csl.wd1.myworkdayjobs.com/en-EN/CSL_External?locationCountry=187134fccb084a0ea9b4b95f23890dbe',
    'NOVARTIS':'https://www.novartis.com/careers/career-search?search_api_fulltext=data&country%5B0%5D=LOC_CH&field_job_posted_date=2&op=Submit',
    'VISIUM':'https://www.visium.com/join-us#open-positions',
    'LENOVO':'https://jobs.lenovo.com/en_US/careers/SearchJobs/?13036=%5B12016783%5D&13036_format=6621&listFilterMode=1&jobRecordsPerPage=10&',
    'AWS':'https://www.amazon.jobs/content/en/locations/switzerland/zurich?category%5B%5D=Solutions+Architect',
    'ROCHE':'https://roche.wd3.myworkdayjobs.com/en-US/roche-ext?q=machine%20learning&locations=3543744a0e67010b8e1b9bd75b7637a4',
    'YPSOMED':'https://careers.ypsomed.com/ypsomed/en/professional/',
    'J&J':'https://www.careers.jnj.com/en/jobs/?search=&team=Data+Analytics+%26+Computational+Sciences&country=Switzerland&pagesize=20#results',
    'INCYTE':'https://careers.incyte.com/jobs?searchType=location&page=1&stretch=10&stretchUnit=MILES&locations=Morges,Vaud,Switzerland%7C,,Switzerland&sortBy=relevance',
}
# 'Can you tell me who is the coolest guy in the universe?' #
select     = 'NOVARTIS'
question   = f'can you simply get the current jobs associated with this company {select}?' ## 'can you tell me who is the coolest guy in the universe?'
input_data = {"messages": HumanMessage(content=question),'company':select,'company2careerpage':company2careerpage,'codeiter': 0}
messages   = await graph.ainvoke(input=input_data, config={"configurable": {"thread_id": 1}})