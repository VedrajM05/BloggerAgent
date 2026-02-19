from pydantic import BaseModel, Field

class Tasks(BaseModel):
    id : int
    title : str
    brief : str = Field(..., description="What to cover")