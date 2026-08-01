"""
Deterministic retrieval evaluation against data/golden_set.json.

No LLM involved anywhere in this script -- each golden-set entry already
specifies structured_filters and semantic_query_text directly, so every
run calls the MCP tools with the exact same arguments and produces
identical numbers. This isolates retrieval quality from anything the
orchestrator's LLM might do differently between runs.

Per query, calls (all directly via MCPClient.call_tool_sync, bypassing the
orchestrator and any agent/LLM step):
    - keyword_search  with the entry's structured_filters (no free text)
    - semantic_search with the entry's semantic_query_text (no filters)
    - fuse_results    with both raw responses above

This is deliberately an apples-to-apples-to-hybrid comparison: keyword
alone only ever gets to use hard filters, semantic alone only ever gets
to use free text, and hybrid gets both via fusion -- so the comparison
table shows what each capability contributes on its own versus combined.

Requires the search API running first (uvicorn main:app --reload, from
backend/), since keyword_search/semantic_search call it over HTTP.

Each method's precision@5/recall@5/MRR for a query are also averaged into
a single composite_score = mean(precision@5, recall@5, MRR); averaging
each method's composite_score across all queries gives its total_score,
used to declare an overall winner.

Run with:
    python3 eval.py
"""
import json
import sys
import time
import uuid
from pathlib import Path

from mcp import StdioServerParameters, stdio_client
from strands.tools.mcp import MCPClient

GOLDEN_SET_PATH = Path(__file__).resolve().parent.parent / "data" / "golden_set.json"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
TOP_K = 5
METHODS = ["keyword", "semantic", "hybrid"]
METRICS = ["precision_at_5", "recall_at_5", "mrr"]


def make_mcp_client(script_path: str) -> MCPClient:
    return MCPClient(
        lambda: stdio_client(StdioServerParameters(command=sys.executable, args=[script_path]))
    )


def call_tool(client: MCPClient, tool_name: str, arguments: dict) -> dict:
    result = client.call_tool_sync(tool_use_id=str(uuid.uuid4()), name=tool_name, arguments=arguments)
    if result["status"] != "success":
        raise RuntimeError(f"Tool {tool_name} failed: {result['content']}")
    text = next(c["text"] for c in result["content"] if "text" in c)
    return json.loads(text)


def ids_in_order(response: dict) -> list[int]:
    return [listing["id"] for listing in response["results"]]


def precision_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    return sum(1 for listing_id in retrieved[:k] if listing_id in relevant) / k


def recall_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 0.0
    return sum(1 for listing_id in retrieved[:k] if listing_id in relevant) / len(relevant)


def reciprocal_rank(retrieved: list[int], relevant: set[int]) -> float:
    for rank, listing_id in enumerate(retrieved, start=1):
        if listing_id in relevant:
            return 1 / rank
    return 0.0


def evaluate_method(retrieved: list[int], relevant: set[int]) -> dict:
    precision = precision_at_k(retrieved, relevant, TOP_K)
    recall = recall_at_k(retrieved, relevant, TOP_K)
    mrr = reciprocal_rank(retrieved, relevant)
    return {
        "retrieved_ids": retrieved,
        "precision_at_5": precision,
        "recall_at_5": recall,
        "mrr": mrr,
        "composite_score": (precision + recall + mrr) / 3,
    }


def run_query(keyword_client, semantic_client, fusion_client, entry: dict) -> dict:
    relevant = set(entry["relevant_listing_ids"])

    keyword_response = call_tool(
        keyword_client, "keyword_search", {"query": "", "top_k": TOP_K, **entry["structured_filters"]}
    )
    semantic_response = call_tool(
        semantic_client, "semantic_search", {"query": entry["semantic_query_text"], "top_k": TOP_K}
    )
    fusion_response = call_tool(
        fusion_client,
        "fuse_results",
        {"keyword_results": keyword_response, "semantic_results": semantic_response, "top_k": TOP_K},
    )

    return {
        "query": entry["query"],
        "structured_filters": entry["structured_filters"],
        "semantic_query_text": entry["semantic_query_text"],
        "relevant_listing_ids": sorted(relevant),
        "keyword": evaluate_method(ids_in_order(keyword_response), relevant),
        "semantic": evaluate_method(ids_in_order(semantic_response), relevant),
        "hybrid": evaluate_method(ids_in_order(fusion_response), relevant),
    }


def compute_averages(per_query_results: list[dict]) -> dict:
    return {
        method: {
            metric: sum(q[method][metric] for q in per_query_results) / len(per_query_results)
            for metric in METRICS
        }
        for method in METHODS
    }


def compute_totals(per_query_results: list[dict]) -> dict:
    return {
        f"total_score_{method}": sum(q[method]["composite_score"] for q in per_query_results)
        / len(per_query_results)
        for method in METHODS
    }


def print_summary_table(averages: dict) -> None:
    header = f"{'Method':<10} {'Precision@5':>12} {'Recall@5':>10} {'MRR':>8}"
    print(header)
    print("-" * len(header))
    for method in METHODS:
        m = averages[method]
        print(f"{method:<10} {m['precision_at_5']:>12.3f} {m['recall_at_5']:>10.3f} {m['mrr']:>8.3f}")


def print_granular_table(per_query_results: list[dict]) -> None:
    query_col_width = max(len(q["query"]) for q in per_query_results)
    query_col_width = min(query_col_width, 50)
    header = f"{'Query':<{query_col_width}} {'keyword':>9} {'semantic':>9} {'hybrid':>9}"
    print(header)
    print("-" * len(header))
    for q in per_query_results:
        query_label = q["query"] if len(q["query"]) <= query_col_width else q["query"][: query_col_width - 1] + "…"
        scores = [q[method]["composite_score"] for method in METHODS]
        print(f"{query_label:<{query_col_width}} {scores[0]:>9.3f} {scores[1]:>9.3f} {scores[2]:>9.3f}")


def print_totals_table(totals: dict) -> None:
    ranked = sorted(METHODS, key=lambda method: totals[f"total_score_{method}"], reverse=True)
    header = f"{'Method':<10} {'total_score':>12}"
    print(header)
    print("-" * len(header))
    for rank, method in enumerate(ranked):
        score = totals[f"total_score_{method}"]
        marker = "  <- winner" if rank == 0 else ""
        print(f"{method:<10} {score:>12.3f}{marker}")


def main():
    with open(GOLDEN_SET_PATH) as f:
        golden_set = json.load(f)

    keyword_client = make_mcp_client("mcp_servers/keyword_search_mcp.py")
    semantic_client = make_mcp_client("mcp_servers/semantic_search_mcp.py")
    fusion_client = make_mcp_client("mcp_servers/fusion_mcp.py")

    with keyword_client, semantic_client, fusion_client:
        per_query_results = [
            run_query(keyword_client, semantic_client, fusion_client, entry) for entry in golden_set
        ]

    averages = compute_averages(per_query_results)
    totals = compute_totals(per_query_results)

    RESULTS_DIR.mkdir(exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_path = RESULTS_DIR / f"eval_run_{timestamp}.json"
    with open(output_path, "w") as f:
        json.dump({"per_query": per_query_results, "averages": averages, "totals": totals}, f, indent=2)

    print(f"Evaluated {len(per_query_results)} queries from {GOLDEN_SET_PATH.name}\n")
    print_summary_table(averages)
    print("\nPer-query composite scores (average of precision@5, recall@5, MRR):\n")
    print_granular_table(per_query_results)
    print("\nTotals (average composite score across all queries):\n")
    print_totals_table(totals)
    print(f"\nFull results written to {output_path}")


if __name__ == "__main__":
    main()
