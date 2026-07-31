"""
Query logic for the two underlying search engines. Each method returns its
own raw ranked results — merging across engines happens one layer up (in an
agent), not here.
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


class CarSearcher:
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
