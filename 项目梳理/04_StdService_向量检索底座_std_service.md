# StdService（向量检索底座：query → 向量 → Milvus → TopK）

> 文件：`backend/services/std_service.py`（60 行）
> 入口：`search_similar_terms(query, limit=5)`
> 衔接：第 2 篇造好了 embedding 模型，第 3 篇灌好了 Milvus 库。这一篇把两者**接起来用**——运行时拿一句话去库里查最像的标准概念。它是整个 RAG 检索的最底层原语，下一篇 MedicalRetriever 在它之上加重排和过滤。

## 核心速记
> 1. **职责单一**：StdService 只做一件事——"一句话 → 向量 → Milvus 搜 → 返回 TopK"。不重排、不过滤、不懂业务。这是它最该被讲清的设计点。
> 2. **`__init__` 做重活一次**：建 embedding 模型 + 连 Milvus + `load_collection`，之后所有查询复用（就是上一题说的"对象级预加载复用"的实例）。
> 3. **`score = round(distance, 4)`**：COSINE 度量下 distance 就是相似度，**越大越像**（约 0~1）。这是最容易讲反的点。
> 次要（trivia）：`data=[query_vector]` 用 list 是因为 Milvus 支持批量查询、`output_fields` 不取 vector、env 默认值——扫一眼。

## 这一段在解决什么

大白话：**它是"去仓库取货的那只手"。** 你给它一句话，它负责把这句话变成向量、去 Milvus 仓库里找最像的几个标准概念、把结果整理好还给你。

```text
"chest pain"
   ↓ embed_query 变成 1024 维向量
   ↓ Milvus 在 5000 个概念里找最近的 limit 个
返回 [{concept_name, concept_id, code, domain, FSN, score}, ...]
```

## 核心1 · `__init__`：开店前先把家伙备齐（骨架）

```python
def __init__(self):
    self.collection_name = os.getenv("MILVUS_COLLECTION_NAME", "concepts_only_name")
    self.milvus_uri      = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
    self.embedding_model = create_embedding_model(EmbeddingConfig())   # ← 回扣第2篇工厂
    self.client          = MilvusClient(uri=self.milvus_uri)
    self.client.load_collection(collection_name=self.collection_name)  # ← 回扣第3篇的库
```

**翻译这四步**：读配置（哪台 Milvus、哪个 collection，带默认值）→ 造 embedding 模型 → 连 Milvus → **把库 load 进内存**（不 load 不能搜，第 3 篇讲过）。

**为什么放 `__init__`**：这四件都是"重活"（造模型几秒、连库、load）。放进 `__init__` = **建一次 StdService，后面所有 `search_similar_terms` 调用都复用这一套**，不重复加载。这正是上一题讲的"对象级预加载复用"。

> env 带默认值的好处：本地开发不配也能跑（用默认 `127.0.0.1:19530` / `concepts_only_name`），上 Docker 时用 `.env` 覆盖成 `host.docker.internal`——同一份代码两种环境。

## 核心2 · `search_similar_terms`：真正的向量搜索（实现机制 + 真实数据）

```python
def search_similar_terms(self, query, limit=5):
    query_vector = self.embedding_model.embed_query(query)      # 一句话 → 向量
    search_result = self.client.search(
        collection_name=self.collection_name,
        data=[query_vector],                # 注意是 list
        anns_field="vector",                # 在哪个字段上做近邻搜索
        limit=limit,                        # 取前几个
        output_fields=["concept_id","concept_name","domain_id","concept_code","FSN"],
    )
    results = []
    for item in search_result[0]:           # [0] 取第一个 query 的结果
        entity = item["entity"]
        results.append({
            "input": query,                 # 把原 query 带上，方便追溯
            "concept_id": entity["concept_id"],
            "concept_name": entity["concept_name"],
            "domain_id": entity["domain_id"],
            "concept_code": entity["concept_code"],
            "FSN": entity["FSN"],
            "score": round(item["distance"], 4),   # ← COSINE：越大越像
        })
    return results
```

三个要会讲的点：

- **`data=[query_vector]` 为什么套一层 list**：Milvus 的 `search` 支持**一次查多个向量**（批量），所以入参是"向量的列表"。这里只查一个，所以结果用 `search_result[0]` 取第一个 query 的那批结果。
- **`score = round(item["distance"], 4)`**：建库用的是 COSINE 度量，**COSINE 下 Milvus 返回的 `distance` 其实就是余弦相似度，越大越像**（约 0~1）。所以下一篇 MedicalRetriever 用 `score >= 0.6` 来过滤"够不够像"。⚠️ 如果建库改成 L2 距离，就反过来（越小越像）——代码直接把 distance 叫 score、没对度量做适配，这是个隐藏依赖（见局限）。
- **`output_fields` 不含 `vector`**：只取 metadata，不把 1024 维向量回传——没必要，省带宽。

## 核心3 · 它故意"什么都不多做"（设计点，要会讲）

StdService 只返回**原始 TopK**，注意它**没做**这些：

```text
✗ 不重排（rerank）
✗ 不按 domain/score 过滤
✗ 不拼 page_content、不懂"这是给缩写扩写用的"
```

这些全在上一层 `MedicalRetriever`（下一篇）做。

**为什么这样分层**：StdService 是"通用向量检索原语"——任何需要"按语义搜 SNOMED"的功能都能复用它，不被某个业务逻辑绑死。业务相关的重排和过滤往上放。**职责单一、可复用**，这是面试讲分层时的标准加分点。

## 数据快照：一次查询

```text
【入】 search_similar_terms("chest pain", limit=3)

【中】 embed_query("chest pain") → [0.01, -0.03, ... ] (1024 维)
       Milvus COSINE 近邻搜索

【出】 [
   {"input":"chest pain","concept_name":"Chest pain","concept_id":"...",
    "domain_id":"Condition","concept_code":"29857009","FSN":"...","score":0.98},
   {... "concept_name":"Chest wall pain", "score":0.86},
   {... "score":0.81}
 ]
```

## 会被追问 / 诚实局限（★主动说）

- **没有任何 try/except**：Milvus 连不上、collection 没建、网络抖动，`__init__` 或 `search` 直接抛异常崩掉。
  → 面试这么说："当前是 MVP，异常直接冒泡。生产化要加连接重试、collection 存在性检查和降级返回。"
- **`distance → score` 没对度量做适配**：代码默认建库是 COSINE（越大越像）。如果有人把建库度量改成 L2，这里的 `score` 语义和上层 `score >= 0.6` 的过滤就全反了，且不会报错——是个**隐藏耦合**。
  → "score 的方向依赖建库度量，两边必须约定一致。更稳的做法是把 metric 也配置化、在这里统一成'越大越好'的语义。"
- **每 `new` 一个 StdService 都会重新加载模型 + load_collection**。项目靠 `ABBRService` 持有**一个** MedicalRetriever → 一个 StdService 来复用；但如果别处也 `new StdService()`，就会重复加载（这就回到上一题"工厂层缓存"的场景）。
  → 能把这条主动说出来，说明你想过实例生命周期。
- **`limit` 默认 5，但实际调用方传 10**（MedicalRetriever 用 `top_k=10`）。默认值和实际用法不一致，不影响功能但容易让人误读。
- **embedding 配置没走 env**：`MILVUS_URI`/collection 可配置，但 embedding 还是写死 `EmbeddingConfig()` 默认的 bge-m3（回扣第 2 篇局限）。

## 面试怎么说

**合格版（30 秒）**：
> StdService 是检索底座：`__init__` 里建好 embedding 模型、连 Milvus、load collection 复用；`search_similar_terms` 把 query 向量化，用 COSINE 在 Milvus 里做 TopK 近邻搜索，返回带 score 的标准概念列表。它只做向量召回，重排和过滤在上层。

**优秀版（1 分钟）**：
> 这是最底层的向量检索原语，我刻意让它职责单一——只负责"一句话 → 向量 → Milvus TopK → 结构化结果"，不做重排、不做过滤、不懂业务，这样任何要语义搜 SNOMED 的地方都能复用它。重活都在 `__init__` 做一次：造模型、连库、load collection，之后查询复用，不重复加载。score 用的是 COSINE distance，越大越像，上层据此设阈值过滤。配置上 Milvus 地址和 collection 走 env 带默认值，本地直接跑、Docker 用 .env 覆盖。诚实说还缺异常处理，而且 score 方向隐含依赖建库度量是 COSINE，这个耦合我会用配置化 metric 来消除。

## 易错点 / 面试问答

**Q：`data=[query_vector]` 为什么是列表？** A：Milvus 支持一次搜多个向量（批量查询），入参是向量列表。这里只查一个，所以取 `search_result[0]`。

**Q：score 越大越好还是越小？** A：建库用 COSINE，Milvus 返回的 distance 就是余弦相似度，越大越像（约 0~1）。上层用 `score >= 0.6` 过滤。

**Q：StdService 为什么不做过滤和重排？** A：职责单一。它是通用向量检索原语，要可复用；业务相关的重排、domain/score 过滤放上层 MedicalRetriever，避免把通用检索绑死在某个业务上。

**Q：output_fields 为什么不取 vector？** A：只需要 metadata 来用，把 1024 维向量回传没意义、浪费带宽。

**Q：load_collection 为什么放 `__init__`？** A：搜索前 collection 必须在内存里。放 `__init__` 保证 StdService 一建好就能搜，且只 load 一次。

## 一句话总结

> StdService 是运行时的向量检索底座：`__init__` 一次性建模型、连 Milvus、load collection 并复用；`search_similar_terms` 把 query 向量化后做 COSINE TopK 近邻搜索，返回带 score 的标准概念。它职责单一、只管召回，重排过滤交给上层，因而可复用。局限是无异常处理、score 方向隐含依赖建库度量、embedding 配置未走 env——都是清晰可改的工程项。
