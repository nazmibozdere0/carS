"""
Minimal orchestrator agent. It connects to both MCP servers as tools and
lets an LLM (Claude, via strands-agents) decide what arguments to send each
one from a single natural-language query.

No fusion logic here on purpose — the agent only calls both tools and we
print each tool's raw, unmerged result set. Combining the two result sets
into one ranked answer is a later step.

Requires the search API running first (uvicorn main:app --reload, from
backend/), since both MCP servers call it over HTTP.

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
You are a car search orchestrator with exactly two tools:

- keyword_search: exact keyword/text match against an Elasticsearch index
  (make, model, description). It has no understanding of numeric ranges or
  meaning — feed it a short, keyword-style string built only from concrete
  terms explicitly present in the user's request (e.g. fuel type, body
  style words, brand/model names, condition words). Do not invent details
  the user didn't mention.
- semantic_search: vector similarity search over listing descriptions. Feed
  it the user's request as close to verbatim as reasonable, since it
  understands meaning and phrasing, not just exact words.

For every user query, call BOTH tools exactly once each. Do not skip
either one. Do not merge, rank, compare, or comment on the results — your
only job this step is to call both tools with well-chosen arguments.
"""


def make_mcp_client(script_path: str) -> MCPClient:
    return MCPClient(
        lambda: stdio_client(StdioServerParameters(command=sys.executable, args=[script_path]))
    )


def print_tool_calls(agent: Agent) -> None:
    print("\n--- Arguments the orchestrator sent to each tool ---")
    for message in agent.messages:
        if message["role"] != "assistant":
            continue
        for block in message["content"]:
            tool_use = block.get("toolUse")
            if tool_use:
                print(f"{tool_use['name']}({json.dumps(tool_use['input'])})")


def print_tool_results(agent: Agent) -> None:
    print("\n--- Raw results returned by each tool (unmerged) ---")
    for message in agent.messages:
        if message["role"] != "user":
            continue
        for block in message["content"]:
            tool_result = block.get("toolResult")
            if not tool_result:
                continue
            for content_item in tool_result["content"]:
                text = content_item.get("text")
                if text:
                    print(text)
                    print()


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

    model = AnthropicModel(
        client_args={"api_key": ANTHROPIC_API_KEY},
        model_id=ANTHROPIC_MODEL,
        max_tokens=1024,
    )
    agent = Agent(
        model=model,
        tools=[keyword_client, semantic_client],
        system_prompt=SYSTEM_PROMPT,
        callback_handler=None,  # we print our own trace below instead of the default stream
    )
    agent(query)

    print_tool_calls(agent)
    print_tool_results(agent)


if __name__ == "__main__":
    main()
