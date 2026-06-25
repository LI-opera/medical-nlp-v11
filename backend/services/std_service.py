import os

from pymilvus import MilvusClient

from utils.embedding_config import EmbeddingConfig
from utils.embedding_factory import create_embedding_model


class StdService:
    def __init__(self):
        self.collections = {
            "snomed": os.getenv("MILVUS_COLLECTION_NAME", "concepts_only_name"),
            "rxnorm": os.getenv("MILVUS_RXNORM_COLLECTION", "rxnorm_concepts"),
        }
        self.default_source = "snomed"
        self.milvus_uri = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
        self.embedding_model = create_embedding_model(EmbeddingConfig())
        self.client = MilvusClient(uri=self.milvus_uri)
        self._loaded = set()
        self._ensure_loaded(self.collections[self.default_source])

    def _ensure_loaded(self, collection_name):
        if collection_name not in self._loaded:
            self.client.load_collection(collection_name=collection_name)
            self._loaded.add(collection_name)

    def search_similar_terms(self, query: str, limit: int = 5, source: str = "snomed"):
        collection = self.collections.get(source, self.collections[self.default_source])
        self._ensure_loaded(collection)
        query_vector = self.embedding_model.embed_query(query)
        search_result = self.client.search(
            collection_name=collection,
            data=[query_vector],
            anns_field="vector",
            limit=limit,
            output_fields=[
                "concept_id",
                "concept_name",
                "domain_id",
                "concept_code",
                "FSN",
            ],
        )
        results = []
        for item in search_result[0]:
            entity = item["entity"]
            results.append({
                "input": query,
                "concept_id": entity["concept_id"],
                "concept_name": entity["concept_name"],
                "domain_id": entity["domain_id"],
                "concept_code": entity["concept_code"],
                "FSN": entity["FSN"],
                "score": round(item["distance"], 4),
            })
        return results
