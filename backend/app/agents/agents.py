import json
from pathlib import Path
from langgraph.graph import StateGraph, START, END
from typing import Annotated, List, Literal, TypedDict
from langgraph.graph.message import add_messages
from langgraph.types import Send 
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from app.schemas.Plan import Plan
from app.schemas.State import State

load_dotenv()

llm = ChatOpenAI()

def orchestrator(state : State) -> dict:
    plan = llm.with_structured_output(Plan).invoke([
        SystemMessage(
            content=("Create a blog plan with 5-7 sections on the following topic")
            ),
        HumanMessage(content=f"Topic: {state['topic']}"),
    ])
    # print("orchestrator called")
    return {"plan" : plan}

def fanout(state : State):
    return [Send("worker", {"task" : task, "topic" : state['topic'], "plan" : state['plan']})
        for task in state["plan"].tasks]

def worker(payload : dict) -> dict:
    task = payload["task"]
    topic = payload["topic"]
    plan = payload["plan"]

    blog_title = plan.blog_title

    section_md = llm.invoke(
        [
            SystemMessage(content="Write one clean markdown section"),
            HumanMessage(content=
                        (
                         f"Blog : {blog_title}\n\n"
                         f"Topic : {topic}\n\n"
                         f"Section : {task.title}\n\n"
                         f"Brief : {task.brief}\n\n"
                         "Return only the section content in markdown"
                        )
                    ),
        ]
    ).content.strip()

    return{"sections" : [section_md]}

def reducer(state : State) -> dict:
    
    title = state["plan"].blog_title
    body = "\n\n".join(state["sections"]).strip()

    final_markdown = f"# {title}\n\n{body}\n"

    # save to file
    filename = title.lower().replace(" ", "_") + ".md"
    output_path = Path(filename)
    output_path.write_text(final_markdown, encoding="utf-8")

    return {"final" : final_markdown}

g = StateGraph(State)
g.add_node("orchestrator", orchestrator)
g.add_node("worker", worker)
g.add_node("reducer", reducer)

g.add_edge(START, "orchestrator")
g.add_conditional_edges("orchestrator", fanout, ["worker"])
g.add_edge("worker", "reducer")
g.add_edge("reducer", END)

workflow = g.compile()

#not required for fast api 
# blog = app.invoke({"topic" : "Write a blog on self attention"})
# print(blog)

# Required for FastAPI 
def run_blog_writer(topic : str):
    return workflow.invoke({"topic" : topic})


