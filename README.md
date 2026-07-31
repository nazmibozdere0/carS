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

From the terminal:

```bash
curl "http://localhost:8000/search/keyword?query=spacious+family+SUV&top_k=5"
curl "http://localhost:8000/search/semantic?query=spacious+family+SUV&top_k=5"
```

- **Keyword search** (Elasticsearch) matches against `description`, `make`, `model` — good at exact words, weak at synonyms/meaning.
- **Semantic search** (Qdrant) embeds the query into a vector and finds nearest neighbors by meaning — good at natural-language queries, but doesn't guarantee exact attribute matches (e.g. asking for a specific color can still surface other colors, since the embedding captures the overall meaning of the sentence, not individual attributes).

## MCP servers

Each search endpoint is also wrapped as its own MCP server, so an agent (or
any MCP-compatible client) can call it as a tool:

- `backend/mcp_servers/keyword_search_mcp.py` — exposes one tool, `keyword_search`, which calls `GET /search/keyword`.
- `backend/mcp_servers/semantic_search_mcp.py` — exposes one tool, `semantic_search`, which calls `GET /search/semantic`.

Both are thin wrappers — they call the running search API over HTTP rather
than talking to Elasticsearch/Qdrant directly, so **the search API
(`uvicorn main:app`) must already be running** before starting either MCP
server.

Test either one standalone with the MCP Inspector (a browser-based test
client for MCP tools, install via `pip install "mcp[cli]"`, requires `uv` —
`pip install uv` — and Node's `npx` on your PATH):

```bash
cd backend
mcp dev mcp_servers/keyword_search_mcp.py    # or semantic_search_mcp.py
```

This prints a local URL with an auth token — open it, click **Connect**, go
to the **Tools** tab, and run the tool with a sample query to see the raw
JSON response.

## What's next

Future steps (not yet done):

- Structured filters in the API (year range, price range, fuel type, color as its own field) alongside the free-text query.
- A fusion agent that calls both MCP tools and combines/reasons over their results (replacing the earlier fixed Reciprocal Rank Fusion approach, which merged results directly in the API).
