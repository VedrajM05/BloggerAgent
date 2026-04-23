from fastapi import APIRouter
from schemas.Blog import BlogRequest, BlogResponse
from api.v1 import health
from agents.agents import run_blog_writer
import uuid

api_router = APIRouter()

api_router.include_router(health.router, prefix="/health")

@api_router.post("/generate-blog", response_model=BlogResponse)
def generate_blog(req : BlogRequest):
    correlationId = str(uuid.uuid4())
    result =  run_blog_writer(req.topic, correlationId = correlationId)

    return BlogResponse(
        plan= result["plan"],
        sections=result["sections"]
        # revert these changes later
        # final= result["final"],
        # published_url = result.get("published_url")
        )