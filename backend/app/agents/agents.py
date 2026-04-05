import asyncio
import json
import os
from pathlib import Path
import dotenv
import httpx
from langgraph.graph import StateGraph, START, END
from typing import Annotated, List, Literal, TypedDict
from langgraph.graph.message import add_messages
from langgraph.types import Send 
from langchain_openai import ChatOpenAI
from huggingface_hub import InferenceClient
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from huggingface_hub import InferenceClient
import requests
from schemas.Plan import Plan
from schemas.State import SearchResult, State, TavilyResponse
from core.logger import AgentLogger
from core.prompt_loader import PromptLoader

agent_logger  = AgentLogger()
deepseek_r1 = "deepseek-ai/DeepSeek-R1"

# logic to load prompt must be at a top, if written inside langgraph nodes, every node call prompt keeps loading
worker_prompt = PromptLoader.load_prompts(
        "blog_worker.md",
        input_variables=["blog_title","topic","task_title","task_brief"]
    )
orchestrator_prompt = PromptLoader.load_prompts(
        "blog_orchestrator.md",
        input_variables=["topic"]
    )
dotenv.load_dotenv()

TAVILY_API_KEY  = os.getenv("TAVILY_API_KEY")

llm = ChatOpenAI()
# llm = InferenceClient(model=deepseek_r1)

def tavily_search_node(state : State) -> dict:
    topic = state["topic"]
    # agent_logger.log_state("tavily_search_node", state)
    # Call Tavily search api:
    search_results =  asyncio.run(tavily_search(topic))
    
    # If no search results found
    if not search_results:
        print("No such results")
        return {"research_content" : search_results}
    # print(search_results['results'])
    # top_results = results["results"][:2]
    
    # agent_logger.log_state("tavily_search_node", "search completed")
    
    tavily_response = TavilyResponse(
        query = search_results.get("query"),
        results = [
            SearchResult(
                title = r.get("title"),
                url = r.get("url"),
                content = r.get("content"),
                score = r.get("score"),
            )
            for r in search_results.get('results')
        ],
        response_time = search_results.get("response_time"),
        request_id = search_results.get("request_id")
    )

    # agent_logger.log_state("tavily_search_node", "pydantic model binding completed")

    # for res in tavily_response.results:
    #     # agent_logger.log_state("tavily_search_node", state)
    #     agent_logger.log_state("URL", res.url)
    #     agent_logger.log_state("title", res.title)
    #     agent_logger.log_state("score", res.score)
    #     agent_logger.log_state("content", res.content)
   
    return {"research_content" : tavily_response.results}


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
    filename = title.lower() + ".md"
    output_dir = Path("outputs")
    output_dir.mkdir(parents=True, exist_ok= True)
    output_path = output_dir/filename
    print(output_path)
    output_path.write_text(final_markdown, encoding="utf-8")

    return {"final" : final_markdown}

def publish_to_devto_node(state : State) -> dict:
    
    api_key = os.getenv("DEVTO_API_KEY")

    if not api_key:
        print("Dev.to API key missing")
        return {"published_url":""}

    final_blog=state["final"]

    plan = state["plan"]

    title = plan.blog_title

    url = "https://dev.to/api/articles"

    headers = {
        "api_key" : api_key,
        "Content-Type" : "application/json"
    }

    payload = {
        "article" : {
            "title" : title,
            "published" : True,
            "body_markdown" : final_blog,
            "tags" : ["ai","machinelearning","deeplearning"]
        }
    }

    try:
        response = requests.post(url=url, json=payload, headers=headers)
        
        if response.status_code != 201:
            print("Dev.to publishing failed")
            return {"published_url":""}
        
        data = response.json()

        article_url = data.get("url","")

        print("Published URL : ", article_url)

        return {"published_url": article_url}
    
    except Exception as e:
        print("Publish error : ", str(e))
        return {"published_url":""}



g = StateGraph(State)
g.add_node("orchestrator", orchestrator)
g.add_node("worker", worker)
g.add_node("reducer", reducer)
g.add_node("tavily_search_node", tavily_search_node)
g.add_node("publish_to_devto_node", publish_to_devto_node)

g.add_edge(START, "orchestrator")
g.add_conditional_edges("orchestrator", fanout, ["worker"])
g.add_edge("worker", "reducer")
g.add_edge("reducer", "tavily_search_node")
g.add_edge("tavily_search_node","publish_to_devto_node")
g.add_edge("publish_to_devto_node", END)
g.set_finish_point("publish_to_devto_node")


workflow = g.compile()

#not required for fast api 
# blog = app.invoke({"topic" : "Write a blog on self attention"})
# print(blog)

# Required for FastAPI 
def run_blog_writer(topic : str, correlationId : str):
    return workflow.invoke({"topic" : topic, "correlationId" : correlationId})


# External API calls 


async def tavily_search(topic : str):
    print("tavily_search method invoked")
    url = "https://api.tavily.com/search"
    payload = {
        "api_key" : TAVILY_API_KEY,
        "query" : topic,
        "search_depth" : "basic",
        "max_results" : 5,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data
     