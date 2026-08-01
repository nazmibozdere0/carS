"""
Orchestrator agent with a bounded, deterministic decision loop.

The LLM is used exactly once per query, to extract structured search
arguments (a short keyword-style text, a near-verbatim semantic text, and
whichever of the four hard filters — mileage/price/year/fuel_type — the
user actually mentioned). Everything after that is plain Python, on
purpose: the loop's safety properties (hard iteration cap, fixed
relaxation order, no repeated identical query, graceful degradation) must
hold regardless of what the LLM decides to do, so they are enforced in
code rather than trusted to a system prompt.

Loop, per query:
    1. Run keyword_search + semantic_search with the current filter set,
       then fuse_results.
    2. If fusion returned >= MIN_RESULTS listings, stop — that's the
       answer.
    3. Otherwise, relax the next not-yet-relaxed filter in the fixed
       order (mileage -> price -> year -> fuel_type) and try again.
    4. Hard cap of MAX_ITERATIONS. If reached without hitting the
       termination condition, return whatever was found on the last
       iteration with a "closest results" message instead of erroring.

Requires the search API running first (uvicorn main:app --reload, from
backend/), since keyword_search/semantic_search call it over HTTP.

Run with:
    python3 orchestrator.py "family car, low mileage, under 300000 TL, diesel"
"""
import json
import sys
import uuid

from mcp import StdioServerParameters, stdio_client
from pydantic import BaseModel
from strands import Agent
from strands.models.anthropic import AnthropicModel
from strands.tools.mcp import MCPClient

from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

MAX_ITERATIONS = 3
MIN_RESULTS_TO_STOP = 5
RELAXATION_ORDER = ["mileage", "price", "year", "fuel_type"]

EXTRACTION_SYSTEM_PROMPT = """\
You turn a natural-language car search request into structured search
arguments. Output only what the ExtractedQuery schema asks for.

- keyword_query: a short, keyword-style string built only from concrete,
  literal terms in the request (brand/model names, body style words,
  condition words). Do NOT put numeric filters (price, mileage, year) or
  fuel type here — those go in the dedicated filter fields below. Can be
  an empty string if the request has no literal terms beyond filters.
- semantic_query: the user's request translated to English (if needed) and
  kept close to verbatim, since this feeds a meaning-based search.
- max_mileage, max_price, min_year: only set these if the user's request
  implies that constraint; otherwise leave them null. min_year means "this
  year or newer".
- fuel_type: only set if the user mentions a fuel type, and only as
  exactly one of "Gasoline", "Diesel", "Hybrid", "Electric" (translate/
  normalize to one of these four, e.g. "dizel" -> "Diesel").
"""


class ExtractedQuery(BaseModel):
    keyword_query: str
    semantic_query: str
    max_mileage: int | None = None
    max_price: int | None = None
    min_year: int | None = None
    fuel_type: str | None = None


def make_mcp_client(script_path: str) -> MCPClient:
    return MCPClient(
        lambda: stdio_client(StdioServerParameters(command=sys.executable, args=[script_path]))
    )


def call_tool(client: MCPClient, tool_name: str, arguments: dict) -> dict:
    """Calls an MCP tool directly (bypassing agent auto tool-calling) and
    parses its JSON text content into a dict."""
    result = client.call_tool_sync(tool_use_id=str(uuid.uuid4()), name=tool_name, arguments=arguments)
    if result["status"] != "success":
        raise RuntimeError(f"Tool {tool_name} failed: {result['content']}")
    text = next(c["text"] for c in result["content"] if "text" in c)
    return json.loads(text)


def extract_query(query: str) -> ExtractedQuery:
    model = AnthropicModel(
        client_args={"api_key": ANTHROPIC_API_KEY},
        model_id=ANTHROPIC_MODEL,
        max_tokens=1024,
    )
    extractor = Agent(
        model=model,
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        structured_output_model=ExtractedQuery,
        callback_handler=None,
    )
    result = extractor(query)
    return result.structured_output


def run_search_loop(
    keyword_client: MCPClient, semantic_client: MCPClient, fusion_client: MCPClient, extracted: ExtractedQuery
) -> list[dict]:
    active_filters: dict[str, int | str] = {}
    if extracted.max_mileage is not None:
        active_filters["mileage"] = extracted.max_mileage
    if extracted.max_price is not None:
        active_filters["price"] = extracted.max_price
    if extracted.min_year is not None:
        active_filters["year"] = extracted.min_year
    if extracted.fuel_type is not None:
        active_filters["fuel_type"] = extracted.fuel_type

    filter_to_param = {"mileage": "max_mileage", "price": "max_price", "year": "min_year", "fuel_type": "fuel_type"}

    relaxed_so_far: list[str] = []
    seen_filter_states: set[tuple] = set()
    last_relaxed: str | None = None
    fused_results: list[dict] = []

    for iteration in range(1, MAX_ITERATIONS + 1):
        state_key = tuple(sorted(active_filters.items()))
        if state_key in seen_filter_states:
            print(f"\nIteration {iteration}: identical query to a previous attempt -- stopping to avoid a repeat.")
            break
        seen_filter_states.add(state_key)

        search_kwargs = {filter_to_param[name]: value for name, value in active_filters.items()}

        keyword_response = call_tool(
            keyword_client, "keyword_search", {"query": extracted.keyword_query, "top_k": 5, **search_kwargs}
        )
        semantic_response = call_tool(
            semantic_client, "semantic_search", {"query": extracted.semantic_query, "top_k": 5, **search_kwargs}
        )
        fusion_response = call_tool(
            fusion_client,
            "fuse_results",
            {"keyword_results": keyword_response, "semantic_results": semantic_response, "top_k": 5},
        )
        fused_results = fusion_response["results"]

        print(
            f"\nIteration {iteration}: relaxed={last_relaxed or 'none'}, "
            f"active_filters={active_filters or 'none'}, results_after_fusion={len(fused_results)}"
        )

        if len(fused_results) >= MIN_RESULTS_TO_STOP:
            print(f"Termination condition met (>= {MIN_RESULTS_TO_STOP} results) -- stopping.")
            return fused_results

        next_filter = next((f for f in RELAXATION_ORDER if f in active_filters and f not in relaxed_so_far), None)
        if next_filter is None:
            print("No filters left to relax -- stopping.")
            return fused_results
        if iteration == MAX_ITERATIONS:
            print(f"Hit the {MAX_ITERATIONS}-iteration cap without reaching {MIN_RESULTS_TO_STOP} results.")
            print("No exact match found, showing closest results.")
            return fused_results

        del active_filters[next_filter]
        relaxed_so_far.append(next_filter)
        last_relaxed = next_filter

    return fused_results


def main():
    if len(sys.argv) < 2:
        print('Usage: python3 orchestrator.py "your natural-language query"')
        sys.exit(1)
    query = sys.argv[1]

    extracted = extract_query(query)
    print(f"Extracted: {extracted.model_dump_json()}")

    # MCPClient instances are entered as context managers here (unlike when passed to
    # Agent(tools=...)) because we call call_tool_sync directly ourselves this time,
    # instead of letting an Agent auto-manage tool-calling and lifecycle.
    keyword_client = make_mcp_client("mcp_servers/keyword_search_mcp.py")
    semantic_client = make_mcp_client("mcp_servers/semantic_search_mcp.py")
    fusion_client = make_mcp_client("mcp_servers/fusion_mcp.py")

    with keyword_client, semantic_client, fusion_client:
        final_results = run_search_loop(keyword_client, semantic_client, fusion_client, extracted)

    print("\n=== Final results ===")
    print(json.dumps(final_results, indent=2))


if __name__ == "__main__":
    main()
