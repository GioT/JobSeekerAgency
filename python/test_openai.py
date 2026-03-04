"""Simple test script to verify OpenAI API connectivity."""
import sys
import os

# Get absolute paths based on script location
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)

sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'keys'))

import Constants as C

os.environ['OPENAI_API_KEY'] = C.OPENAI_API_KEY

print("=" * 50)
print("OpenAI API Connectivity Test")
print("=" * 50)

# Test 1: Direct OpenAI client
print("\n>> Test 1: Direct OpenAI client...")
try:
    from openai import OpenAI

    client = OpenAI(timeout=30.0)
    print("   Client created, calling API...")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "Say hello"}],
        max_tokens=10
    )
    print(f"   SUCCESS! Response: {response.choices[0].message.content}")
except Exception as e:
    print(f"   FAILED: {type(e).__name__}: {e}")

# Test 2: LangChain ChatOpenAI
print("\n>> Test 2: LangChain ChatOpenAI...")
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    model = ChatOpenAI(model='gpt-4o-mini', temperature=0, request_timeout=30)
    print("   Model created, calling invoke()...")

    result = model.invoke([HumanMessage(content="Say hello")])
    print(f"   SUCCESS! Response: {result.content}")
except Exception as e:
    print(f"   FAILED: {type(e).__name__}: {e}")

print("\n" + "=" * 50)
print("Tests complete")
print("=" * 50)
