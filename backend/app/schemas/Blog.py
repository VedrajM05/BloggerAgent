from typing import Optional

from pydantic import BaseModel

class BlogRequest(BaseModel):
    topic: str


    
class BlogResponse(BaseModel):
    final: str
    published_url : Optional[str] = None