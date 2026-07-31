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
async def semantic_search(query: str, top_k: int = 5) -> dict:
    """Search car listings by meaning using vector similarity over descriptions.

    Good for descriptive/natural-language queries (e.g. "spacious family SUV
    with good fuel economy"). Does not guarantee exact keyword matches (e.g.
    a specific color or brand) — use keyword search for that.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(SEARCH_API_URL, params={"query": query, "top_k": top_k})
        response.raise_for_status()
        return response.json()


if __name__ == "__main__":
    mcp.run()
