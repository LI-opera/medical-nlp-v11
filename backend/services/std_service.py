import os
import time

from pymilvus import MilvusClient

from utils.embedding_config import EmbeddingConfig
from utils.embedding_factory import create_embedding_model
from utils.structured_logger import exc_meta, log_dependency


class StdService:
    def __init__(self):
        start = time.perf_counter()
        self.collections = {
            "snomed": os.getenv("MILVUS_COLLECTION_NAME", "concepts_only_name"),
            "rxnorm": os.getenv("MILVUS_RXNORM_COLLECTION", "rxnorm_concepts"),
        }
        self.default_source = "snomed"
        self.milvus_uri = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
        self.embedding_model = create_embedding_model(EmbeddingConfig())
        log_dependency(
            "dependency.milvus.connect_start",
            component="StdService",
            uri=self.milvus_uri,
            ok=True,
        )
        try:
            self.client = MilvusClient(uri=self.milvus_uri)
            log_dependency(
                "dependency.milvus.connect_ok",
                component="StdService",
                uri=self.milvus_uri,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                ok=True,
            )
        except Exception as exc:
            log_dependency(
                "dependency.milvus.connect_error",
                component="StdService",
                uri=self.milvus_uri,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                ok=False,
                level="ERROR",
                **exc_meta(exc),
            )
            raise
        self._loaded = set()
        self._ensure_loaded(self.collections[self.default_source])

    def _ensure_loaded(self, collection_name):
        if collection_name not in self._loaded:
            start = time.perf_counter()
            log_dependency(
                "dependency.collection.load_start",
                component="StdService",
                collection_name=collection_name,
                ok=True,
            )
            try:
                self.client.load_collection(collection_name=collection_name)
            except Exception as exc:
                log_dependency(
                    "dependency.collection.load_error",
                    component="StdService",
                    collection_name=collection_name,
                    duration_ms=round((time.perf_counter() - start) * 1000, 2),
                    ok=False,
                    level="ERROR",
                    **exc_meta(exc),
                )
                raise
            self._loaded.add(collection_name)
            log_dependency(
                "dependency.collection.load_ok",
                component="StdService",
                collection_name=collection_name,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                ok=True,
            )

    def search_similar_terms(self, query: str, limit: int = 5, source: str = "snomed"):
        # `source` 表示逻辑概念域；每个概念域对应一个独立的 Milvus collection，
        # 而不是把 SNOMED 和 RxNorm 放在同一个集合的不同字段中。
        collection = self.collections.get(source, self.collections[self.default_source])
        self._ensure_loaded(collection)
        start = time.perf_counter()
        log_dependency(
            "dependency.vector_search.start",
            component="StdService",
            collection_name=collection,
            source=source,
            limit=limit,
            query_len=len(query or ""),
            ok=True,
        )
        try:
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
        except Exception as exc:
            log_dependency(
                "dependency.vector_search.error",
                component="StdService",
                collection_name=collection,
                source=source,
                limit=limit,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                ok=False,
                level="ERROR",
                **exc_meta(exc),
            )
            raise
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
        log_dependency(
            "dependency.vector_search.ok",
            component="StdService",
            collection_name=collection,
            source=source,
            limit=limit,
            result_count=len(results),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
            ok=True,
        )
        return results
