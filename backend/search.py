"""
Hybrid search logic: queries Elasticsearch (keyword) and Qdrant (semantic)
separately, then merges the two ranked lists into one using Reciprocal Rank
Fusion (RRF) — a simple, well-known way to combine rankings from different
search engines without needing their scores to be on the same scale.
"""
from elasticsearch import Elasticsearch
from qdrant_client import QdrantClient
from sentence_transformers import SentenceTransformer

from config import (
    ELASTICSEARCH_URL,
    ELASTICSEARCH_INDEX,
    QDRANT_URL,
    QDRANT_COLLECTION,
    EMBEDDING_MODEL,
)

RRF_K = 60  # standard constant used in reciprocal rank fusion


class HybridSearcher:
    def __init__(self):
        self.es = Elasticsearch(ELASTICSEARCH_URL)
        self.qdrant = QdrantClient(url=QDRANT_URL)
        self.model = SentenceTransformer(EMBEDDING_MODEL)

    def keyword_search(self, query: str, top_k: int) -> list[dict]:
        """Full-text match against description/make/model. Returns ranked listings."""
        response = self.es.search(
            index=ELASTICSEARCH_INDEX,
            query={"multi_match": {"query": query, "fields": ["description", "make", "model"]}},
            size=top_k,
        )
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def semantic_search(self, query: str, top_k: int) -> list[dict]:
        """Embeds the query and finds nearest listings by meaning. Returns ranked listings."""
        vector = self.model.encode(query).tolist()
        results = self.qdrant.query_points(
            collection_name=QDRANT_COLLECTION, query=vector, limit=top_k
        )
        return [point.payload for point in results.points]

    def hybrid_search(self, query: str, top_k: int = 5) -> list[dict]:
        """Runs both searches and fuses the rankings with RRF."""
        keyword_results = self.keyword_search(query, top_k=top_k * 2)
        semantic_results = self.semantic_search(query, top_k=top_k * 2)

        scores: dict[int, float] = {}
        listings_by_id: dict[int, dict] = {}

        for rank, listing in enumerate(keyword_results):
            scores[listing["id"]] = scores.get(listing["id"], 0) + 1 / (RRF_K + rank)
            listings_by_id[listing["id"]] = listing

        for rank, listing in enumerate(semantic_results):
            scores[listing["id"]] = scores.get(listing["id"], 0) + 1 / (RRF_K + rank)
            listings_by_id[listing["id"]] = listing

        ranked_ids = sorted(scores, key=lambda listing_id: scores[listing_id], reverse=True)

        return [
            {**listings_by_id[listing_id], "hybrid_score": round(scores[listing_id], 5)}
            for listing_id in ranked_ids[:top_k]
        ]
