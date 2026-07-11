# L3 · Stage-2 给 Codex 的指令(可整段复制)· 检索器按源查(多 collection)

## 背景与范围

让检索能选源:SNOMED(`concepts_only_name`)或 RxNorm(`rxnorm_concepts`)。**默认 `source="snomed"`,所有现有调用不传 source → 行为完全不变**(主 benchmark / concept benchmark 照旧查 SNOMED)。本批只改检索层两个文件,**不接路由**(路由是 Stage-3)。

**铁律**:只改 `services/std_service.py`(整文件替换)+ `services/medical_retriever.py`(retrieve 加一个 source 参数并透传);默认全部 snomed,向后兼容;输出结构一字不变。

工作在 `medical-refactor`。

---

## A · 整文件替换 `backend/services/std_service.py`

```python
# 接收输入 -> 转 query vector -> 去 Milvus 搜 -> 返回最相似医学术语
# 【L3 Stage-2】支持多源:SNOMED(concepts_only_name)/ RxNorm(rxnorm_concepts)
import os
from pymilvus import MilvusClient

from utils.embedding_config import EmbeddingConfig
from utils.embedding_factory import create_embedding_model


class StdService:
    def __init__(self):
        # source -> collection 名(默认 snomed 与历史一致;rxnorm 是 L3 第二源)
        self.collections = {
            "snomed": os.getenv("MILVUS_COLLECTION_NAME", "concepts_only_name"),
            "rxnorm": os.getenv("MILVUS_RXNORM_COLLECTION", "rxnorm_concepts"),
        }
        self.default_source = "snomed"
        self.milvus_uri = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
        self.embedding_model = create_embedding_model(EmbeddingConfig())
        self.client = MilvusClient(uri=self.milvus_uri)
        # 默认源预加载;其它源首次检索时按需加载(幂等)
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
            output_fields=["concept_id", "concept_name", "domain_id", "concept_code", "FSN"],
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
```

## B · 改 `backend/services/medical_retriever.py`:retrieve 加 `source` 透传

先 Read 核对。`retrieve(...)` 方法:

**B1. 方法签名**最后加一个参数 `source: str = "snomed"`(放在 `score_threshold` 后面)。例如签名变成:
```python
    def retrieve(
            self,
            query: str,
            top_k: int = 5,
            domain_filter: str | None = None,
            domain_boost: str | None = None,
            score_threshold: float | None = None,
            source: str = "snomed",
            ):
```

**B2. 调用 std_service 那行**加上 `source=source`:
```python
        results = self.std_service.search_similar_terms(query=query, limit=top_k, source=source)
```
> 其余(`_rerank_results`、domain_boost、过滤、文档组装)一律不动。默认 source="snomed",现有调用不传 source 即查 SNOMED,行为不变。

---

## 验收

1. **编译+import**:`python -m compileall backend/services` 通过;`ABBRService` 干净 import。
2. **现有 benchmark 不变(默认 snomed)**:`python backend/evaluation/run_benchmark.py` → 仍 **71/74=0.9595**;`python backend/evaluation/run_concept_benchmark.py` → 仍 PASS 11/11、canonical 10/11。(它们不传 source,默认 SNOMED。)
3. **多源冒烟**(证明能切源):
   ```bash
   python -c "import sys;sys.path.append('backend');from dotenv import load_dotenv;load_dotenv('backend/.env');from services.medical_retriever import MedicalRetriever;r=MedicalRetriever();
   print('RXNORM aspirin:', [d['metadata']['concept_name'] for d in r.retrieve(query='aspirin', top_k=3, source='rxnorm')][:3]);
   print('SNOMED chest pain:', [d['metadata']['concept_name'] for d in r.retrieve(query='chest pain', top_k=3, source='snomed')][:3])"
   ```
   预期:RXNORM 行 top1 是 'aspirin'(走 rxnorm_concepts);SNOMED 行 top1 是 'Chest pain'(走 concepts_only_name)。
4. **判定**:1-3 全过 → 合入。

## 提交

```bash
git add backend/services/std_service.py backend/services/medical_retriever.py
git commit -m "V11 L3 stage2: source-aware retrieval (retrieve(source=snomed|rxnorm) -> multi-collection). Default snomed, fully backward compatible; benchmarks unchanged."
```
> 下一步 Stage-3:在标准化那步按 NER domain 路由——Drug 走 `source='rxnorm'`、Condition/其它走 `source='snomed'`,再用 concept bench(含新增药品 gold)量。
