from typing import List,Sequence,TypedDict,Annotated,Literal
import subprocess as sub
## langchain
from langchain_core.messages import ToolMessage, BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate, ChatPromptTemplate, SystemMessagePromptTemplate, HumanMessagePromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
## LLMs from providers:
from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
## langgraph
from langgraph.graph import START, END, StateGraph, MessagesState
## Typing
from pydantic import BaseModel, Field
from typing import List,Sequence,TypedDict,Annotated,Literal


def joblist_formatting(state):
    """
    Simply takes the list of job list string and formats to json
    """

    print(f'>> 1.a Formatting job list >>')
    
    messages = state['messages']
    # state["messages"].append(system_message)
    state['joblist'] = messages[-1].content

    # define the format of the final joblist
    class JobList(BaseModel):
        name: str = Field(description='Name of the job')
        url: list = Field(description='The url of the job')
    
    parser       = PydanticOutputParser(pydantic_object=JobList)
    
    human_prompt = HumanMessagePromptTemplate.from_template("{request}\n{format_instructions}")
    chat_prompt  = ChatPromptTemplate.from_messages([human_prompt])
    request      = chat_prompt.format_prompt(request=f"can you split this list {state['joblist']}, which contains job name and url into a nice json format?",
                                         format_instructions=parser.get_format_instructions()).to_messages()
    # model        = ChatOpenAI(model=['gpt-4o-mini','gpt-5'][1],openai_api_key=os.environ['OPENAI_API_KEY'],temperature=0)
    model        = ChatAnthropic(model='claude-sonnet-4-5',temperature=0)
    response     = model.invoke(request)

    state['messages'].append(response)
    
    return state
    
def code_writing(state):
    """
    Agent writing the code to retrieve jobs for companies
    """
    
    print(f'>> 1.b Code Writing, iteration {state['codeiter']}>>')

    # define the system message
    system_message = SystemMessage(
        content="""You are an expert programmer that is ready to help write some clean and concise python code. Please ensure that:

        1. you use beautiful soup and async_playwright
        2. you should only output python code
        3. DO NOT include Python code block markers (```python and ```) in your output
        """
    ) # 3. the ouptut of the code should be a list of job names followed by their application url
    # 3. you end with with 'await main()' instead of 'asyncio.run(main())
    sel_               = state['company']
    company2careerpage = state['company2careerpage']
    question   = f"""can you write a short python code to list the jobs from the company {sel_} career page ({company2careerpage[sel_]})?""" 

    state["messages"].append(HumanMessage(content=question))
    state["messages"].append(system_message)
    # print('> question:',state["question"])
    
    if 1<3:
        # define the messages
        prompt   = ChatPromptTemplate.from_messages(state['messages']).format()
        # select coding model (here gpt 5)
        # model    = ChatOpenAI(model=['gpt-4o-mini','gpt-5'][1],openai_api_key=os.environ['OPENAI_API_KEY'],temperature=0)
        model      = ChatAnthropic(model="claude-sonnet-4-5",temperature=0)
        # get response and prb
        response = model.invoke(prompt) # you are calling the llm here!
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

def code_eval(state):
    """
    Agent responsible for making sure the code is running
    """

    print('>> 2. Code Evaluation >>')

    if 1 < 3:
        # save code to file to check whether it works
        with open("../tmp/tmp.py", "w") as f:
            f.write(state['codescript'])
        f.close()
    
    # run and check outputs
    p = sub.run( 'python ../tmp/tmp.py',shell=True, capture_output=True )
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
    response = model.invoke(prompt)    # you are calling the llm here!
    print('\n> response:',response.content)
    state['messages'].append(response) # don't forget to add message to the response!
    # update the request in case we need to re-write the code
    question = f'The following code "{state['codescript']}" got this output "{p.stdout.decode()}" and got this error: "{response.content}" - can you re-write the code by fixing the error?'
    state["question"] = HumanMessage(content=question)
    
    return state