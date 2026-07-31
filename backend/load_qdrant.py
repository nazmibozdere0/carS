"""
Creates the car_listings collection in Qdrant, turns each listing's description
into a vector using a local embedding model, and loads them all in.

Run with: python3 backend/load_qdrant.py
"""
import json

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from sentence_transformers import SentenceTransformer

from config import QDRANT_URL, QDRANT_COLLECTION, EMBEDDING_MODEL, DATA_FILE


def main():
    print(f"Loading embedding model '{EMBEDDING_MODEL}' (first run downloads it, ~90MB)...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    vector_size = model.get_sentence_embedding_dimension()

    client = QdrantClient(url=QDRANT_URL)

    if client.collection_exists(QDRANT_COLLECTION):
        print(f"Collection '{QDRANT_COLLECTION}' already exists — deleting it to start fresh.")
        client.delete_collection(QDRANT_COLLECTION)

    client.create_collection(
        collection_name=QDRANT_COLLECTION,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
    print(f"Created collection '{QDRANT_COLLECTION}' (vector size {vector_size}).")

    with open(DATA_FILE) as f:
        listings = json.load(f)

    descriptions = [listing["description"] for listing in listings]
    print(f"Embedding {len(descriptions)} descriptions...")
    vectors = model.encode(descriptions, show_progress_bar=True)

    points = [
        PointStruct(id=listing["id"], vector=vector.tolist(), payload=listing)
        for listing, vector in zip(listings, vectors)
    ]
    client.upsert(collection_name=QDRANT_COLLECTION, points=points)

    count = client.count(QDRANT_COLLECTION).count
    print(f"Loaded {count} listings into Qdrant.")


if __name__ == "__main__":
    main()
