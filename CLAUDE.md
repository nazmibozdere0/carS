# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A hybrid car-listings search project: Elasticsearch for keyword/structured search, Qdrant for vector/semantic search, merged via Reciprocal Rank Fusion (RRF). Elasticsearch and Qdrant are kept unmerged through the API and MCP layers — each is exposed as its own REST endpoint and its own MCP server, returning raw ranked results — and fusion itself is also its own MCP server/tool (pure math, no LLM). The orchestrator agent (`backend/orchestrator.py`, using `strands-agents` + Claude) calls all three MCP tools in sequence: keyword search, semantic search, then fusion, with the LLM only responsible for picking good arguments for the first two and forwarding their outputs into the third. Structured filters (year/price/fuel type actually constraining results, as opposed to being hinted at in free text) are not yet built. The user has no coding background, so explanations in this repo (and in conversation) should stay in plain language.

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
python3 orchestrator.py "family car, low mileage, under 300000 TL, diesel"
```

There is no test suite, linter, or build step yet.

## Architecture

- `data/car_listings.json` is the single source of truth for sample data (60 listings: id, make, model, year, mileage, price, fuel_type, description). Both loader scripts read from this file independently — there is no shared ingestion pipeline yet, so schema changes must be applied in three places: `generate_sample_data.py`, `load_elasticsearch.py`'s `INDEX_MAPPING`, and implicitly in `load_qdrant.py`'s payload (which just stores the whole listing dict as-is).
- `backend/config.py` is the single place reading `.env` (via `python-dotenv`) and defining defaults; every backend script imports settings from here rather than reading env vars directly.
- Elasticsearch and Qdrant are loaded as two independent, unsynchronized copies of the same data — `load_elasticsearch.py` indexes structured fields (make/model as `keyword`, description as `text`), while `load_qdrant.py` embeds only the `description` field into a 384-dim vector (via local `sentence-transformers` model `all-MiniLM-L6-v2`, no API key/cost) and stores the full listing as Qdrant payload. Point/document IDs match `id` in the source JSON in both stores, which is what will let a future fusion layer correlate results across the two.
- No embedding API key is used by design (see `.env.example`) — this was a deliberate choice to keep local dev free of paid dependencies; if a hosted embedding provider is ever introduced, `EMBEDDING_MODEL` in `.env`/`config.py` is the intended override point.
- `.env` (real secrets) is gitignored; `.env.example` is the template and must be kept in sync whenever new config vars are added.
- `backend/search.py` (`CarSearcher`) holds the two independent query methods: `keyword_search` (ES `multi_match` on description/make/model) and `semantic_search` (Qdrant nearest-neighbor, using the same `sentence-transformers` model that must stay in sync with whatever embedded the Qdrant vectors, or similarity scores become meaningless). Neither method merges with the other — there is deliberately no fusion logic in this file anymore.
- `backend/main.py` is a thin FastAPI wrapper exposing each `CarSearcher` method as its own `GET` endpoint (`/search/keyword`, `/search/semantic`). It instantiates one `CarSearcher` (and therefore loads the embedding model) at process startup, not per-request.
- `backend/mcp_servers/keyword_search_mcp.py` and `semantic_search_mcp.py` are two separate MCP servers (built with `mcp.server.fastmcp.FastMCP`), each exposing exactly one tool. Both are HTTP clients of the FastAPI service above (via `httpx`), not direct callers of `CarSearcher` — so the search API must be running before either MCP server is started.
- `backend/mcp_servers/fusion_mcp.py` is a third MCP server exposing `fuse_results`, which reimplements the RRF math that used to live in `search.py`'s now-deleted `hybrid_search` (`RRF_K = 60`, score `1/(RRF_K + rank)` summed per listing ID across both input lists). It takes no dependency on Elasticsearch/Qdrant/the search API — it operates purely on the two lists it's given — so it's usable standalone even without the API running. Its parameters accept either a raw list or the full `{"query": ..., "results": [...]}` wrapper that `keyword_search`/`semantic_search` return (`_as_listing_list` normalizes either shape), since the orchestrator's LLM sometimes forwards the whole tool-result object rather than just the `results` array.
- `backend/orchestrator.py` is the agent that composes all three. It uses `strands-agents` with `AnthropicModel` as the LLM and passes the three `MCPClient` instances directly as `Agent(tools=[...])` — **do not** wrap those in a `with` block yourself; `MCPClient` implements `ToolProvider`, so `Agent` starts/stops the underlying stdio subprocess lifecycle itself, and manually entering the context manager first causes a "the client session is currently running" error. Each `MCPClient` is configured with `stdio_client(StdioServerParameters(command=sys.executable, args=["mcp_servers/....py"]))`, i.e. it spawns the MCP server as a subprocess directly (not via `mcp dev`/Inspector) — the first two subprocesses in turn call the search API over HTTP, so the API must already be running. The system prompt is what enforces the fixed call order (keyword_search → semantic_search → fuse_results) and instructs the LLM to forward the first two tools' outputs into the third verbatim rather than reasoning about the merge itself — the LLM only ever chooses arguments, never ranks or filters results by itself. After `agent(query)` runs, the orchestrator inspects `agent.messages` directly (matching `toolUse` blocks in assistant messages to `toolResult` blocks in user messages via `toolUseId`) to print each tool call's arguments and raw result in order — this bypasses the default `PrintingCallbackHandler`, which only prints tool *names*, not their input arguments.
- `backend/requirements.txt` versions are mutually resolved as a set (`mcp`, `strands-agents`, `fastapi`, `uvicorn` all had to be bumped together once to satisfy each other's transitive pins) — when adding a new dependency, reinstall with `pip install -r backend/requirements.txt` and resolve any conflict by bumping the versions pip reports as already-installed, rather than pinning back down.
