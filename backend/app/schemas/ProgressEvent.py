from pydantic import BaseModel


class ProgressEvent(BaseModel):
    agent: str
    message: str
    status: str

