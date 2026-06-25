"""
Build the second Milvus collection for RxNorm: rxnorm_concepts.

This mirrors backend/tools/rebuild_milvus.py, but it does not drop or rebuild
the existing SNOMED collection concepts_only_name.

Run:
    python backend/tools/rebuild_rxnorm_milvus.py
"""
import os
import sys

import pandas as pd
from pymilvus import DataType, MilvusClient


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
sys.path.append(BACKEND_DIR)

from utils.embedding_config import EmbeddingConfig
from utils.embedding_factory import create_embedding_model


CSV_PATH = os.path.join(BACKEND_DIR, "data", "rxnorm_clinical.csv")
COLLECTION_NAME = "rxnorm_concepts"
MILVUS_URI = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
BATCH = 256


def main():
    print(f"Reading {CSV_PATH}")
    df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)
    names = df["concept_name"].astype(str).tolist()
    print(f"  Rows: {len(df):,}")

    print("Loading embedding model (bge-m3)...")
    model = create_embedding_model(EmbeddingConfig())
    dim = len(model.embed_query("test"))
    print("  Vector dim:", dim)

    print("Connecting Milvus:", MILVUS_URI)
    client = MilvusClient(uri=MILVUS_URI)
    if client.has_collection(COLLECTION_NAME):
        print("  Dropping old collection:", COLLECTION_NAME)
        client.drop_collection(COLLECTION_NAME)

    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
    for field in [
        {"field_name": "id", "datatype": DataType.INT64, "is_primary": True},
        {"field_name": "concept_id", "datatype": DataType.VARCHAR, "max_length": 64},
        {"field_name": "concept_name", "datatype": DataType.VARCHAR, "max_length": 512},
        {"field_name": "domain_id", "datatype": DataType.VARCHAR, "max_length": 128},
        {"field_name": "concept_code", "datatype": DataType.VARCHAR, "max_length": 128},
        {"field_name": "vector", "datatype": DataType.FLOAT_VECTOR, "dim": dim},
        {"field_name": "FSN", "datatype": DataType.VARCHAR, "max_length": 2048},
    ]:
        schema.add_field(**field)

    index_params = client.prepare_index_params()
    index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
    )

    print("Embedding + inserting rows ...")
    total = len(df)
    for start in range(0, total, BATCH):
        end = min(start + BATCH, total)
        vectors = model.embed_documents(names[start:end])
        rows = []
        for row_index in range(start, end):
            row = df.iloc[row_index]
            rows.append({
                "id": row_index,
                "concept_id": str(row["concept_id"]),
                "concept_name": str(row["concept_name"]),
                "domain_id": str(row["domain_id"]),
                "concept_code": str(row["concept_code"]),
                "FSN": str(row.get("FSN", "")),
                "vector": vectors[row_index - start],
            })
        client.insert(collection_name=COLLECTION_NAME, data=rows)
        print(f"  {end:,}/{total:,}", end="\r")

    client.flush(collection_name=COLLECTION_NAME)
    client.load_collection(collection_name=COLLECTION_NAME)
    print(f"\nDone. Inserted {total:,} rows into {COLLECTION_NAME}.")

    print("\n=== Self-test 'aspirin' ===")
    query_vector = model.embed_query("aspirin")
    results = client.search(
        collection_name=COLLECTION_NAME,
        data=[query_vector],
        anns_field="vector",
        limit=5,
        output_fields=["concept_name", "domain_id", "concept_code"],
    )
    for item in results[0]:
        entity = item["entity"]
        print(
            f"  {entity['concept_name']!r}  "
            f"domain={entity['domain_id']}  "
            f"score={round(item['distance'], 4)}"
        )


if __name__ == "__main__":
    main()
