# MedicalStandardizer（标准化编排：NER + 检索 拼成一个完整能力）

> 文件：`backend/services/medical_standardizer.py`（55 行，很薄）
> 入口：`standardize(text)`
> 衔接：这是**阶段二（检索层）的收口**。第 6 篇 NER 负责"找出实体"，第 5 篇 Retriever 负责"查 SNOMED"。MedicalStandardizer 把这两个单一职责模块**组合**起来，对一整句话完成"抽实体 → 每个实体配 SNOMED 候选"。

## 核心速记
> 1. **它只做编排，不写新逻辑**：NER 和检索的活全在子模块里，Standardizer 只负责把它们串起来。这是"组合 + 单一职责"的体现，本篇骨架。
> 2. **一句话流程**：整句 → NER 抽实体 → 每个实体 `retrieve(top_k=10, score≥0.6)` 取前 3 → 打包成结构化结果。
> 3. **注意**：这段"检索+取前3"的逻辑和 ABBRService 里对 expansion 的检索几乎一模一样（重复代码），且整句标准化结果在主链路里**算了但用得少**。这两点是面试可挖的诚实局限。
> 次要（trivia）：返回结构 `{input_text, entities:[...]}`、字段重命名——扫一眼。

## 这一段在解决什么

大白话：**把前两篇拼起来用。** 给一整句话，它先调 NER 圈出医学实体，再对每个实体调检索器查 SNOMED，最后整理成"每个实体 + 它的候选概念"。

```text
"The patient has chest pain and hypertension."
   ↓ NER 抽实体 → [chest pain, hypertension]
   ↓ 每个实体 retrieve(top_k=10, score≥0.6) 取前3
{ entities: [
    {entity:"chest pain",    candidates:[ {Chest pain, code:29857009, score:0.98}, ... ]},
    {entity:"hypertension",  candidates:[ {Hypertensive disorder, ...}, ... ]}
] }
```

## 核心1 · 它是"编排者"，不是"干活的"（骨架，必背）

整个类只有两个子模块 + 一个循环：

```python
class MedicalStandardizer:
    def __init__(self):
        self.ner_service = NERService()        # 第 6 篇
        self.retriever   = MedicalRetriever()  # 第 5 篇

    def standardize(self, text):
        entities = self.ner_service.extract_entities(text)   # ① 抽实体
        results = []
        for entity in entities:                              # ② 每个实体查 SNOMED
            docs = self.retriever.retrieve(query=entity["text"],
                                           top_k=10, domain_filter=None, score_threshold=0.6)
            candidates = [ {...} for doc in docs[:3] ]        # ③ 取前 3 整理成候选
            results.append({"entity":entity["text"], "entity_label":entity["label"],
                            "entity_score":entity["score"], "candidates":candidates})
        return {"input_text": text, "entities": results}
```

**为什么这是好设计**：NER 怎么识别、检索怎么重排过滤，Standardizer **一概不管**——那是子模块的职责。它只负责"先抽再查"的编排。这就是**组合（composition）+ 单一职责**：每个模块只做一件事，上层把它们拼成完整能力。好处是各模块能独立测试、独立替换。

> 对比：如果把 NER 和检索逻辑全塞进一个大类，就成了"上帝类"，难测难改。拆开 + 编排是更健康的结构。

## 核心2 · 真实参数与返回结构（实现 + 真实数据）

检索参数（和后面 ABBRService 里一致）：

```text
top_k=10  →  domain_filter=None  →  score_threshold=0.6  →  docs[:3]
召回 10 个 → 不限领域 → 踢掉相似度 < 0.6 → 每个实体保留前 3 个候选
```

返回结构：

```text
{
  "input_text": "原句",
  "entities": [
    { "entity": "chest pain",
      "entity_label": "BIOLOGICAL_STRUCTURE+SIGN_SYMPTOM",   # 来自 NER（可能是合并标签）
      "entity_score": 0.97,                                  # NER 置信度
      "candidates": [                                        # 来自检索（前 3）
        {"concept_id":..., "concept_name":"Chest pain", "domain_id":"Condition",
         "concept_code":"29857009", "score":0.98, "rerank_score":1.33},
        ...
      ] }
  ]
}
```

一句话：**每个实体挂着它的 SNOMED 候选**，把"自由文本"对齐到"标准概念"。

## 会被追问 / 诚实局限（★主动说）

- **"检索 + 取前 3"的逻辑被复制了两份**：这里对实体检索，ABBRService 里对每个 expansion 检索，两段代码几乎一字不差（`top_k=10, score≥0.6, docs[:3]`，连 candidate 字段都一样），没抽成公共函数。违背 DRY。
  → 面试这么说："这块检索+取前3的逻辑出现了两处，是重复代码。我会抽成一个公共方法（比如 `retrieve_top_candidates`），两边都调，避免参数改一处漏一处。"
- **整句标准化结果在主链路里"算了但用得少"**：`standardize()` 对整句所有实体都做了检索，产出 `standardization`；但主重试链路里，Verifier 实际用的是**逐 expansion 单独检索的 `mapping_standardizations`**，整句的 `standardization` 主要作为 attempt 记录/调试信息，没直接驱动校验决策。
  → "整句标准化更多是给调试和未来扩展（如整句级 RAG）准备的，主链路决策走的是 mapping 级标准化。这块有冗余，我清楚。" 能说清说明你真读懂了数据流。
- **参数全写死**（top_k=10 / 0.6 / 前 3），调用方改不了。
- **串行检索**：实体越多越慢，每个实体一次 embedding + 一次 Milvus。可以批量优化。
- **`domain_filter=None`**：领域过滤口子留着没用（和第 5 篇一致）。

## 面试怎么说

**合格版（30 秒）**：
> MedicalStandardizer 是个编排器，组合 NER 和检索器：对一句话先抽医学实体，再对每个实体查 SNOMED，取前 3 个候选，返回"每个实体 + 候选概念"的结构。它本身不写 NER 或检索逻辑，只负责串联。

**优秀版（1 分钟）**：
> 这个类很薄，体现的是组合和单一职责——NER 怎么识别、检索怎么重排，它都不管，只负责"先抽实体再逐个查 SNOMED"的编排，子模块能独立替换和测试。返回结构是每个实体挂着它的 Top-3 SNOMED 候选，把自由文本对齐到标准概念。诚实说两个点：一是这里的"检索+取前3"和 ABBRService 里对 expansion 的检索是重复代码，应该抽成公共方法；二是整句标准化结果在主链路里其实没直接驱动校验，校验走的是逐 expansion 的标准化，整句这份更多是调试和未来整句级 RAG 的预留。

## 易错点 / 面试问答

**Q：Standardizer 自己做了什么？** A：只做编排——调 NER 抽实体、调检索器查 SNOMED、整理结果。识别和检索的逻辑都在子模块里。这是组合 + 单一职责。

**Q：为什么不把 NER 和检索写在一个类里？** A：会变成难测难改的"上帝类"。拆成单一职责模块再编排，各自能独立测试和替换，更健康。

**Q：每个实体保留几个候选？参数怎么来的？** A：检索 top_k=10、过滤 score≥0.6、取前 3。这组参数和 ABBRService 里对 expansion 的检索一致（也因此是重复代码）。

**Q：整句标准化结果用在哪？** A：主链路校验其实用的是逐 expansion 的标准化（mapping_standardizations），整句的 standardization 主要作调试记录和未来扩展，没直接驱动决策。

## 一句话总结

> MedicalStandardizer 是阶段二的收口编排器：组合 NER（抽实体）和 Retriever（查 SNOMED），对整句完成"每个实体配 Top-3 SNOMED 候选"，体现组合 + 单一职责。局限是"检索+取前3"逻辑与 ABBRService 重复（违背 DRY）、整句标准化结果在主链路用得少（有冗余）、参数写死、串行检索——都是可重构优化的工程点。
