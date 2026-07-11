# MedicalRetriever —— 检索层与规则重排 · V11

> 文件:`backend/services/medical_retriever.py`(约 120 行,薄包装但很关键)
> 衔接:它夹在 `StdService` 和上层标准化/缩写主编排之间。下面的 `StdService` 只会"按 source 去 Milvus 搜相似概念";上面的 `ABBRService` / `MedicalStandardizer` 需要的是更像 RAG document 的结果,并且希望 exact match、domain match、短术语优先。所以 MedicalRetriever 就负责**拿底层检索结果,做轻量规则重排、过滤、包装**。
> **V11 变化(必看)**:它从"只查 SNOMED 的 retriever"升级成支持 `source` 透传的多源 retriever。`ABBRService._route_source(domain)` 决定 Drug→RxNorm / 其它→SNOMED,然后 `MedicalRetriever.retrieve(..., source=...)` 把这个选择一路传给 `StdService.search_similar_terms()`。

## 核心速记

> 1. **一句定位**:MedicalRetriever 是 RAG 里的 retriever 层,但它不生成答案、不做医学判断,只负责"检索 + 重排 + 包装成 documents"。
> 2. **它比 StdService 多做三件事**:规则重排(`rerank_score`)、可选过滤(`domain_filter` / `score_threshold`)、结果包装(`page_content` + `metadata`)。
> 3. **V11 的 source 透传很关键**:`retrieve(query, ..., source="rxnorm")` → `StdService.search_similar_terms(query, source="rxnorm")`。也就是说多源路由的选择不是在这里判断,但这里负责把选择传到底。
> 次要(trivia):`domain_filter` 是硬过滤,`domain_boost` 是软加分;主链路用的是 `domain_boost`,不是硬过滤,避免把可能正确但 domain 标注不一致的候选过早删掉。

## 这一段在解决什么

大白话:**StdService 只知道"向量相似",MedicalRetriever 负责让检索结果更像人想要的医学候选列表。**

比如搜索:

```text
query = "chest pain"
```

底层向量检索可能返回很多相似概念,其中有:

```text
Chest pain
Chest pain rating
History of chest pain
Pain in chest
```

向量分数高不代表一定最适合。MedicalRetriever 会额外加规则:

- 概念名完全等于 query → 加分最多;
- 概念名以 query 开头 → 加一点;
- 概念名包含 query → 加一点;
- domain 和预期一致 → 加一点;
- 名字太长 → 扣一点。

最后它把结果变成:

```python
{
  "page_content": "Concept Name:Chest pain\nFully Specified Name:...\nDomain:Condition\nConcept Code:...",
  "metadata": {
    "concept_id": "...",
    "concept_name": "Chest pain",
    "domain_id": "Condition",
    "concept_code": "...",
    "score": 0.91,
    "rerank_score": 1.41
  }
}
```

这就是上层 verifier / benchmark 更方便消费的格式。

## 核心1 · 它是 StdService 的上层薄包装

初始化非常简单:

```python
class MedicalRetriever:
    def __init__(self):
        self.std_service = StdService()
```

含义:

```text
MedicalRetriever
  持有 StdService
    持有 embedding model
    持有 MilvusClient
    持有 collections 字典
```

所以每创建一个 `MedicalRetriever`,都会创建一个 `StdService`,进而连接 Milvus、加载 embedding、load 默认 collection。

这也是为什么主链路里 `ABBRService.__init__` 会把 `self.retriever = MedicalRetriever()` 放在初始化阶段复用,而不是每次请求临时创建。

## 核心2 · retrieve() 的完整流程

主函数:

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
    results = self.std_service.search_similar_terms(
        query=query,
        limit=top_k,
        source=source
    )
    results = self._rerank_results(query, results, domain_boost)
    ...
    return documents
```

流程图:

```text
query + source
  ↓
StdService.search_similar_terms()
  ↓
Milvus top_k 原始候选
  ↓
_rerank_results(query, results, domain_boost)
  ↓
domain_filter 硬过滤(可选)
  ↓
score_threshold 过滤(可选)
  ↓
包装成 documents
```

注意:它不会自己决定 `source` 是 `snomed` 还是 `rxnorm`。主链路里这个决策来自:

```python
ABBRService._route_source(domain)
```

MedicalRetriever 的职责是接住这个 source,然后传给 StdService。

## 核心3 · 规则重排:让"像答案的结果"排前面

重排函数:

```python
def _rerank_results(self, query, results, domain_boost=None):
    query_lower = query.lower()
    for item in results:
        concept_name = item["concept_name"].lower().strip()
        bonus = 0.0

        if concept_name == query_lower:
            bonus += 0.5
        elif concept_name.startswith(query_lower):
            bonus += 0.3
        elif query_lower in concept_name:
            bonus += 0.15

        if domain_boost is not None and item.get("domain_id") == domain_boost:
            bonus += 0.2

        word_count = len(concept_name)
        if word_count > 10:
            bonus -= 0.25
        elif word_count > 6:
            bonus -= 0.15
        elif word_count > 4:
            bonus -= 0.08

        item["rerank_score"] = item["score"] + bonus

    results.sort(key=lambda x: x["rerank_score"], reverse=True)
    return results
```

### 加分规则

```text
完全同名:      +0.5
以 query 开头: +0.3
包含 query:    +0.15
domain 命中:   +0.2
```

为什么要这样?

- 向量检索会召回语义相近结果,但不一定把"字面完全一致"排第一;
- 医学标准化里,如果 expansion 是 `chest pain`,那概念名刚好叫 `Chest pain` 通常应该优先;
- domain boost 能把 `Condition` / `Drug` 这类领域信号加入排序,但不把其它领域硬删掉。

### 扣分规则

```text
len(concept_name) > 10: -0.25
len(concept_name) > 6:  -0.15
len(concept_name) > 4:  -0.08
```

这里代码变量叫 `word_count`,但实际用的是:

```python
len(concept_name)
```

也就是**字符长度**,不是单词数量。这个命名有点误导,但意图是"长概念名可能加了限定词,要稍微降权"。

例如:

```text
Chest pain                    短,更像标准概念本体
Chest pain rating             多了 rating,可能是量表/评分
History of chest pain         多了 history,语义变了
```

扣长术语不是绝对医学规则,只是一个轻量启发式。

## 核心4 · domain_filter vs domain_boost 千万别混

这两个参数很像,但作用完全不同。

### domain_filter:硬过滤

```python
if domain_filter is not None and item["domain_id"] != domain_filter:
    continue
```

含义:

```text
只保留 domain_id == domain_filter 的候选
其它全部删掉
```

适合测试或非常确定领域的场景。比如:

```python
retriever.retrieve(
    query="chest pain",
    domain_filter="Condition"
)
```

风险:如果库里的 domain 标错、候选本身跨域、或者目标概念 domain 和你预期不完全一致,硬过滤可能直接删掉正确答案。

### domain_boost:软加分

```python
if domain_boost is not None and item.get("domain_id") == domain_boost:
    bonus += 0.2
```

含义:

```text
domain_id 命中就加分
不命中也保留
```

V11 主链路用的是这个:

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

为什么主链路选软加分?

因为医疗概念 domain 不是永远完美。V11 更保守地让 domain 参与排序,但不让它一票否决。

一句话:

```text
domain_filter = 错了就可能删答案
domain_boost  = 对了就往前排,错了也先留着给 verifier 判断
```

## 核心5 · score_threshold 用的是 raw/rerank 双口径

过滤代码:

```python
if score_threshold is not None:
    effective_score = max(item["score"], item.get("rerank_score", item["score"]))
    if effective_score < score_threshold:
        continue
```

这个细节很重要。

以前如果只看 raw score,可能出现:

```text
raw score 稍低
但 exact match / domain boost 后 rerank_score 很高
```

如果仍按 raw score 过滤,好候选会先被删掉。现在用:

```text
effective_score = max(raw score, rerank_score)
```

含义是:只要原始向量分数或重排后分数任一过线,就保留。

这让"重排"和"过滤"口径一致,避免一边把候选排上去,另一边又把它删掉。

## 核心6 · 输出为什么包装成 documents

最终返回:

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
        "rerank_score": item["rerank_score"],
    }
})
```

这是一种 RAG 常见格式:

```text
page_content: 给 LLM / 人看的文本描述
metadata: 给程序稳定读取的结构化字段
```

在 V11 主链路里,`ABBRService` 主要读取 metadata:

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

也就是说 `page_content` 更多是 RAG 风格保留/调试可读性,真正进入 verifier 的是结构化候选列表。

## V11 主链路里它在哪里

在 `ABBRService.expand_verify_with_retry()` 里:

```text
coverage 选出 expansion
  ↓
record.status = PENDING
  ↓
MedicalRetriever.retrieve(
    query=expansion,
    top_k=10,
    domain_boost=domain,
    score_threshold=0.6,
    source=_route_source(domain)
)
  ↓
std_cache = docs[:10] 的 metadata
  ↓
ABBVerifier.verify_mappings() 在 std_cache 里选 chosen_index
```

反思阶段也会再次调用它:

```text
propose_requeries()
  ↓
对每个新检索词 MedicalRetriever.retrieve(...)
  ↓
合并新候选池
  ↓
verify_mappings() 再选一次
```

所以 MedicalRetriever 是标准概念候选池的主要来源。它本身不决定哪个概念最终正确,但它决定 verifier 能看到哪些候选、候选排序大概如何。

## 数据快照

```text
输入:
  query: str                       # expansion 或 NER entity
  top_k: int                       # 主链路常用 10
  domain_filter: str | None         # 硬过滤,主链路不用
  domain_boost: str | None          # 软加分,主链路用
  score_threshold: float | None     # 主链路常用 0.6
  source: "snomed" | "rxnorm"       # V11 多源透传

中间:
  StdService 返回 list[dict]
  _rerank_results 添加 rerank_score 并排序

输出:
  list[dict]
  每条 = {
    page_content: str,
    metadata: {
      input,
      concept_id,
      concept_name,
      domain_id,
      concept_code,
      score,
      rerank_score
    }
  }
```

## 调用方地图

### 生产主链路

```text
backend/services/abbr_service.py
  - 初次标准化检索
  - 反思重检索
```

### 早期/辅助标准化路径

```text
backend/services/medical_standardizer.py
  - 对 NER 抽出的实体逐个检索候选
```

### 评估与分析

```text
backend/evaluation/concept_match.py
backend/evaluation/run_concept_benchmark.py
backend/evaluation/run_source_ab.py
backend/evaluation/error_triage.py
```

### 实验图包装

```text
backend/graph/standardization_graph.py
```

这些调用说明它是一个共享底座。改它的规则会同时影响主链路、benchmark、concept benchmark、error triage 和 LangGraph 实验。

## 其余细节(次要,一行带过)

【次要】`top_k` 默认 5,但主链路通常传 10;`page_content` 里的 `FSN` 来自 StdService output_fields;`source` 默认 snomed,所以老调用不传 source 时行为向后兼容;`domain_filter` 在测试脚本里更常见,主链路更偏向 domain_boost。

## 死代码 / 盲肠提醒

- 本文件没有明显死代码,但有一个**命名误导**:`word_count = len(concept_name)` 实际是字符数,不是词数。若继续维护,建议改名为 `name_length` 或真的用 `len(concept_name.split())`。
- `domain_filter` 在主链路没有用,但不是死代码。测试、旧路径或人工调试可以用它做硬过滤。
- `page_content` 当前主链路基本不依赖,主要用 metadata。它保留 RAG document 形状,对调试和未来直接喂 LLM 有用。

## 优化方向(更好 / 更稳)

1. **把重排权重常量化**:现在 `+0.5/+0.3/+0.15/+0.2/-0.25` 都写死在函数里。可以抽成配置,方便 ablation。
2. **修正长度惩罚命名**:`word_count` 改为 `name_length`,或者真的按单词数惩罚,避免维护者误解。
3. **让 rerank_score 更可解释**:返回 bonus 明细,例如 `exact_bonus/domain_bonus/length_penalty`,方便错误分析知道为什么某个候选排第一。
4. **按 source 定制重排规则**:SNOMED 和 RxNorm 的概念命名风格不同,药品库可能不应该完全沿用疾病库的长度惩罚。
5. **加入候选去重**:如果 Milvus 返回同义或重复 concept_id,可以在 retriever 层去重,让 verifier 看到更干净的候选池。
6. **支持更精细 filter**:未来如果 Milvus 里有 concept_class_id / vocabulary_id / standard_concept 等字段,可以在 retriever 层做更可靠的过滤或加权。

## 会被追问 / 诚实局限(主动说)

- **重排是启发式,不是训练出来的 ranker**。它靠 exact/prefix/substring/domain/长度这些规则,好处是透明,坏处是权重未系统学习。
- **domain_boost 依赖上游 domain 标签**。如果 `abbr_candidates.py` 的 domain 写错,这里会把错误领域加分。
- **score_threshold 不是医学可信度阈值**。它只是向量相似/重排分过滤阈值,最终医学忠实度还要 verifier 判断。
- **候选质量决定 verifier 上限**。如果 retriever 没召回正确概念,verifier 不能凭空创造标准概念。

## 面试怎么说

**合格版(30 秒)**:
> MedicalRetriever 是向量检索上面的一层 retriever。底层 StdService 只负责 embedding 和 Milvus search,MedicalRetriever 会对结果做规则重排,比如 exact match、prefix、substring、domain boost 和长术语惩罚,再按阈值过滤并包装成 RAG document。它不判断最终哪个概念正确,只是给 verifier 提供候选池。

**优秀版(1 分钟)**:
> 我把检索分成两层:StdService 是物理检索层,只管把 query 编码后到指定 Milvus collection 搜;MedicalRetriever 是语义候选层,它在 raw vector score 上加了一层透明的规则重排。比如概念名和 expansion 完全一致会加 0.5,同领域会加 0.2,过长概念会扣分。这里我刻意用 domain_boost 而不是 domain_filter,因为医学库的 domain 标注和扩写 domain 不一定百分百对齐,硬过滤可能误删正确答案。V11 还让 retriever 支持 source 透传,Drug 的 expansion 可以走 RxNorm,其它默认走 SNOMED。最后 verifier 只在这些候选里选择忠实概念或弃码,所以 retriever 的职责是高质量召回和排序,不是最终裁判。

## 易错点 / 面试问答

**Q:MedicalRetriever 和 StdService 有什么区别?**  
A:StdService 是底层执行器,只做 embedding + Milvus search。MedicalRetriever 是上层检索器,做规则重排、过滤和 document 包装。

**Q:domain_filter 和 domain_boost 的区别?**  
A:domain_filter 是硬过滤,不匹配就删;domain_boost 是软加分,命中就排前,不命中仍保留。V11 主链路用 domain_boost。

**Q:rerank_score 是怎么来的?**  
A:Milvus raw score 加规则 bonus/penalty。完全同名、前缀、包含、domain 命中会加分,概念名太长会扣分。

**Q:为什么不直接相信 Milvus score?**  
A:向量相似度能找语义接近概念,但医学标准化里字面精确匹配、领域一致、是否多了限定词都很重要。规则重排把这些可解释信号补进去。

**Q:为什么 source 不在 MedicalRetriever 里判断?**  
A:因为路由决策属于上层业务逻辑。`ABBRService` 根据候选 domain 判断 Drug→RxNorm / 其它→SNOMED,MedicalRetriever 只负责把 source 透传到底层检索。

**Q:如果正确概念没召回怎么办?**  
A:第一次 verifier 可能弃码,然后反思阶段会让 LLM 提出同义/规范检索词,再用 MedicalRetriever 重检索并重新 verify。但如果多轮仍召不回,系统应该 WITHHELD,不能编造概念。

## 一句话总结

> MedicalRetriever 是 V11 标准概念候选池的"检索加工层":它调用 StdService 到 SNOMED/RxNorm 搜原始相似概念,再用 exact/prefix/substring/domain_boost/长度惩罚做透明重排,用 score_threshold 做过滤,最后包装成带 metadata 的 document 给 ABBRService 和 verifier 使用。它不负责最终医学判断,但它决定 verifier 能看到哪些候选,所以是整条标准化链路质量上限的重要一环。
