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
from app.core.logger import AgentLogger
from app.core.prompt_loader import PromptLoader

agent_logger  = AgentLogger()

# logic to load prompt must be at a top, if written inside langgraph nodes, every node call prompt keeps loading
worker_prompt = PromptLoader.load_prompts(
        "blog_worker.md",
        input_variables=["blog_title","topic","task_title","task_brief"]
    )
orchestrator_prompt = PromptLoader.load_prompts(
        "blog_orchestrator.md",
        input_variables=["topic"]
    )

load_dotenv()

llm = ChatOpenAI()

def orchestrator(state : State) -> dict:
    agent_logger.log_state("orchestrator", state)
    formatted_prompt = orchestrator_prompt.format(
        topic = state["topic"]
    )
    #agent_logger.log_prompt(node_name="orchestrator", correlationId= state.get("correlationId"), prompt=formatted_prompt)
    plan = llm.with_structured_output(Plan).invoke(formatted_prompt)
    
    return {"plan" : plan}

def fanout(state : State):
    agent_logger.log_state("fanout", state)
    return [Send("worker", {"task" : task, "topic" : state['topic'], "plan" : state['plan'],
                            "correlationId": state["correlationId"]})
        for task in state["plan"].tasks]

def worker(payload : dict) -> dict:
    agent_logger.log_state("worker_start", payload)
    task = payload["task"]
    topic = payload["topic"]
    plan = payload["plan"]
    correlationId = payload.get("correlationId")
    audience = plan.audience
    blog_title = plan.blog_title
    tone = plan.tone
    goal = task.goal
    target_words = task.target_words
    bullet_text = task.bullets

    agent_logger.logger.info(
            f"[CID: {correlationId}] | "
            f"[NODE: worker] | "
            f"Task Id: {task.id} | "
            f"Task Title: {task.title} | "
            f"Task Type: {task.section_type} | "
            f"Goal: {task.goal} | "
            f"Plan: {plan.tone} | "
        )

    formatted_prompt = worker_prompt.format(
        blog_title = blog_title,
        audience = audience,
        tone = tone,
        goal = goal,
        topic = topic,
        target_words = target_words,
        task_title = task.title,
        task_type = task.section_type,
        bullet_text = bullet_text
    )
    
    # log_prompt creating too much prompts in log file
    #agent_logger.log_prompt(node_name="worker", correlationId= correlationId, prompt=formatted_prompt)
    
    section_md = llm.invoke(formatted_prompt).content.strip()
    
    return{"sections" : [section_md]}

def reducer(state : State) -> dict:
    agent_logger.log_state("reducer", state)
    title = state["plan"].blog_title
    body = "\n\n".join(state["sections"]).strip()
    # print(f"State ---- \n\nTopic : {state['plan'].blog_title} -- \n\nTasks : {state['plan']}")
    final_markdown = f"# {title}\n\n{body}\n"

    # save to file
    filename = title.lower().replace(" ", "_") + ".md"
    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok= True)
    output_path = output_dir/filename
    print(output_path)
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
def run_blog_writer(topic : str, correlationId : str):
    return workflow.invoke({"topic" : topic, "correlationId" : correlationId})


