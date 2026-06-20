- 串行检索：实体越多越慢，每个实体一次 embedding + 一次 Milvus。可以批量优化。这个怎么优化





## Claude responded: 这个优化是真有料的一题,而且你项目里已经埋好了批量的接口(还记得第 4 篇 data=[query_vector] 为什么套 list 吗?

Thought process

这个优化是真有料的一题,而且你项目里**已经埋好了批量的接口**(还记得第 4 篇 `data=[query_vector]` 为什么套 list 吗?就是因为 Milvus 支持一次查多个)。我分两种优化讲,批量是主力。

### 现在为什么慢

python

```python
for entity in entities:                          # N 个实体
    docs = self.retriever.retrieve(query=entity["text"], ...)
    #          ↓ 内部
    #   embed_query(一个词)   ← 第 1 次 embedding 调用
    #   client.search(data=[一个向量])  ← 第 1 次 Milvus 往返
```

N 个实体 = **N 次 embedding + N 次 Milvus 往返**,而且是**一个接一个串着跑**。每次 Milvus 往返都有固定的网络/调度开销,embedding 模型也是"喂一条"远比"喂一批"低效(向量化计算的并行性没用上)。

### 优化一:批量(batch)—— 主力,推荐

核心思想:**把 N 次合并成 1 次。**

python

```python
# ① 一次性把所有实体文本拿出来
texts = [e["text"] for e in entities]

# ② 批量 embedding：一次调用算出 N 个向量（而不是 N 次 embed_query）
vectors = self.embedding_model.embed_documents(texts)   # langchain 的批量接口

# ③ 批量 Milvus 搜索：一次往返查 N 个向量
search_result = self.client.search(
    collection_name=...,
    data=vectors,          # ← 直接传 N 个向量的列表（这就是当初套 list 的意义）
    anns_field="vector",
    limit=10,
    output_fields=[...]
)
# search_result[i] 就是第 i 个实体的结果，和 entities[i] 一一对应

# ④ 再逐个 rerank/过滤（rerank 要用各自的 query，所以这步仍按实体分别做）
for i, entity in enumerate(entities):
    reranked = self._rerank_results(entity["text"], parse(search_result[i]))
    ...
```

收益:**N 次 embedding → 1 次,N 次 Milvus 往返 → 1 次**。实体多的时候(比如一句话 5-8 个实体)能快好几倍。

注意点:

- **rerank 必须按各自 query 分别做**(第 5 篇的重排规则依赖 query 字符串),所以第④步还是 per-entity 的——但那是纯内存计算,不耗 I/O,不影响大头。
- 要改 `StdService` 和 `MedicalRetriever` 的签名,让它们**支持"传一批 query"**(加个 `search_similar_terms_batch`),不能只接一个词。这是主要改动量。

### 优化二:并发(如果不想改成批量)

如果短期不想动批量逻辑,可以让 N 次调用**并行**而不是串行——用线程池让多次 Milvus 往返的等待时间重叠:

python

```python
from concurrent.futures import ThreadPoolExecutor
with ThreadPoolExecutor(max_workers=8) as pool:
    all_docs = list(pool.map(lambda e: self.retriever.retrieve(e["text"]), entities))
```

但这只是"让等待重叠",不如批量从根上减少调用次数。**能批量就别只靠并发。**

### 优化三:缓存(锦上添花)

医学实体高频重复(`chest pain`、`hypertension` 几乎每个病例都有)。给检索结果加一层缓存(`实体文本 → 候选`),命中就不查了:

python

```python
if entity_text in self._cache: return self._cache[entity_text]
```

跨请求复用,对 Benchmark 这种批量场景特别明显。

### 三者怎么选

| 方案     | 收益         | 改动量     | 适用               |
| -------- | ------------ | ---------- | ------------------ |
| **批量** | 最大(N→1)    | 中(改签名) | 首选,尤其实体多    |
| 并发     | 中(等待重叠) | 小         | 懒得改批量时的过渡 |
| 缓存     | 看重复率     | 小         | 高频实体/Benchmark |

### 面试怎么说

> "现在每个实体一次 embedding 加一次 Milvus 往返,串行,实体多就慢。优化首选批量——embedding 用 `embed_documents` 一次算 N 个向量,Milvus 的 search 本来就支持 `data=[多个向量]` 一次往返查 N 个,把 N 次 I/O 压成 1 次,只有 rerank 因为依赖各自 query 还得逐个做,但那是纯内存运算。改动是给 StdService 加一个批量检索接口。退一步也可以用线程池让多次调用并发,或对高频实体加缓存,但批量是从根上减少调用次数的最优解。"

这个回答能体现你懂"**I/O 批量 > 并发 > 串行**"的性能直觉,是后端/RAG 工程的常见考点。