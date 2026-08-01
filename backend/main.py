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
def search_keyword(
    query: str = "",
    top_k: int = 5,
    max_mileage: int | None = None,
    max_price: int | None = None,
    min_year: int | None = None,
    fuel_type: str | None = None,
):
    results = searcher.keyword_search(
        query,
        top_k=top_k,
        max_mileage=max_mileage,
        max_price=max_price,
        min_year=min_year,
        fuel_type=fuel_type,
    )
    return {"query": query, "results": results}


@app.get("/search/semantic")
def search_semantic(
    query: str,
    top_k: int = 5,
    max_mileage: int | None = None,
    max_price: int | None = None,
    min_year: int | None = None,
    fuel_type: str | None = None,
):
    results = searcher.semantic_search(
        query,
        top_k=top_k,
        max_mileage=max_mileage,
        max_price=max_price,
        min_year=min_year,
        fuel_type=fuel_type,
    )
    return {"query": query, "results": results}
