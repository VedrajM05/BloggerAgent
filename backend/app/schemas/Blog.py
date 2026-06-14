from typing import List, Optional
from typing import Optional

from pydantic import BaseModel
from schemas.QualityAssessment import QualityAssessment
from schemas.Plan import Plan
from schemas.ProgressEvent import ProgressEvent

class BlogRequest(BaseModel):
    topic: str


    
class BlogResponse(BaseModel):
    topic: str
    final: str
    plan: Optional[Plan] = None
    events: list[ProgressEvent]
    quality_assessment : QualityAssessment
