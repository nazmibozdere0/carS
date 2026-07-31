"""
The search API. Run locally with:
    uvicorn main:app --reload

Then open http://localhost:8000/docs for an interactive test page (Swagger UI) —
no curl or code needed, just fill in a form and click "Execute".
"""
from fastapi import FastAPI

from search import CarSearcher

app = FastAPI(title="Car Listings Search")
searcher = CarSearcher()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/search/keyword")
def search_keyword(query: str, top_k: int = 5):
    results = searcher.keyword_search(query, top_k=top_k)
    return {"query": query, "results": results}


@app.get("/search/semantic")
def search_semantic(query: str, top_k: int = 5):
    results = searcher.semantic_search(query, top_k=top_k)
    return {"query": query, "results": results}
