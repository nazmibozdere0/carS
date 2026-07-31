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
async def keyword_search(query: str, top_k: int = 5) -> dict:
    """Search car listings by keyword match against make, model, and description.

    Good for exact terms (brand names, model names, specific words in the
    listing text). Does not understand meaning/synonyms — use semantic
    search for that.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(SEARCH_API_URL, params={"query": query, "top_k": top_k})
        response.raise_for_status()
        return response.json()


if __name__ == "__main__":
    mcp.run()
