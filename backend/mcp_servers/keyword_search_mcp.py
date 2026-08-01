"""
MCP server exposing keyword (Elasticsearch) car search as a tool.

Wraps GET /search/keyword on the running search API — it does not talk to
Elasticsearch directly, so the search API must be running first
(uvicorn main:app --reload, from backend/).

Test standalone with the MCP Inspector:
    mcp dev mcp_servers/keyword_search_mcp.py
"""
import httpx
from mcp.server.fastmcp import FastMCP

SEARCH_API_URL = "http://localhost:8000/search/keyword"

mcp = FastMCP("keyword-search")


@mcp.tool()
async def keyword_search(
    query: str = "",
    top_k: int = 5,
    max_mileage: int | None = None,
    max_price: int | None = None,
    min_year: int | None = None,
    fuel_type: str | None = None,
) -> dict:
    """Search car listings by keyword match against make, model, and description,
    optionally narrowed by structured filters that are actually enforced (not just
    hinted at in text).

    Good for exact terms (brand names, model names, specific words in the
    listing text) and hard constraints. Does not understand meaning/synonyms
    in free text — use semantic search for that.

    Args:
        query: Free-text terms to match (e.g. "family sedan"). Can be empty if
            you only want to filter.
        top_k: How many results to return.
        max_mileage: Only listings with mileage at or below this value.
        max_price: Only listings with price at or below this value.
        min_year: Only listings from this model year or newer.
        fuel_type: Exact fuel type match. Must be one of: "Gasoline", "Diesel",
            "Hybrid", "Electric".
    """
    params = {"query": query, "top_k": top_k}
    if max_mileage is not None:
        params["max_mileage"] = max_mileage
    if max_price is not None:
        params["max_price"] = max_price
    if min_year is not None:
        params["min_year"] = min_year
    if fuel_type is not None:
        params["fuel_type"] = fuel_type

    async with httpx.AsyncClient() as client:
        response = await client.get(SEARCH_API_URL, params=params)
        response.raise_for_status()
        return response.json()


if __name__ == "__main__":
    mcp.run()
