import operator
from typing import Annotated, List, TypedDict

from pydantic import BaseModel

from schemas.Plan import Plan


class State(TypedDict):
    correlationId : str
    topic : str
    research_sources : list[dict]
    research_content : list[dict]
    research_summary : str
    plan : Plan
    sections : Annotated[List[str], operator.add]
    final : str
    published_url : str
    research: list[str] 

class SearchResult(BaseModel):
    title : str
    content : str
    # url : str
    # score : float

class TavilyResponse(BaseModel):
    query : str
    results : list[SearchResult]
    response_time : float
    request_id : str


    