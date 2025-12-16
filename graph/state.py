from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing import List,Sequence,TypedDict,Annotated,Literal

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