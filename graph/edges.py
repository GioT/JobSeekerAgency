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

# CLASSES
# =======================

# FUNCTIONS
# =======================

def Router1(state)-> Literal['jobTools','codePlanner','filterer']:
    """
    first pass, decides whether to call tool -> formatting or write code to extract jobs
    """
    print('>> 0.1 Router1')
    
    messages = state["messages"]
    last_message = messages[-1]

    # If the LLM makes a tool call, then perform an action
    if last_message.tool_calls:
        print('> 0.2 calling tool')
        # return END
        return "jobTools"
    elif last_message.content == 'No':
        print('> 0.3 proceeding to code planner')
        return "codePlanner"
    return 'filterer'

def Router2(state)-> Literal['webTools','codeWriter']:
    """
    Second pass, tool calling to extract raw html to help code writing
    """
    print('>> 1.0 Router2')
    
    messages = state["messages"]
    last_message = messages[-1]

    # If the LLM makes a tool call, then perform an action
    if last_message.tool_calls:
        print('> 1.2 calling tool')
        return "webTools"
    return 'codeWriter'
    
def Is_code_ok_YN(state) -> Literal['codeWriter',END]:
    """
    If the code did not pass all desirability criteria, returns to code writer for correction
    """
    messages = state['messages']
    
    print('>> 2. Is_code_ok_YN >>')
    
    last_message = state['messages'][-1].content
    # if 
    if last_message == 'Yes' or state['codeiter'] > 10:
        print('> calling tools\n')
        return END # calls the tools node here
    else:
        print('> returning code to code writer')
        return 'codeWriter'
        
    return END