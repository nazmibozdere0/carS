# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A hybrid car-listings search project: Elasticsearch for keyword/structured search, Qdrant for vector/semantic search, merged via Reciprocal Rank Fusion (RRF), with structured filters (mileage/price/year/fuel type) actually enforced by both engines rather than just hinted at in text. Elasticsearch and Qdrant are kept unmerged through the API and MCP layers — each is exposed as its own REST endpoint and its own MCP server, returning raw ranked results — and fusion itself is also its own MCP server/tool (pure math, no LLM). The orchestrator agent (`backend/orchestrator.py`, using `strands-agents` + Claude) uses the LLM only once per query, to extract structured search arguments; everything after that — calling the three MCP tools and deciding whether/how to relax filters — is a deterministic Python loop, not further LLM reasoning, so its safety properties (hard iteration cap, fixed relaxation order, no repeated queries) hold regardless of what the LLM outputs. The user has no coding background, so explanations in this repo (and in conversation) should stay in plain language.

## Commands

Local services (Elasticsearch on :9200, Qdrant on :6333/:6334):
```bash
docker compose up -d
docker compose down       # stop, keep data
docker compose down -v    # stop and wipe data volumes
```

Python environment (venv lives at repo root as `.venv/`, gitignored):
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
```

Load/reload sample data into both databases (each script drops and recreates its index/collection, so safe to rerun):
```bash
cd backend
python3 load_elasticsearch.py
python3 load_qdrant.py
```

Regenerate the placeholder dataset:
```bash
python3 data/generate_sample_data.py    # overwrites data/car_listings.json, seeded (random.seed(42))
```

Run the search API (requires data already loaded, above):
```bash
cd backend
uvicorn main:app --reload      # then see http://localhost:8000/docs for interactive testing
```

Sanity checks:
```bash
curl "http://localhost:9200/car_listings/_search?q=make:Toyota&pretty"
curl "http://localhost:6333/collections/car_listings"
curl "http://localhost:8000/search/keyword?query=spacious+family+SUV&top_k=5"
curl "http://localhost:8000/search/semantic?query=spacious+family+SUV&top_k=5"
curl "http://localhost:8000/search/keyword?max_price=8000&fuel_type=Diesel"   # structured filters, no free text
```

Run/test an MCP server standalone (`keyword_search_mcp.py`/`semantic_search_mcp.py` require the search API running first; `fusion_mcp.py` is standalone, pure math; all require `uv` on PATH — `pip install uv` — and Node's `npx`):
```bash
cd backend
mcp dev mcp_servers/keyword_search_mcp.py     # or semantic_search_mcp.py, fusion_mcp.py
# opens the MCP Inspector (browser UI) with a printed auth-token URL
```

Run the orchestrator agent (requires the search API running first, and `ANTHROPIC_API_KEY`/`ANTHROPIC_MODEL` set in `.env`):
```bash
cd backend
python3 orchestrator.py "diesel car from 2023 or newer, under 8000 dollars, with less than 20000 miles"
```

There is no test suite, linter, or build step yet.

## Architecture

- `data/car_listings.json` is the single source of truth for sample data (60 listings: id, make, model, year, mileage, price, fuel_type, description). Both loader scripts read from this file independently — there is no shared ingestion pipeline yet, so schema changes must be applied in three places: `generate_sample_data.py`, `load_elasticsearch.py`'s `INDEX_MAPPING`, and implicitly in `load_qdrant.py`'s payload (which just stores the whole listing dict as-is).
- `backend/config.py` is the single place reading `.env` (via `python-dotenv`) and defining defaults; every backend script imports settings from here rather than reading env vars directly.
- Elasticsearch and Qdrant are loaded as two independent, unsynchronized copies of the same data — `load_elasticsearch.py` indexes structured fields (make/model as `keyword`, description as `text`), while `load_qdrant.py` embeds only the `description` field into a 384-dim vector (via local `sentence-transformers` model `all-MiniLM-L6-v2`, no API key/cost) and stores the full listing as Qdrant payload. Point/document IDs match `id` in the source JSON in both stores, which is what will let a future fusion layer correlate results across the two.
- No embedding API key is used by design (see `.env.example`) — this was a deliberate choice to keep local dev free of paid dependencies; if a hosted embedding provider is ever introduced, `EMBEDDING_MODEL` in `.env`/`config.py` is the intended override point.
- `.env` (real secrets) is gitignored; `.env.example` is the template and must be kept in sync whenever new config vars are added.
- `backend/search.py` (`CarSearcher`) holds the two independent query methods: `keyword_search` (ES `multi_match` on description/make/model, plus a `bool` `filter` clause for `max_mileage`/`max_price`/`min_year`/`fuel_type`) and `semantic_search` (Qdrant nearest-neighbor, using the same `sentence-transformers` model that must stay in sync with whatever embedded the Qdrant vectors, or similarity scores become meaningless — plus the *same* four filters applied as a Qdrant payload `Filter`). Both engines enforce the same hard filters; this symmetry matters because if only one engine filtered, fusion would let unfiltered results leak back in from the other side. Neither method merges with the other — there is deliberately no fusion logic in this file.
- `backend/main.py` is a thin FastAPI wrapper exposing each `CarSearcher` method as its own `GET` endpoint (`/search/keyword`, `/search/semantic`), both accepting the same four optional filter query params. It instantiates one `CarSearcher` (and therefore loads the embedding model) at process startup, not per-request.
- `backend/mcp_servers/keyword_search_mcp.py` and `semantic_search_mcp.py` are two separate MCP servers (built with `mcp.server.fastmcp.FastMCP`), each exposing exactly one tool with the same filter parameters as their API endpoint. Both are HTTP clients of the FastAPI service above (via `httpx`), not direct callers of `CarSearcher` — so the search API must be running before either MCP server is started.
- `backend/mcp_servers/fusion_mcp.py` is a third MCP server exposing `fuse_results`, which reimplements the RRF math that used to live in `search.py`'s now-deleted `hybrid_search` (`RRF_K = 60`, score `1/(RRF_K + rank)` summed per listing ID across both input lists). It takes no dependency on Elasticsearch/Qdrant/the search API — it operates purely on the two lists it's given — so it's usable standalone even without the API running. Its parameters accept either a raw list or the full `{"query": ..., "results": [...]}` wrapper that `keyword_search`/`semantic_search` return (`_as_listing_list` normalizes either shape).
- `backend/orchestrator.py` composes all three tools in two stages, not one agentic loop. Stage 1 (`extract_query`) is a single LLM call using `structured_output_model=ExtractedQuery` (a Pydantic model) so the LLM's output is a validated `keyword_query`/`semantic_query`/filter object rather than free text or a tool call. Stage 2 (`run_search_loop`) is plain Python with no further LLM involvement — it calls each MCP tool directly via `MCPClient.call_tool_sync(...)` (not `Agent(tools=...)`), so unlike the extraction agent, these `MCPClient` instances **are** entered with a `with` block in `main()`, since nothing else (no `Agent`) is managing their lifecycle this time. The loop enforces, in code, everything the LLM must not be trusted to enforce on its own: a hard cap of `MAX_ITERATIONS = 3`, a concrete termination check (`len(fused_results) >= MIN_RESULTS_TO_STOP`), a fixed one-way relaxation order (`RELAXATION_ORDER = ["mileage", "price", "year", "fuel_type"]`, each dropped entirely rather than loosened gradually, and never re-relaxed), and a `seen_filter_states` set to guarantee no identical filter combination is queried twice. Hitting the cap without meeting the termination condition returns the last iteration's results rather than erroring or looping further.
- `backend/requirements.txt` versions are mutually resolved as a set (`mcp`, `strands-agents`, `fastapi`, `uvicorn` all had to be bumped together once to satisfy each other's transitive pins) — when adding a new dependency, reinstall with `pip install -r backend/requirements.txt` and resolve any conflict by bumping the versions pip reports as already-installed, rather than pinning back down.
