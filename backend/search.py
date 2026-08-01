"""
Query logic for the two underlying search engines. Each method returns its
own raw ranked results — merging across engines happens one layer up (in an
agent), not here.
"""
from elasticsearch import Elasticsearch
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue, Range
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

    def keyword_search(
        self,
        query: str,
        top_k: int,
        max_mileage: int | None = None,
        max_price: int | None = None,
        min_year: int | None = None,
        fuel_type: str | None = None,
    ) -> list[dict]:
        """Full-text match against description/make/model, optionally narrowed by
        structured filters (exact/range constraints, not just text hints). Returns
        ranked listings."""
        must = []
        if query:
            must.append({"multi_match": {"query": query, "fields": ["description", "make", "model"]}})

        filters = []
        if max_mileage is not None:
            filters.append({"range": {"mileage": {"lte": max_mileage}}})
        if max_price is not None:
            filters.append({"range": {"price": {"lte": max_price}}})
        if min_year is not None:
            filters.append({"range": {"year": {"gte": min_year}}})
        if fuel_type is not None:
            filters.append({"term": {"fuel_type": fuel_type}})

        es_query = {"bool": {}}
        if must:
            es_query["bool"]["must"] = must
        if filters:
            es_query["bool"]["filter"] = filters
        if not must and not filters:
            es_query = {"match_all": {}}

        response = self.es.search(index=ELASTICSEARCH_INDEX, query=es_query, size=top_k)
        return [hit["_source"] for hit in response["hits"]["hits"]]

    def semantic_search(
        self,
        query: str,
        top_k: int,
        max_mileage: int | None = None,
        max_price: int | None = None,
        min_year: int | None = None,
        fuel_type: str | None = None,
    ) -> list[dict]:
        """Embeds the query and finds nearest listings by meaning, optionally narrowed
        by the same structured filters keyword_search supports (applied to Qdrant's
        stored payload, not the vector itself) — so a hard constraint like fuel type
        is actually enforced here too, not just left to text similarity. Returns
        ranked listings."""
        vector = self.model.encode(query).tolist()

        conditions = []
        if max_mileage is not None:
            conditions.append(FieldCondition(key="mileage", range=Range(lte=max_mileage)))
        if max_price is not None:
            conditions.append(FieldCondition(key="price", range=Range(lte=max_price)))
        if min_year is not None:
            conditions.append(FieldCondition(key="year", range=Range(gte=min_year)))
        if fuel_type is not None:
            conditions.append(FieldCondition(key="fuel_type", match=MatchValue(value=fuel_type)))
        query_filter = Filter(must=conditions) if conditions else None

        results = self.qdrant.query_points(
            collection_name=QDRANT_COLLECTION, query=vector, query_filter=query_filter, limit=top_k
        )
        return [point.payload for point in results.points]
