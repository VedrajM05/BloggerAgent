import operator
from typing import Annotated, List, TypedDict

from app.schemas.Plan import Plan


class State(TypedDict):
    correlationId : str
    topic : str
    plan : Plan
    sections : Annotated[List[str], operator.add]
    final : str