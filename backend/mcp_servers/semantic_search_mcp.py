"""
MCP server exposing semantic (Qdrant vector) car search as a tool.

Wraps GET /search/semantic on the running search API — it does not talk to
Qdrant directly, so the search API must be running first
(uvicorn main:app --reload, from backend/).

Test standalone with the MCP Inspector:
    mcp dev mcp_servers/semantic_search_mcp.py
"""
import httpx
from mcp.server.fastmcp import FastMCP

SEARCH_API_URL = "http://localhost:8000/search/semantic"

mcp = FastMCP("semantic-search")


@mcp.tool()
async def semantic_search(
    query: str,
    top_k: int = 5,
    max_mileage: int | None = None,
    max_price: int | None = None,
    min_year: int | None = None,
    fuel_type: str | None = None,
) -> dict:
    """Search car listings by meaning using vector similarity over descriptions,
    optionally narrowed by structured filters that are actually enforced (applied
    to the stored listing data, not just hinted at in the query text).

    Good for descriptive/natural-language queries (e.g. "spacious family SUV
    with good fuel economy"). Does not guarantee exact keyword matches from
    free text (e.g. a specific color) — use keyword search for that. Hard
    constraints (mileage/price/year/fuel type) should go in the filter
    parameters below, not just be mentioned in the query text.

    Args:
        query: Natural-language description of what the user wants.
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
