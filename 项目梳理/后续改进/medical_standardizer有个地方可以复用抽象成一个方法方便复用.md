- 检索 + 取前 3"的逻辑被复制了两份：这里对实体检索，ABBRService 里对每个 expansion 检索，两段代码几乎一字不差（`top_k=10, score≥0.6, docs[:3]`，连 candidate 字段都一样），没抽成公共函数。违背 DRY。 → 面试这么说："这块检索+取前3的逻辑出现了两处，是重复代码。我会抽成一个公共方法（比如 `retrieve_top_candidates`），两边都调，避免参数改一处漏一处。"这是什么意思我没明白，我的ABBRService里面不是用的就是meidical_standardizer吗不是整合成一个模块去用了

Show more





## Claude responded: 你的理解只对了一半,我把代码摆出来你立刻就懂。关键是:ABBRService 里其实做了"两次检索",只有第一次用了 standardizer,第二次是它自己又写了一遍。

Thought process

你的理解只对了一半,我把代码摆出来你立刻就懂。关键是:**ABBRService 里其实做了"两次检索",只有第一次用了 standardizer,第二次是它自己又写了一遍。**

### ABBRService 主链路里真实的两段

在 `expand_verify_with_retry` 里:

python

```python
# 第①次检索：对"整句"做标准化 —— 这次确实用了 standardizer
standardization_result = self.standardizer.standardize(current_expanded_text)

# 第②次检索：对"每个 expansion"单独查 SNOMED —— 这次没用 standardizer，自己写了一遍
mapping_standardizations = []
for mapping in valid_mappings:
    expansion = mapping.get("expansion")
    docs = self.retriever.retrieve(          # ← 直接调 retriever，不走 standardizer
        query=expansion, top_k=10, domain_filter=None, score_threshold=0.6
    )
    candidates = []
    for doc in docs[:3]:                     # ← 取前 3
        metadata = doc["metadata"]
        candidates.append({
            "concept_id": metadata["concept_id"],
            "concept_name": metadata["concept_name"],
            "domain_id": metadata["domain_id"],
            "concept_code": metadata["concept_code"],
            "score": metadata["score"],
            "rerank_score": metadata.get("rerank_score"),
        })
    mapping_standardizations.append({...})
```

### MedicalStandardizer 内部的那段

python

```python
# medical_standardizer.py
for entity in entities:
    docs = self.retriever.retrieve(          # ← 一模一样
        query=entity["text"], top_k=10, domain_filter=None, score_threshold=0.6
    )
    candidates = []
    for doc in docs[:3]:                     # ← 一模一样
        metadata = doc["metadata"]
        candidates.append({
            "concept_id": metadata["concept_id"],
            "concept_name": metadata["concept_name"],
            "domain_id": metadata["domain_id"],
            "concept_code": metadata["concept_code"],
            "score": metadata["score"],
            "rerank_score": metadata.get("rerank_score"),
        })
```

**看到了吗?** 中间这块"`retrieve(top_k=10, score≥0.6)` → `docs[:3]` → 拼那 6 个字段的 candidate"——在两个文件里**逐字重复**。这就是 DRY 违背的地方,跟"ABBRService 有没有用 standardizer"是两码事。

### 为什么会变成这样(澄清你的困惑)

你以为"ABBRService 用了 standardizer 就等于复用了检索逻辑",但实际上 ABBRService 需要**两种不同粒度**的检索:

|       | 查什么                  | 用谁                             | 产出                               |
| ----- | ----------------------- | -------------------------------- | ---------------------------------- |
| 第①次 | **整句**所有实体        | `standardizer.standardize()`     | `standardization`(整句的)          |
| 第②次 | **每个 expansion** 单独 | 直接 `self.retriever.retrieve()` | `mapping_standardizations`(逐项的) |

第②次它**没有复用 standardizer**(因为 standardizer 是"先 NER 再查",而这里输入已经是确定的 expansion 词、不需要 NER),于是作者把 standardizer 内部那段"查+取前3"的代码**复制粘贴**了一份到 ABBRService 里。

> 注意:**"做两次检索"本身是合理的**(整句 vs 逐项,目的不同)。不合理的只是——那段"查 SNOMED 候选并取前 3 拼字段"的**公共动作**被抄了两遍,而不是抽成一个函数。

### 改进:抽成一个公共方法

把重复那段提成一个工具函数,两处都调它:

python

```python
def retrieve_top_candidates(retriever, query, top_k=10, score_threshold=0.6, keep=3):
    docs = retriever.retrieve(query=query, top_k=top_k,
                              domain_filter=None, score_threshold=score_threshold)
    return [{
        "concept_id": d["metadata"]["concept_id"],
        "concept_name": d["metadata"]["concept_name"],
        "domain_id": d["metadata"]["domain_id"],
        "concept_code": d["metadata"]["concept_code"],
        "score": d["metadata"]["score"],
        "rerank_score": d["metadata"].get("rerank_score"),
    } for d in docs[:keep]]
```

之后:

- `MedicalStandardizer` 里:`candidates = retrieve_top_candidates(self.retriever, entity["text"])`
- `ABBRService` 里:`candidates = retrieve_top_candidates(self.retriever, expansion)`

好处:参数(比如把 `score≥0.6` 改成 `0.7`、前 3 改成前 5)**只改一处**,不会出现"改了 standardizer 忘了改 ABBRService"导致两边行为不一致的 bug。这就是 DRY(Don't Repeat Yourself)。

------

所以一句话:**你没用错 standardizer,只是 ABBRService 还额外有一段没复用、靠复制的检索代码。** 等我们写到第 14 篇 ABBRService 时,你会在源码里亲眼看到这两段并存。