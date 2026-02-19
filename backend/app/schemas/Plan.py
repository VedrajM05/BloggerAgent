from typing import List
from pydantic import BaseModel, Field

from app.schemas.Tasks import Tasks

class Plan(BaseModel):
    blog_title : str
    tasks : List[Tasks]