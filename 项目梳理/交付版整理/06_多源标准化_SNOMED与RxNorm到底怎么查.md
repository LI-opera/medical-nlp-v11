# 06_多源标准化：SNOMED 与 RxNorm 到底怎么查

> 这一章接着 05 讲：
> 05 已经生成了 `expanded_text`，06 解释每个 `record.expansion` 怎么去查标准医学概念。

---

## 先说结论

V11 不是把所有标准概念放在一个 Milvus collection 里。

当前是两个 collection：

| source | Milvus collection | 用途 |
|---|---|---|
| `snomed` | `concepts_only_name` | 疾病、症状、检查、解剖结构、过程等 |
| `rxnorm` | `rxnorm_concepts` | 药品 |

在线标准化时，系统根据 record 的 `domain` 做路由：

```python
return "rxnorm" if domain == "Drug" else "snomed"
```

所以：

```text
ASA -> aspirin -> domain=Drug -> 查 RxNorm
CP -> chest pain -> domain=Condition -> 查 SNOMED
SOB -> shortness of breath -> domain=Condition -> 查 SNOMED
```

这就是你之前问的那个问题的准确答案：

> 是两个集合，不是一个集合两个字段。

---

## 1. 标准化从哪里开始

标准化发生在：

```text
backend/services/abbr_service.py
ABBRService.expand_verify_with_retry()
```

代码位置在 retry loop 里：

```python
pending = [r for r in records if r["status"] == "PENDING"]
```

也就是说：

```text
只有 PENDING record 才会进入标准化检索。
```

在前几章里，`PENDING` 的意思是：

```text
coverage 已经选出 expansion，但还没绑定标准概念。
```

例如：

```json
{
  "abbreviation": "CP",
  "expansion": "chest pain",
  "domain": "Condition",
  "status": "PENDING",
  "std_cache": null,
  "std_concept": null
}
```

这条 record 接下来要做的事是：

```text
用 chest pain 去标准医学库里找候选概念。
```

---

## 2. ABBRService 先决定查哪个 source

函数：

```text
ABBRService._route_source()
```

代码：

```python
@staticmethod
def _route_source(domain):
    return "rxnorm" if domain == "Drug" else "snomed"
```

它非常短，但很关键。

它把候选扩写阶段得到的 `domain` 转成标准库来源：

| domain | source |
|---|---|
| `Drug` | `rxnorm` |
| `Condition` | `snomed` |
| `Procedure` | `snomed` |
| `Measurement` | `snomed` |
| `Observation` | `snomed` |
| `Spec Anatomic Site` | `snomed` |
| `None` | `snomed` |

所以目前 V11 的策略是：

```text
只有药品单独走 RxNorm。
其他都走 SNOMED。
```

这不是说 SNOMED 不能有药品概念，而是项目为了减少药品映射错误，把药品类缩写单独路由到更合适的 RxNorm。

面试说法：

> V11 做了多源标准化路由。候选扩写阶段会给 expansion 带 domain，标准化时如果 domain 是 Drug 就查 RxNorm，否则查 SNOMED。这样药品和非药品不会混在一个候选空间里互相干扰。

---

## 3. ABBRService 调用 MedicalRetriever

主状态机里对每个 `PENDING` record 调用：

```python
docs = self.retriever.retrieve(
    query=r["expansion"],
    top_k=10,
    domain_filter=None,
    domain_boost=r.get("domain"),
    score_threshold=0.6,
    source=self._route_source(r.get("domain")),
)
```

这里每个参数都很重要：

| 参数 | 示例 | 意义 |
|---|---|---|
| `query` | `chest pain` | 用 expansion 当检索词 |
| `top_k` | `10` | 先取前 10 个候选 |
| `domain_filter` | `None` | 不强制过滤 domain |
| `domain_boost` | `Condition` | domain 匹配时加分 |
| `score_threshold` | `0.6` | 分数过低的候选丢掉 |
| `source` | `snomed` / `rxnorm` | 查哪个 collection |

你可以把这一行理解成：

```text
拿 expansion 去对应标准库查相似概念，再用 domain 做软加分。
```

---

## 4. 为什么是 domain_boost，不是 domain_filter

这里代码传的是：

```python
domain_filter=None
domain_boost=r.get("domain")
```

这说明系统没有强制说：

```text
只要 domain 完全等于 Condition 的结果。
```

而是说：

```text
如果结果 domain 等于 Condition，就加分。
但不匹配也不一定直接删掉。
```

为什么？

因为 NER/domain 不是百分百可靠。

如果强制过滤，可能会把本来正确但 domain 标注不一致的概念过滤掉。

所以 V11 采用的是软约束：

```text
domain_boost 是软偏好，不是硬规则。
```

面试说法：

> domain 在检索阶段主要作为 soft boost，而不是 hard filter。因为医学概念体系里的 domain 标注和 NER label 不一定完全一致，硬过滤可能误伤正确候选。

---

## 5. MedicalRetriever 做什么

文件：

```text
backend/services/medical_retriever.py
```

它处在中间层：

```text
ABBRService
  ↓
MedicalRetriever
  ↓
StdService
  ↓
Milvus
```

它自己不直接连 Milvus，而是调用：

```python
self.std_service.search_similar_terms(
    query=query,
    limit=top_k,
    source=source
)
```

拿到结果后，它做两件事：

1. 规则重排。
2. 过滤低分结果并封装成 documents。

所以 MedicalRetriever 的定位是：

```text
检索适配层 + 规则重排层。
```

不是底层向量库，也不是 LLM。

---

## 6. StdService 才是多源向量底座

文件：

```text
backend/services/std_service.py
```

它初始化时定义两个 collection：

```python
self.collections = {
    "snomed": os.getenv("MILVUS_COLLECTION_NAME", "concepts_only_name"),
    "rxnorm": os.getenv("MILVUS_RXNORM_COLLECTION", "rxnorm_concepts"),
}
```

默认 source：

```python
self.default_source = "snomed"
```

Milvus 地址：

```python
self.milvus_uri = os.getenv("MILVUS_URI", "http://127.0.0.1:19530")
```

embedding 模型：

```python
self.embedding_model = create_embedding_model(EmbeddingConfig())
```

Milvus client：

```python
self.client = MilvusClient(uri=self.milvus_uri)
```

你可以把 `StdService` 理解成：

```text
标准概念向量库客户端。
```

它负责：

- 知道有哪些 collection。
- 加载 collection。
- 把 query 转 embedding。
- 调 Milvus search。
- 把 Milvus 结果转成统一 dict。

---

## 7. StdService 怎么选择 collection

搜索函数：

```python
def search_similar_terms(self, query: str, limit: int = 5, source: str = "snomed"):
    collection = self.collections.get(source, self.collections[self.default_source])
```

这行的意思：

```text
如果 source 是 snomed，就用 concepts_only_name。
如果 source 是 rxnorm，就用 rxnorm_concepts。
如果 source 传错了，就回退到默认 snomed。
```

示例：

```python
search_similar_terms("chest pain", source="snomed")
```

实际查：

```text
collection_name = concepts_only_name
```

示例：

```python
search_similar_terms("aspirin", source="rxnorm")
```

实际查：

```text
collection_name = rxnorm_concepts
```

---

## 8. StdService 在线查询流程

核心代码：

```python
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
```

流程是：

```text
query: chest pain
  ↓
embedding_model.embed_query("chest pain")
  ↓
query_vector
  ↓
Milvus search(collection_name="concepts_only_name")
  ↓
TopK 标准概念候选
```

返回字段：

| 字段 | 含义 |
|---|---|
| `concept_id` | 标准概念 ID |
| `concept_name` | 标准概念名称 |
| `domain_id` | 概念所属域 |
| `concept_code` | 标准编码 |
| `FSN` | Fully Specified Name |
| `score` | Milvus 返回的相似度距离，代码里 round 到 4 位 |

最后统一成：

```json
{
  "input": "chest pain",
  "concept_id": "...",
  "concept_name": "Chest pain",
  "domain_id": "Condition",
  "concept_code": "...",
  "FSN": "...",
  "score": 0.8234
}
```

---

## 9. embedding 模型是什么

配置文件：

```text
backend/utils/embedding_config.py
backend/utils/embedding_factory.py
```

默认配置：

```python
class EmbeddingConfig:
    provider: EmbeddingProvider = EmbeddingProvider.HUGGINGFACE
    model_name: str = "BAAI/bge-m3"
```

创建模型：

```python
return HuggingFaceEmbeddings(
    model_name=config.model_name,
    model_kwargs={
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "trust_remote_code": True
    },
    encode_kwargs={
        "normalize_embeddings": True
    }
)
```

也就是说：

```text
当前向量模型默认是 BAAI/bge-m3。
有 CUDA 就用 GPU，没有就用 CPU。
向量会 normalize。
```

面试说法：

> 标准概念检索用的是 HuggingFace embedding，默认模型是 `BAAI/bge-m3`。查询词和离线概念名用同一个 embedding 模型编码，再通过 Milvus 做向量相似度搜索。

---

## 10. MedicalRetriever 怎么规则重排

`StdService` 返回的是向量相似候选。

但向量分数不一定完美。

所以 `MedicalRetriever._rerank_results()` 会加一些规则分：

| 规则 | bonus |
|---|---:|
| `concept_name` 完全等于 query | `+0.5` |
| `concept_name` 以 query 开头 | `+0.3` |
| `concept_name` 包含 query | `+0.15` |
| `domain_id` 等于 `domain_boost` | `+0.2` |
| 名称较长 | 扣分 |

然后：

```python
item["rerank_score"] = item["score"] + bonus
```

再按 `rerank_score` 从大到小排序。

这一步的直觉是：

```text
如果用户查 chest pain，
名叫 Chest pain 的概念应该比 Chest pain rating / Chest pain management service 更靠前。
```

面试说法：

> 向量召回后我加了一层轻量规则重排，优先提升 exact match、prefix match、contains match 和 domain match，同时对过长概念名做惩罚。这样能减少检索结果里相关但不忠实的候选排到前面。

---

## 11. score_threshold 怎么用

ABBRService 调 retriever 时传：

```python
score_threshold=0.6
```

MedicalRetriever 里：

```python
effective_score = max(item["score"], item.get("rerank_score", item["score"]))
if effective_score < score_threshold:
    continue
```

这说明过滤时不是只看原始向量分数，而是看：

```text
max(raw score, rerank_score)
```

为什么？

因为有些候选：

- raw score 稍低
- 但 exact/domain 规则很强

如果只看 raw score，可能误删。

所以 V11 用的是：

```text
向量分数和规则分数二者取更强信号。
```

注意：这个分数语义依赖 Milvus 返回的 distance 和 embedding/metric 设定，当前项目把它作为“越高越好”的候选分数来使用。

---

## 12. MedicalRetriever 返回给 ABBRService 什么

MedicalRetriever 最终把每个候选封装成：

```python
documents.append({
    "page_content": content,
    "metadata": {
        "input": item["input"],
        "concept_id": item["concept_id"],
        "concept_name": item["concept_name"],
        "domain_id": item["domain_id"],
        "concept_code": item["concept_code"],
        "score": item["score"],
        "rerank_score": item["rerank_score"]
    }
})
```

`page_content` 是给人/LLM 更容易看的文本：

```text
Concept Name:Chest pain
Fully Specified Name:...
Domain:Condition
Concept Code:...
```

`metadata` 是给代码结构化使用的字段。

ABBRService 会把 `docs[:10]` 写入 record 的 `std_cache`：

```python
r["std_cache"] = [
    {
        "concept_id": d["metadata"]["concept_id"],
        "concept_name": d["metadata"]["concept_name"],
        "domain_id": d["metadata"]["domain_id"],
        "concept_code": d["metadata"]["concept_code"],
        "score": d["metadata"]["score"],
        "rerank_score": d["metadata"].get("rerank_score"),
    }
    for d in docs[:10]
]
```

所以 `std_cache` 的含义是：

```text
这个 expansion 查到的标准概念候选列表。
```

还不是最终标准概念。

最终标准概念要等下一章 verifier 来选。

---

## 13. 用 ASA、CP、SOB 走一遍

原句：

```text
The patient took ASA for CP and denies SOB.
```

经过 04、05 后 records 大概是：

```json
[
  {
    "abbreviation": "ASA",
    "expansion": "aspirin",
    "domain": "Drug",
    "status": "PENDING"
  },
  {
    "abbreviation": "CP",
    "expansion": "chest pain",
    "domain": "Condition",
    "status": "PENDING"
  },
  {
    "abbreviation": "SOB",
    "expansion": "shortness of breath",
    "domain": "Condition",
    "status": "PENDING"
  }
]
```

### ASA

```text
domain = Drug
_route_source("Drug") = rxnorm
query = aspirin
collection = rxnorm_concepts
```

检索后：

```json
{
  "abbreviation": "ASA",
  "expansion": "aspirin",
  "std_cache": [
    {
      "concept_name": "aspirin",
      "domain_id": "Drug",
      "concept_code": "...",
      "score": 0.91,
      "rerank_score": 1.41
    }
  ]
}
```

### CP

```text
domain = Condition
_route_source("Condition") = snomed
query = chest pain
collection = concepts_only_name
```

检索后：

```json
{
  "abbreviation": "CP",
  "expansion": "chest pain",
  "std_cache": [
    {
      "concept_name": "Chest pain",
      "domain_id": "Condition",
      "concept_code": "...",
      "score": 0.86,
      "rerank_score": 1.56
    }
  ]
}
```

### SOB

```text
domain = Condition
_route_source("Condition") = snomed
query = shortness of breath
collection = concepts_only_name
```

检索后：

```json
{
  "abbreviation": "SOB",
  "expansion": "shortness of breath",
  "std_cache": [
    {
      "concept_name": "Shortness of breath",
      "domain_id": "Condition",
      "concept_code": "...",
      "score": 0.84,
      "rerank_score": 1.34
    }
  ]
}
```

上面是结构示意，不是本机真实运行输出。真实候选和分数取决于本地 Milvus 数据、embedding 模型和 collection 内容。

---

## 14. 离线建库和在线查询不要混

这一点很容易混乱。

### 离线建库

脚本：

```text
backend/tools/rebuild_milvus.py
backend/tools/rebuild_rxnorm_milvus.py
```

作用：

```text
CSV
  ↓
concept_name
  ↓
embedding
  ↓
Milvus collection
```

SNOMED：

```text
backend/data/snomed_clinical.csv
  → concepts_only_name
```

RxNorm：

```text
backend/data/rxnorm_clinical.csv
  → rxnorm_concepts
```

### 在线查询

服务：

```text
StdService.search_similar_terms()
```

作用：

```text
query expansion
  ↓
embedding
  ↓
Milvus search
  ↓
候选标准概念
```

在线请求不会重新建库。

面试说法：

> 离线阶段把 SNOMED 和 RxNorm CSV 分别向量化后写入两个 Milvus collection；在线阶段只根据 expansion 生成 query embedding，然后到对应 collection 里 search，不会在请求时建库。

---

## 15. 两个建库脚本分别做什么

### SNOMED 建库

脚本：

```text
backend/tools/rebuild_milvus.py
```

输入：

```text
backend/data/snomed_clinical.csv
```

输出 collection：

```text
concepts_only_name
```

自测 query：

```text
chest pain
```

### RxNorm 建库

脚本：

```text
backend/tools/rebuild_rxnorm_milvus.py
```

输入：

```text
backend/data/rxnorm_clinical.csv
```

输出 collection：

```text
rxnorm_concepts
```

自测 query：

```text
aspirin
```

两者 schema 基本一致：

| 字段 | 用途 |
|---|---|
| `id` | Milvus 主键 |
| `concept_id` | 标准概念 ID |
| `concept_name` | 概念名，也是 embedding 的主要文本 |
| `domain_id` | 概念域 |
| `concept_code` | 标准编码 |
| `FSN` | 完整名称 |
| `vector` | 概念名向量 |

区别主要是：

```text
数据来源不同，collection 名不同。
```

---

## 16. 为什么不把 SNOMED 和 RxNorm 混在一起

可以混，但 V11 没这么做。

分成两个 collection 的好处：

1. 药品和非药品的候选空间更干净。
2. `aspirin` 这类药品不会在 SNOMED 疾病/症状候选里乱撞。
3. 后续可以给不同 source 配不同数据、字段、阈值或 rerank 策略。
4. 面试时更容易解释“多源标准化”。

代价是：

1. 要维护两个建库脚本或两套数据准备流程。
2. 路由错了就可能查错库。
3. 如果某个实体 domain 判断错，候选召回也会受影响。

所以 V11 目前用一个简单但清晰的路由：

```text
Drug → RxNorm
其他 → SNOMED
```

这是项目当前合理的工程折中。

---

## 17. 这章和前后章节怎么连起来

前一章 05：

```text
record.expansion + records 状态
  ↓
expanded_text
```

本章 06：

```text
record.expansion + record.domain
  ↓
source = snomed / rxnorm
  ↓
MedicalRetriever
  ↓
StdService
  ↓
Milvus
  ↓
std_cache
```

下一章要讲：

```text
std_cache
  ↓
ABBVerifier.verify_mappings()
  ↓
std_concept / CODED / WITHHELD
```

所以目前主链路已经走到：

```text
候选选择
  → 确定性替换
  → 多源标准概念召回
```

---

## 18. 面试怎么讲这章

30 秒版本：

> 标准化阶段我做了多源路由。每个缩写通过 coverage 后会带一个 expansion 和 domain，如果 domain 是 Drug，就查 RxNorm collection；否则查 SNOMED collection。底层 `StdService` 维护了两个 Milvus collection：`concepts_only_name` 和 `rxnorm_concepts`。在线查询时用 `BAAI/bge-m3` 把 expansion 编码成向量，到对应 collection 搜索，再由 `MedicalRetriever` 做 exact match、contains match、domain boost 等规则重排，结果写入每条 record 的 `std_cache`。

2 分钟版本：

> 扩写完成后，系统要把 expansion 映射到标准医学概念。V11 不是把所有概念放在一个 collection，而是维护了 SNOMED 和 RxNorm 两个 Milvus collection。`ABBRService` 会根据 record 的 domain 做路由：`Drug` 走 `rxnorm`，其他走 `snomed`。比如 `ASA -> aspirin` 会查 RxNorm，`CP -> chest pain` 会查 SNOMED。
>
> 具体调用链是 `ABBRService -> MedicalRetriever -> StdService -> Milvus`。`StdService` 是底层向量库客户端，负责维护 source 到 collection 的映射，加载 collection，用 `BAAI/bge-m3` 生成 query embedding，然后调用 Milvus search。`MedicalRetriever` 是检索适配层，它拿到向量召回结果后做规则重排，比如 exact match 加分、prefix/contains 加分、domain match 加分、过长概念名扣分，然后再按阈值过滤。
>
> 检索结果不会直接变成最终概念，而是先写入 record 的 `std_cache`。下一步 verifier 会在这些候选中判断哪个 concept 和 expansion 是忠实映射。如果没有忠实候选，就进入 `WITHHELD` 或反思重检索。

---

## 19. 你要记住的 8 句话

1. V11 是两个 collection：`concepts_only_name` 和 `rxnorm_concepts`。
2. `Drug` 走 RxNorm，其他走 SNOMED。
3. `ABBRService._route_source()` 负责把 domain 转成 source。
4. `MedicalRetriever` 是检索适配层和规则重排层。
5. `StdService` 才是连接 embedding 和 Milvus 的底座。
6. embedding 默认是 `BAAI/bge-m3`。
7. 检索结果先进 `std_cache`，还不是最终标准概念。
8. 最终概念要等下一步 verifier 从 `std_cache` 里选。

---

## 20. 下一章建议

下一章建议写：

```text
07_verifier忠实性校验_为什么不直接相信向量Top1.md
```

因为现在我们已经有了：

```text
std_cache = 标准概念候选
```

下一步最重要的问题是：

```text
为什么不能直接取向量检索 Top1？
verifier 到底判断什么？
chosen_index 怎么变成 std_concept？
为什么会出现 WITHHELD？
```

