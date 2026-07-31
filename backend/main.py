"""
The search API. Run locally with:
    uvicorn main:app --reload

Then open http://localhost:8000/docs for an interactive test page (Swagger UI) —
no curl or code needed, just fill in a form and click "Execute".
"""
from fastapi import FastAPI
from pydantic import BaseModel

from search import HybridSearcher

app = FastAPI(title="Car Listings Hybrid Search")
searcher = HybridSearcher()


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/search")
def search(request: SearchRequest):
    results = searcher.hybrid_search(request.query, top_k=request.top_k)
    return {"query": request.query, "results": results}
