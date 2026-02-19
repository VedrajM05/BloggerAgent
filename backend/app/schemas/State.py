import operator
from typing import Annotated, List, TypedDict

from app.schemas.Plan import Plan


class State(TypedDict):
    topic : str
    plan : Plan
    sections : Annotated[List[str], operator.add]
    final : str