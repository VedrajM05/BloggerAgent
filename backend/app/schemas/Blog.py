from typing import List, Optional

from pydantic import BaseModel
from schemas.Plan import Plan

class BlogRequest(BaseModel):
    topic: str


    
class BlogResponse(BaseModel):
    plan : Plan
    sections : List[str]
    # revert this changes later
    # final: str
    # published_url : Optional[str] = None