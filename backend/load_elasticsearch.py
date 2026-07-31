"""
Creates the car_listings index in Elasticsearch and loads data/car_listings.json into it.

Run with: python3 backend/load_elasticsearch.py
"""
import json

from elasticsearch import Elasticsearch, helpers

from config import ELASTICSEARCH_URL, ELASTICSEARCH_INDEX, DATA_FILE

INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "id": {"type": "integer"},
            "make": {"type": "keyword"},
            "model": {"type": "keyword"},
            "year": {"type": "integer"},
            "mileage": {"type": "integer"},
            "price": {"type": "integer"},
            "fuel_type": {"type": "keyword"},
            "description": {"type": "text"},
        }
    }
}


def main():
    client = Elasticsearch(ELASTICSEARCH_URL)

    if client.indices.exists(index=ELASTICSEARCH_INDEX):
        print(f"Index '{ELASTICSEARCH_INDEX}' already exists — deleting it to start fresh.")
        client.indices.delete(index=ELASTICSEARCH_INDEX)

    client.indices.create(index=ELASTICSEARCH_INDEX, body=INDEX_MAPPING)
    print(f"Created index '{ELASTICSEARCH_INDEX}'.")

    with open(DATA_FILE) as f:
        listings = json.load(f)

    actions = [
        {"_index": ELASTICSEARCH_INDEX, "_id": listing["id"], "_source": listing}
        for listing in listings
    ]
    helpers.bulk(client, actions)
    client.indices.refresh(index=ELASTICSEARCH_INDEX)

    count = client.count(index=ELASTICSEARCH_INDEX)["count"]
    print(f"Loaded {count} listings into Elasticsearch.")


if __name__ == "__main__":
    main()
