from typing import Literal

from pydantic import BaseModel, Field

class Tasks(BaseModel):
    id : int
    title : str
    goal : str = Field(..., description= "One sentence describing what the reader should be able to do/understand " 
    "       after this section.")
    bullets : list[str] = Field(..., min_length=3, max_length=5, description="3-5 concrete, non-overlapping " 
    "subpoints to cover in this section")
    target_words: int = Field(..., description="Target word count for this section (120-450).")
    section_type : Literal["intro","core","examples","checklist","common_mistakes","conclusion"] = Field(...,description="Use common_mistakes exactly once in the plan")

    #brief : str = Field(..., description="What to cover")