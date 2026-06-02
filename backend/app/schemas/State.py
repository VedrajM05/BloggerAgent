import operator
from typing import Annotated, List, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from schemas.Plan import Plan
from schemas.ProgressEvent import ProgressEvent


class State(TypedDict):
    correlationId : str
    topic : str
    research_sources : list[dict]
    research_content : list[dict]
    research_summary : "ResearchSummary"
    research_context : str
    plan : Plan
    sections : Annotated[List[str], operator.add]
    progress_events: Annotated[List[ProgressEvent], operator.add]
    final : str
    published_url : str
    # research: list[str] 

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


# class ResearchSummary(BaseModel):

#     core_concepts: list[str] = Field(description="5-10 detailed technical concepts extracted from research")
#     technical_details: list[str] = Field(description="Implementation details, formulas, architectures, examples")
#     risks_and_challenges: list[str] = Field(description="Failure modes, limitations, edge cases")
#     important_trends: list[str] = Field(description="Recent developments, industry usage, future direction")

class ResearchSummary(BaseModel):

    model_config = ConfigDict(
        extra="ignore"
    )

    core_concepts: list[str] = Field(
        default_factory=list,
        description="5-10 detailed technical concepts extracted from research"
    )

    technical_details: list[str] = Field(
        default_factory=list,
        description="Implementation details, formulas, architectures, examples"
    )

    risks_and_challenges: list[str] = Field(
        default_factory=list,
        description="Failure modes, limitations, edge cases"
    )

    important_trends: list[str] = Field(
        default_factory=list,
        description="Recent developments, industry usage, future direction"
    )

    
