from typing import List
from pydantic import BaseModel, Field

from schemas.Tasks import Tasks

class Plan(BaseModel):
    blog_title : str
    audience : str = Field(..., description="Who is the blog for")
    tone : str = Field(..., description="Writing tone (eg : practical, crisp).")
    tasks : List[Tasks]