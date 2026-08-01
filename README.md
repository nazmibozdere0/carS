# Car Listings Hybrid Search Assistant

A hobby project exploring **hybrid search** for car listings:

- **Elasticsearch** — keyword and structured search (e.g. "make = Toyota AND price < 20000").
- **Qdrant** — vector database for semantic search (e.g. "spacious family SUV with good gas mileage" matching on meaning, not just keywords).
- A future **fusion agent** that combines results from both to give better answers than either alone.

This is a learning project, built one step at a time.

## Project structure

```
carS/
├── backend/              # Application code (search logic, API, ingestion scripts) — to be built
├── data/
│   ├── car_listings.json         # 60 sample/placeholder car listings for local development
│   └── generate_sample_data.py   # Script that generated the sample data (re-run to regenerate)
├── docker-compose.yml    # Spins up local Elasticsearch + Qdrant
├── .env.example          # Template for environment variables / API keys (copy to .env)
├── .gitignore
├── LICENSE               # MIT
└── README.md
```

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running.
- Python 3 (already used to generate the sample data; will be used later for backend code).

## Running the local services

1. **Start Elasticsearch and Qdrant:**

   ```bash
   docker compose up -d
   ```

   This downloads the Elasticsearch and Qdrant images (first time only) and starts both as background containers.

2. **Check Elasticsearch is up:**

   ```bash
   curl http://localhost:9200
   ```

   You should get back a JSON blob with cluster info (name, version, etc).

3. **Check Qdrant is up:**

   Open [http://localhost:6333/dashboard](http://localhost:6333/dashboard) in your browser — you should see the Qdrant web UI.

4. **Stop the services** (when you're done for the day):

   ```bash
   docker compose down
   ```

   Your data stays on disk (in Docker volumes) between restarts. To wipe everything and start fresh:

   ```bash
   docker compose down -v
   ```

## Environment variables

Copy the example file and fill in real values as needed:

```bash
cp .env.example .env
```

`.env` is listed in `.gitignore`, so your real API keys will never be committed to git.

## Sample data

`data/car_listings.json` contains 60 placeholder car listings with:

- `make`, `model`, `year`, `mileage`, `price`, `fuel_type`
- `description` — a free-text field for semantic search experiments

This is fake data for development only. Regenerate it anytime with:

```bash
python3 data/generate_sample_data.py
```

## Loading the sample data into the databases

Once Elasticsearch and Qdrant are running (see above), set up a Python virtual environment and load the data:

```bash
python3 -m venv .venv
source .venv/bin/activate          # on Windows: .venv\Scripts\activate
pip install -r backend/requirements.txt

cd backend
python3 load_elasticsearch.py      # loads the 60 listings into Elasticsearch
python3 load_qdrant.py             # embeds descriptions locally and loads them into Qdrant
```

`load_qdrant.py` uses a small free local embedding model (`sentence-transformers`,
model `all-MiniLM-L6-v2`) to turn each listing's `description` text into a 384-number
vector — no API key or internet cost required. The first run downloads the model
(~90MB) and caches it.

Both scripts are safe to re-run — they delete and recreate the index/collection each
time, so you always end up with a clean copy of the current `data/car_listings.json`.

**Quick sanity checks:**

```bash
# Elasticsearch: find Toyotas
curl "http://localhost:9200/car_listings/_search?q=make:Toyota&pretty"

# Qdrant: see collection stats
curl "http://localhost:6333/collections/car_listings"
```

## Running the search API

Once the data is loaded (previous section), start the API:

```bash
cd backend
uvicorn main:app --reload
```

Open **http://localhost:8000/docs** in a browser — this is an interactive test
page (Swagger UI) generated automatically by the API framework. There are two
endpoints, each returning its own raw ranked results (no merging happens
here anymore — that's the agent's job, see below):

- `GET /search/keyword?query=...&top_k=5` — Elasticsearch only.
- `GET /search/semantic?query=...&top_k=5` — Qdrant only.

Both also accept structured filter parameters that are **actually enforced**
(not just hinted at in text): `max_mileage`, `max_price`, `min_year`,
`fuel_type` (exact match, one of `Gasoline`/`Diesel`/`Hybrid`/`Electric`).

From the terminal:

```bash
curl "http://localhost:8000/search/keyword?query=spacious+family+SUV&top_k=5"
curl "http://localhost:8000/search/semantic?query=spacious+family+SUV&top_k=5"
curl "http://localhost:8000/search/keyword?max_price=8000&fuel_type=Diesel"
```

- **Keyword search** (Elasticsearch) matches free text against `description`, `make`, `model` — good at exact words, weak at synonyms/meaning. Filters are applied as hard constraints (range/exact-match), separate from the free-text match.
- **Semantic search** (Qdrant) embeds the free text into a vector and finds nearest neighbors by meaning — good at natural-language queries. Filters are applied to Qdrant's stored payload, so a hard constraint like fuel type is enforced here too, not left to text similarity.

## MCP servers

Each search endpoint is also wrapped as its own MCP server, so an agent (or
any MCP-compatible client) can call it as a tool:

- `backend/mcp_servers/keyword_search_mcp.py` — exposes one tool, `keyword_search`, which calls `GET /search/keyword`.
- `backend/mcp_servers/semantic_search_mcp.py` — exposes one tool, `semantic_search`, which calls `GET /search/semantic`.
- `backend/mcp_servers/fusion_mcp.py` — exposes one tool, `fuse_results`, which merges a keyword-search result list and a semantic-search result list into one ranked list. Pure math (Reciprocal Rank Fusion, see below) — no database or search-API call, so it works standalone without the API running.

The first two are thin wrappers — they call the running search API over HTTP
rather than talking to Elasticsearch/Qdrant directly, so **the search API
(`uvicorn main:app`) must already be running** before starting either one.

Test any of them standalone with the MCP Inspector (a browser-based test
client for MCP tools, install via `pip install "mcp[cli]"`, requires `uv` —
`pip install uv` — and Node's `npx` on your PATH):

```bash
cd backend
mcp dev mcp_servers/keyword_search_mcp.py    # or semantic_search_mcp.py, fusion_mcp.py
```

This prints a local URL with an auth token — open it, click **Connect**, go
to the **Tools** tab, and run the tool with a sample query to see the raw
JSON response.

## Orchestrator agent

`backend/orchestrator.py` (built with `strands-agents`, using Claude as the
LLM) turns a natural-language query into a final ranked list in two stages:

1. **One LLM call, to extract structured arguments** — a short keyword-style
   text, a near-verbatim semantic text, and whichever of the four hard
   filters (`max_mileage`, `max_price`, `min_year`, `fuel_type`) the user
   actually mentioned. This uses `strands-agents`' `structured_output_model`
   (a Pydantic schema), so the LLM's output is a validated object, not
   free-form text.
2. **A deterministic Python loop** — everything after extraction is plain
   code, not further LLM reasoning. This is deliberate: the loop's safety
   guarantees need to hold no matter what the LLM does, so they're enforced
   in code rather than trusted to a system prompt.

The loop, per query:

- Call `keyword_search` and `semantic_search` with the current filters,
  then `fuse_results` to merge them.
- **Stop** if fusion returned **5 or more** listings — that's the answer.
- Otherwise, **relax the next filter** in a fixed order — `mileage` →
  `price` → `year` → `fuel_type` — dropping it entirely and trying again.
  Each filter is only ever relaxed once, and the exact same filter
  combination is never retried.
- **Hard cap of 3 iterations.** If the cap is hit without reaching 5
  results, the loop stops and returns whatever it found on the last
  attempt with a "no exact match found, showing closest results" message
  — it never errors and never loops further.

Requires:

- Both `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` set in `.env` (get a key at
  https://console.anthropic.com/ — usage for this is tiny, a few cents).
- The search API running (`uvicorn main:app --reload`, from `backend/`) — the
  orchestrator spawns all three MCP servers itself; the first two in turn
  call the API.

Run it with a natural-language query as an argument:

```bash
cd backend
python3 orchestrator.py "diesel car from 2023 or newer, under 8000 dollars, with less than 20000 miles"
```

Output shows the extracted arguments, then one line per loop iteration
(which filter was relaxed to reach it, and how many results came back
after fusion), then the final result list. Tested scenarios:

- **Deliberately narrow query** (above): iteration 1 (all 4 filters) → 0
  results; iteration 2 (mileage relaxed) → 0; iteration 3 (price relaxed)
  → 1. Cap reached without hitting 5, so the loop stopped and returned
  that 1 result with the "closest results" message — no 4th attempt, no
  error.
- **Moderately narrow query** (`"diesel car under 12000 dollars with less
  than 60000 miles"`): iteration 1 → 0, iteration 2 (mileage relaxed) → 4,
  iteration 3 (price relaxed) → 5 — hit the termination condition exactly
  at the last allowed iteration.
- **Broad query with no filters** (`"spacious family SUV with good fuel
  economy"`): iteration 1 already returns 5 — loop exits immediately,
  nothing to relax.

A listing found by **both** raw searches consistently rose to the top of
the merged list (see the RRF explanation below) — this held both with and
without active filters.

### How Reciprocal Rank Fusion (RRF) works

For each listing, its score is `1 / (60 + rank)` in a given list (`rank`
starts at 0 for the top result; `60` is a standard constant that flattens
the impact of exact rank position). Scores from both lists are summed per
listing ID, and the final list is sorted by that combined score — so a
listing found by only one engine can still place, but one confirmed by
both engines almost always ranks higher.

## What's next

Future steps (not yet done):

- A color filter (currently only free-text inside `description`, not its own structured field).
- Smarter relaxation: currently a relaxed filter is dropped entirely rather than loosened gradually (e.g. widening a price cap by a percentage instead of removing it outright).
