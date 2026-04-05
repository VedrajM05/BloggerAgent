from fastapi import FastAPI
from api.v1.router import api_router
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI(title="Blog Writer Agent")

origins = [
    "http://localhost:4200",
    "http://127.0.0.1:4200"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # or ["*"] for testing
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
def root():
    return {"message" : "Backend Running..."}