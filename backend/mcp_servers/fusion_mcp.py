"""
MCP server exposing Reciprocal Rank Fusion (RRF) as a tool.

Purely deterministic math — no LLM call, no database access. Takes the raw
ranked result lists from keyword-search-mcp and semantic-search-mcp and
merges them into one ranked list: each listing gets a score based on how
high it ranked in each input list (1 / (60 + rank), summed across both
lists where it appears), then results are sorted by that combined score.
A listing that ranks well in both searches rises to the top.

Test standalone with the MCP Inspector:
    mcp dev mcp_servers/fusion_mcp.py
"""
from mcp.server.fastmcp import FastMCP

RRF_K = 60  # standard constant used in reciprocal rank fusion

mcp = FastMCP("fusion")


def _as_listing_list(value) -> list[dict]:
    """Accepts either a raw list of listings or the {"query", "results"} wrapper
    that keyword_search/semantic_search return, and normalizes to a plain list."""
    if isinstance(value, dict):
        return value.get("results", [])
    return value or []


@mcp.tool()
def fuse_results(keyword_results: list[dict] | dict, semantic_results: list[dict] | dict, top_k: int = 5) -> dict:
    """Merge a keyword-search result list and a semantic-search result list into one
    ranked list using Reciprocal Rank Fusion.

    Args:
        keyword_results: The result list (or full response object) from keyword_search.
        semantic_results: The result list (or full response object) from semantic_search.
        top_k: How many merged results to return.
    """
    keyword_list = _as_listing_list(keyword_results)
    semantic_list = _as_listing_list(semantic_results)

    scores: dict[int, float] = {}
    listings_by_id: dict[int, dict] = {}

    for rank, listing in enumerate(keyword_list):
        scores[listing["id"]] = scores.get(listing["id"], 0) + 1 / (RRF_K + rank)
        listings_by_id[listing["id"]] = listing

    for rank, listing in enumerate(semantic_list):
        scores[listing["id"]] = scores.get(listing["id"], 0) + 1 / (RRF_K + rank)
        listings_by_id[listing["id"]] = listing

    ranked_ids = sorted(scores, key=lambda listing_id: scores[listing_id], reverse=True)

    results = [
        {**listings_by_id[listing_id], "hybrid_score": round(scores[listing_id], 5)}
        for listing_id in ranked_ids[:top_k]
    ]
    return {"results": results}


if __name__ == "__main__":
    mcp.run()
