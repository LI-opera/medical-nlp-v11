# MedicalStandardizer —— 整句标准化旧编排 / 辅助能力层 · V11

> 文件:`backend/services/medical_standardizer.py`(约 55 行,非常薄)
> 衔接:前两篇讲了 `NERService` 如何抽医学实体、`MedicalRetriever` 如何检索标准概念。MedicalStandardizer 就是把这两个模块拼起来:整句文本 → NER 抽实体 → 每个实体检索候选概念 → 返回结构化标准化结果。
> **V11 必看定位变化**:它在 V9 时更像"标准化主编排";但在 V11 当前主链路里,`ABBRService.expand_verify_with_retry()` 并没有调用 `standardize()`。`ABBRService` 只是初始化 `MedicalStandardizer()` 后复用其中的 `ner_service`,用于 fallback 候选的 domain 推断。也就是说,MedicalStandardizer 现在更像**保留的整句标准化能力 / 旧编排 / 测试辅助模块**,不是 `/expand/simple` 最终标准化结果的主来源。

## 核心速记

> 1. **一句定位**:MedicalStandardizer 是"NER + Retriever"的薄编排器,自己不做识别、不做向量检索、不做 verifier 判断。
> 2. **标准流程**:`text → NERService.extract_entities() → 每个 entity 调 MedicalRetriever.retrieve(top_k=10, score_threshold=0.6) → 每个实体取前 3 个候选`。
> 3. **V11 当前真实地位**:`standardize()` 保留但主 API 不直接用;当前 `ABBRService` 主要复用 `self.standardizer.ner_service`。
> 次要(trivia):`standardization_result` 在 `ABBRService.expand_verify_with_retry()` 里初始化为 `None`,后面只是被放进返回结构,没有被本类填充。

## 这一段在解决什么

大白话:**把一句话里的医学实体都找出来,再给每个实体配几个可能的标准概念候选。**

例如:

```text
输入:
"The patient has chest pain and hypertension."

MedicalStandardizer 做:
1. NER 抽出:
   chest pain
   hypertension

2. 每个实体单独检索:
   chest pain    → [Chest pain, Pain in chest, ...]
   hypertension  → [Hypertensive disorder, Hypertension, ...]

3. 返回:
   每个实体 + NER label/score + Top-3 候选概念
```

它不是缩写扩写模块。它面对的是"已经是医学词/医学短语"的文本片段。

## 核心1 · 它只是编排者,真正干活的是两个子模块

代码很薄:

```python
from services.ner_service import NERService
from services.medical_retriever import MedicalRetriever

class MedicalStandardizer:
    def __init__(self):
        self.ner_service = NERService()
        self.retriever = MedicalRetriever()
```

含义:

```text
MedicalStandardizer
  ├─ NERService           # 负责抽实体
  └─ MedicalRetriever     # 负责查标准概念候选
```

`MedicalStandardizer` 自己不写模型逻辑、不写 Milvus 逻辑、不写重排逻辑。它只是把两个能力按顺序串起来。

这是一种组合式设计:

```text
NER 怎么做         → 交给 NERService
检索怎么做         → 交给 MedicalRetriever / StdService
整句怎么串起来     → MedicalStandardizer
最终概念是否忠实   → 不在这里,交给 ABBVerifier / ABBRService 主链路
```

## 核心2 · standardize() 的真实流程

入口:

```python
def standardize(self, text: str):
    entities = self.ner_service.extract_entities(text)

    results = []
    for entity in entities:
        entity_text = entity["text"]

        docs = self.retriever.retrieve(
            query=entity_text,
            top_k=10,
            domain_filter=None,
            score_threshold=0.6
        )
        ...
    return {
        "input_text": text,
        "entities": results
    }
```

流程图:

```text
text
  ↓
NERService.extract_entities(text)
  ↓
entities = [{text,label,score,start,end}, ...]
  ↓
for each entity:
  MedicalRetriever.retrieve(
    query=entity["text"],
    top_k=10,
    domain_filter=None,
    score_threshold=0.6
  )
  ↓
取 docs[:3]
  ↓
整理成 candidates
  ↓
返回 {input_text, entities:[...]}
```

它没有调用 LLM,也没有调用 `ABBVerifier`。

## 核心3 · 输出结构

对每个实体,它返回:

```python
results.append({
    "entity": entity_text,
    "entity_label": entity["label"],
    "entity_score": entity["score"],
    "candidates": candidates
})
```

每个 candidate 来自 `doc["metadata"]`:

```python
candidates.append({
    "concept_id": metadata["concept_id"],
    "concept_name": metadata["concept_name"],
    "domain_id": metadata["domain_id"],
    "concept_code": metadata["concept_code"],
    "score": metadata["score"],
    "rerank_score": metadata.get("rerank_score")
})
```

整体结果:

```json
{
  "input_text": "The patient has chest pain.",
  "entities": [
    {
      "entity": "chest pain",
      "entity_label": "SIGN_SYMPTOM",
      "entity_score": 0.9821,
      "candidates": [
        {
          "concept_id": "...",
          "concept_name": "Chest pain",
          "domain_id": "Condition",
          "concept_code": "...",
          "score": 0.91,
          "rerank_score": 1.41
        }
      ]
    }
  ]
}
```

注意:这是候选标准化结果,不是最终忠实标准化结果。它没有说"哪个 candidate 一定正确",只是列出候选。

## 核心4 · V11 主链路为什么没有直接用它

V11 的主链路入口是:

```text
POST /expand/simple
  ↓
ABBRService.expand_verify_with_retry()
```

在 `ABBRService.__init__` 里确实创建了:

```python
self.standardizer = MedicalStandardizer()
self.ner_service = self.standardizer.ner_service
```

但在 `expand_verify_with_retry()` 当前代码里:

```python
standardization_result = None
```

后面没有:

```python
self.standardizer.standardize(...)
```

也就是说:

```text
MedicalStandardizer.standardize()
  当前没有被 /expand/simple 主流程调用
```

主流程的标准化是另一条更细的 per-abbreviation 路径:

```text
候选 coverage 选出 expansion
  ↓
_build_expanded_text_deterministic()
  ↓
每个 expansion 单独 MedicalRetriever.retrieve()
  ↓
ABBVerifier.verify_mappings() 选择 chosen_concept 或弃码
  ↓
mapping_standardizations → API standardized_entities
```

所以 `MedicalStandardizer` 和 V11 主链路的关系更准确是:

```text
保留旧能力:
  整句 → NER → 每个实体检索候选

被主链路复用:
  self.standardizer.ner_service

不再承担:
  /expand/simple 的最终标准化主编排
```

这是本篇最重要的定位。

## 核心5 · 它和 ABBRService 标准化路径的区别

### MedicalStandardizer 路径

```text
整句文本
  ↓
NER 抽所有医学实体
  ↓
每个实体查标准概念候选
  ↓
返回候选列表
```

特点:

- 面向整句所有医学实体;
- 不关心哪些词来自缩写扩写;
- 不做 abbreviation mapping;
- 不做 verifier 忠实性选择;
- 默认只走 `MedicalRetriever.retrieve(...)`,没有显式传 `source`,所以默认 source 是 `snomed`。

### ABBRService V11 路径

```text
缩写 token
  ↓
候选召回 + coverage 选 expansion
  ↓
按 expansion 单独检索
  ↓
根据 domain 路由 source(snomed/rxnorm)
  ↓
verifier 在候选里选标准概念或弃码
```

特点:

- 面向缩写扩写得到的 mapping;
- 每个 record 有状态: PENDING / CODED / WITHHELD 等;
- 支持 Drug → RxNorm 多源路由;
- verifier 选择最终 chosen_concept;
- API 的 `standardized_entities` 来自这条路径。

一句话:

```text
MedicalStandardizer = 整句实体候选检索
ABBRService = 缩写扩写 + 标准概念忠实选择
```

## 数据快照

### 输入

```python
standardizer.standardize("The patient has chest pain and hypertension.")
```

### 中间实体

```json
[
  {"text": "chest pain", "label": "SIGN_SYMPTOM", "score": 0.98},
  {"text": "hypertension", "label": "DISEASE_DISORDER", "score": 0.99}
]
```

### 每个实体检索参数

```text
query = entity["text"]
top_k = 10
domain_filter = None
score_threshold = 0.6
source = 默认 snomed
最终只保留 docs[:3]
```

### 输出

```json
{
  "input_text": "The patient has chest pain and hypertension.",
  "entities": [
    {
      "entity": "chest pain",
      "entity_label": "SIGN_SYMPTOM",
      "entity_score": 0.98,
      "candidates": [
        {"concept_name": "Chest pain", "score": 0.91, "rerank_score": 1.41}
      ]
    }
  ]
}
```

## 调用方地图

### 当前直接调用

```text
backend/test_medical_standardizer.py
  → MedicalStandardizer.standardize(text)
```

### 被初始化但不直接 standardize

```text
backend/services/abbr_service.py
  → self.standardizer = MedicalStandardizer()
  → self.ner_service = self.standardizer.ner_service
```

### 下游无直接依赖

```text
/expand/simple 返回 standardized_entities
  不来自 MedicalStandardizer.standardize()
  而来自 final_result["mapping_standardizations"]
```

这说明它目前更像"保留能力 + NER 容器 + 测试对象",不是 V11 API 主输出路径。

## 为什么还保留它

虽然它不是主链路,但仍有价值:

1. **保留整句实体标准化能力**:以后如果要做"不只是缩写,还标准化整句所有医学术语",这条路径可以继续扩展。
2. **方便单测和调试**:可以单独测试 NER → Retriever 是否能跑通。
3. **复用 NERService 初始化**:`ABBRService` 通过它拿 `ner_service`,不用再单独创建一份。
4. **作为 V9/V10 架构遗留桥梁**:理解历史演进时,它说明项目曾经从整句实体标准化角度组织过。

但保留不等于主链路。写文档和面试时要把这两个概念分开。

## 其余细节(次要,一行带过)

【次要】`standardize()` 对实体串行检索;每个实体检索 top 10 但只返回前 3;没有传 `domain_boost`;没有传 `source`,因此默认 SNOMED;不做异常捕获;不做空实体的特殊解释,空实体时返回 `entities: []`。

## 死代码 / 盲肠提醒

- `MedicalStandardizer.standardize()` 当前不是死代码,因为测试脚本会调用,也可能作为辅助能力使用;但它**不是 V11 主 API 的标准化热路径**。
- `ABBRService.expand_verify_with_retry()` 里的 `standardization_result = None` 说明旧的整句 standardization 结果已经不再被填充。这是一个历史字段/兼容字段。
- `ABBRService` 初始化整个 `MedicalStandardizer()` 主要为了拿 `ner_service`,这会顺带创建一个 `MedicalRetriever()` / `StdService()`。同时 `ABBRService` 自己又创建 `self.retriever = MedicalRetriever()`。这意味着初始化阶段可能有重复的 retriever/std_service 实例,属于可优化点。

## 优化方向(更好 / 更稳)

1. **拆开 NERService 注入**:`ABBRService` 如果只需要 `ner_service`,可以直接创建或注入 `NERService`,避免为了拿 NER 而创建整个 `MedicalStandardizer`。
2. **抽公共候选整理函数**:`standardize()` 和 `ABBRService` 都会把 docs metadata 整理成 candidate dict,可抽成工具函数,减少重复。
3. **支持 source/domain_boost**:如果以后继续使用整句标准化,可以根据 NER label 映射 domain,再传 `domain_boost` 或 source,让药品实体走 RxNorm。
4. **参数配置化**:`top_k=10`、`score_threshold=0.6`、`docs[:3]` 都写死,可放入配置。
5. **并行或批量检索**:实体多时逐个检索会慢。可以考虑批量 embedding 或并发检索。
6. **增加 verifier 层**:如果它要重新成为主标准化能力,需要像 ABBRService 一样有 faithful selection,否则只停留在候选列表。
7. **明确 API 返回字段**:如果 `standardization` 字段长期为 `None`,要么删除/降级为调试字段,要么恢复它的实际生产含义。

## 会被追问 / 诚实局限(主动说)

- **当前主链路没直接用 standardize()**:一定要主动说明,不要把它夸成 V11 API 的主标准化模块。
- **它只给候选,不做最终判断**:没有 verifier,不能保证第一个候选就是正确概念。
- **默认只走 SNOMED**:没有显式 source,所以药品整句实体不会自动走 RxNorm。
- **初始化可能重复加载底座**:`ABBRService` 里同时有 `self.standardizer.retriever` 和 `self.retriever`。
- **参数写死且串行**:适合原型,不适合高吞吐生产。

## 面试怎么说

**合格版(30 秒)**:
> MedicalStandardizer 是一个很薄的编排器,组合 NERService 和 MedicalRetriever。它对整句先抽医学实体,再对每个实体检索 SNOMED 候选,最后返回每个实体的 top candidates。它自己不做 NER、不做 Milvus、不做 verifier 判断。

**优秀版(1 分钟)**:
> 这个模块是项目早期整句标准化路径的收口:先用 NER 抽实体,再逐个用 MedicalRetriever 查标准概念候选,每个实体保留前 3 个。它体现的是组合和单一职责,因为实体识别和检索都在子模块里。但 V11 以后主链路已经转向 ABBRService 的 per-abbreviation 状态机,`/expand/simple` 的标准化结果来自每个缩写扩写的 mapping_standardizations 和 verifier chosen_concept,不是来自 MedicalStandardizer.standardize()。现在 ABBRService 主要复用它里面的 NERService,用于 fallback 候选推断 domain。这个模块仍有价值,但更像旧编排/辅助能力;后续我会考虑拆开 NER 注入,避免为了拿 NER 而额外创建 retriever/std_service。

## 易错点 / 面试问答

**Q:MedicalStandardizer 是 V11 的主标准化模块吗?**  
A:不是当前主热路径。V11 主标准化在 `ABBRService.expand_verify_with_retry()` 里按 abbreviation mapping 单独检索和 verify。MedicalStandardizer 是保留的整句实体标准化编排。

**Q:它和 MedicalRetriever 有什么区别?**  
A:MedicalRetriever 只管一个 query 的检索/重排/包装。MedicalStandardizer 管整句:先 NER 抽多个 entity,再对每个 entity 调 MedicalRetriever。

**Q:它会选择最终标准概念吗?**  
A:不会。它只返回候选列表,没有 verifier faithful selection。

**Q:为什么 `ABBRService` 还要初始化它?**  
A:主要为了复用 `self.standardizer.ner_service`,用于 fallback 候选的 `is_medical()` / domain 推断。但这会顺带创建 retriever,存在可优化空间。

**Q:它支持 RxNorm 吗?**  
A:当前 `standardize()` 没传 source,所以默认走 MedicalRetriever 的 `source="snomed"`。V11 药品走 RxNorm 的能力在 ABBRService 的 `_route_source(domain)` 那条 mapping 标准化路径里。

**Q:如果未来要扩展它,最应该补什么?**  
A:先补 label→domain→source/domain_boost,再补 verifier 选择层,否则它只是一份候选召回结果。

## 一句话总结

> MedicalStandardizer 是 V9/V10 留下来的整句标准化薄编排:它把 NERService 和 MedicalRetriever 串成"整句抽实体 → 每个实体查标准概念候选"的能力。V11 当前主 API 不直接用它产出最终标准化结果,而是由 ABBRService 的 mapping 级检索 + verifier 负责;MedicalStandardizer 现在主要作为辅助能力和 NERService 容器保留。理解它时最重要的是别把"候选检索"误说成"最终标准化裁判"。
