"""
Orchestrator agent. Connects to three MCP servers as tools and lets an LLM
(Claude, via strands-agents) run all three in sequence for a single
natural-language query:

1. keyword_search  — raw Elasticsearch results
2. semantic_search — raw Qdrant results
3. fuse_results    — merges the two raw lists into one ranked list via
                      Reciprocal Rank Fusion (pure math, no LLM involved
                      in this step — the LLM's only job here is to pass
                      the two prior tool outputs into fuse_results).

Requires the search API running first (uvicorn main:app --reload, from
backend/), since keyword_search/semantic_search call it over HTTP.

Run with:
    python3 orchestrator.py "family car, low mileage, under 300000 TL, diesel"
"""
import json
import sys

from mcp import StdioServerParameters, stdio_client
from strands import Agent
from strands.models.anthropic import AnthropicModel
from strands.tools.mcp import MCPClient

from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

SYSTEM_PROMPT = """\
You are a car search orchestrator with exactly three tools:

- keyword_search: exact keyword/text match against an Elasticsearch index
  (make, model, description). It has no understanding of numeric ranges or
  meaning — feed it a short, keyword-style string built only from concrete
  terms explicitly present in the user's request (e.g. fuel type, body
  style words, brand/model names, condition words). Do not invent details
  the user didn't mention.
- semantic_search: vector similarity search over listing descriptions. Feed
  it the user's request as close to verbatim as reasonable, since it
  understands meaning and phrasing, not just exact words.
- fuse_results: merges the two raw result lists above into one ranked list
  using Reciprocal Rank Fusion. It does no reasoning of its own — it is
  pure math over rank positions. Call it with keyword_results set to the
  full JSON object returned by keyword_search, and semantic_results set to
  the full JSON object returned by semantic_search.

For every user query, call the tools in this exact order: keyword_search,
then semantic_search, then fuse_results with both of their outputs. Do not
skip any tool, do not reorder them, and do not do any merging or ranking
yourself — that is fuse_results' job. Your final answer should just be the
merged list that fuse_results returned.
"""


def make_mcp_client(script_path: str) -> MCPClient:
    return MCPClient(
        lambda: stdio_client(StdioServerParameters(command=sys.executable, args=[script_path]))
    )


def print_trace(agent: Agent) -> None:
    """Prints each tool call in order: its name, the arguments the LLM sent it,
    and the raw result it returned — so fusion's effect is visible alongside
    the two raw lists that fed into it."""
    tool_name_by_id: dict[str, str] = {}
    tool_input_by_id: dict[str, dict] = {}

    for message in agent.messages:
        if message["role"] != "assistant":
            continue
        for block in message["content"]:
            tool_use = block.get("toolUse")
            if tool_use:
                tool_name_by_id[tool_use["toolUseId"]] = tool_use["name"]
                tool_input_by_id[tool_use["toolUseId"]] = tool_use["input"]

    for message in agent.messages:
        if message["role"] != "user":
            continue
        for block in message["content"]:
            tool_result = block.get("toolResult")
            if not tool_result:
                continue
            tool_use_id = tool_result["toolUseId"]
            name = tool_name_by_id.get(tool_use_id, "unknown_tool")
            arguments = tool_input_by_id.get(tool_use_id, {})

            print(f"\n=== {name} ===")
            print(f"Arguments: {json.dumps(arguments)}")
            for content_item in tool_result["content"]:
                text = content_item.get("text")
                if text:
                    print("Result:")
                    print(text)


def main():
    if len(sys.argv) < 2:
        print('Usage: python3 orchestrator.py "your natural-language query"')
        sys.exit(1)
    query = sys.argv[1]

    # Note: MCPClient instances are passed directly to Agent(tools=...), not entered
    # as context managers ourselves — Agent manages their start/stop lifecycle since
    # they implement the ToolProvider interface.
    keyword_client = make_mcp_client("mcp_servers/keyword_search_mcp.py")
    semantic_client = make_mcp_client("mcp_servers/semantic_search_mcp.py")
    fusion_client = make_mcp_client("mcp_servers/fusion_mcp.py")

    model = AnthropicModel(
        client_args={"api_key": ANTHROPIC_API_KEY},
        model_id=ANTHROPIC_MODEL,
        max_tokens=2048,
    )
    agent = Agent(
        model=model,
        tools=[keyword_client, semantic_client, fusion_client],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,  # we print our own trace below instead of the default stream
    )
    agent(query)

    print_trace(agent)


if __name__ == "__main__":
    main()
