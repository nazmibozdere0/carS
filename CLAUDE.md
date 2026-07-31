# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A hybrid car-listings search project: Elasticsearch for keyword/structured search, Qdrant for vector/semantic search. The two are deliberately kept unmerged through the API and MCP layers — each is exposed as its own REST endpoint and its own MCP server, returning raw ranked results. A minimal orchestrator agent (`backend/orchestrator.py`, using `strands-agents` + Claude) calls both MCP tools with LLM-extracted arguments, but still does no fusion — it only prints both raw result sets. Actual fusion/ranking logic is not yet built. The user has no coding background, so explanations in this repo (and in conversation) should stay in plain language.

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

Run/test an MCP server standalone (requires the search API running first; requires `uv` on PATH — `pip install uv` — and Node's `npx`):
```bash
cd backend
mcp dev mcp_servers/keyword_search_mcp.py     # or semantic_search_mcp.py
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
- `backend/mcp_servers/keyword_search_mcp.py` and `semantic_search_mcp.py` are two separate MCP servers (built with `mcp.server.fastmcp.FastMCP`), each exposing exactly one tool. Both are HTTP clients of the FastAPI service above (via `httpx`), not direct callers of `CarSearcher` — so the search API must be running before either MCP server is started. This keeps the MCP layer decoupled from the search/query logic: an agent that composes both tools is expected to live above this layer and do the actual fusion.
- `backend/orchestrator.py` is that agent, currently minimal (no fusion logic yet). It uses `strands-agents` with `AnthropicModel` as the LLM and passes both `MCPClient` instances directly as `Agent(tools=[...])` — **do not** wrap those in a `with` block yourself; `MCPClient` implements `ToolProvider`, so `Agent` starts/stops the underlying stdio subprocess lifecycle itself, and manually entering the context manager first causes a "the client session is currently running" error. Each `MCPClient` is configured with `stdio_client(StdioServerParameters(command=sys.executable, args=["mcp_servers/....py"]))`, i.e. it spawns the MCP server as a subprocess directly (not via `mcp dev`/Inspector) — that subprocess in turn calls the search API over HTTP, so the API must already be running. After `agent(query)` runs, the orchestrator inspects `agent.messages` directly (looking for `toolUse` blocks in assistant messages and `toolResult` blocks in user messages) to print exactly what arguments were sent and what raw JSON came back — this bypasses the default `PrintingCallbackHandler`, which only prints tool *names*, not their input arguments.
- `backend/requirements.txt` versions are mutually resolved as a set (`mcp`, `strands-agents`, `fastapi`, `uvicorn` all had to be bumped together once to satisfy each other's transitive pins) — when adding a new dependency, reinstall with `pip install -r backend/requirements.txt` and resolve any conflict by bumping the versions pip reports as already-installed, rather than pinning back down.
