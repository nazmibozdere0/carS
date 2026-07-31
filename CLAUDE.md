# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

A hybrid car-listings search project: Elasticsearch for keyword/structured search, Qdrant for vector/semantic search, with a fusion layer planned to combine both (not yet built). Currently in early scaffolding stage — only data ingestion exists, no query/API layer yet. The user has no coding background, so explanations in this repo (and in conversation) should stay in plain language.

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

Sanity checks:
```bash
curl "http://localhost:9200/car_listings/_search?q=make:Toyota&pretty"
curl "http://localhost:6333/collections/car_listings"
```

There is no test suite, linter, or build step yet.

## Architecture

- `data/car_listings.json` is the single source of truth for sample data (60 listings: id, make, model, year, mileage, price, fuel_type, description). Both loader scripts read from this file independently — there is no shared ingestion pipeline yet, so schema changes must be applied in three places: `generate_sample_data.py`, `load_elasticsearch.py`'s `INDEX_MAPPING`, and implicitly in `load_qdrant.py`'s payload (which just stores the whole listing dict as-is).
- `backend/config.py` is the single place reading `.env` (via `python-dotenv`) and defining defaults; every backend script imports settings from here rather than reading env vars directly.
- Elasticsearch and Qdrant are loaded as two independent, unsynchronized copies of the same data — `load_elasticsearch.py` indexes structured fields (make/model as `keyword`, description as `text`), while `load_qdrant.py` embeds only the `description` field into a 384-dim vector (via local `sentence-transformers` model `all-MiniLM-L6-v2`, no API key/cost) and stores the full listing as Qdrant payload. Point/document IDs match `id` in the source JSON in both stores, which is what will let a future fusion layer correlate results across the two.
- No embedding API key is used by design (see `.env.example`) — this was a deliberate choice to keep local dev free of paid dependencies; if a hosted embedding provider is ever introduced, `EMBEDDING_MODEL` in `.env`/`config.py` is the intended override point.
- `.env` (real secrets) is gitignored; `.env.example` is the template and must be kept in sync whenever new config vars are added.
