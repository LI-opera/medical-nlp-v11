# NERService —— 医学实体识别能力层 · V11

> 文件:`backend/services/ner_service.py`(约 100 行)
> 衔接:前面 `StdService` / `MedicalRetriever` 解决的是"给一个 query,去医学库里搜标准概念"。但一整句临床文本里,不是每个词都值得搜。NERService 的职责是**把医学实体从文本里圈出来**,并给出实体类型、置信度、位置。V11 主链路里,它不再是最终标准化主干,但仍被 fallback 缩写候选用来推断 domain。
> **V11 变化(必看)**:在 V9 文档里,NERService 更像"整句标准化的起点";到 V11,主链路改成 `ABBRService` 的 per-abbreviation 状态机。NERService 仍然保留,但它的关键作用变成两个:①服务 `MedicalStandardizer.standardize()` 这条旧整句标准化路径;②通过 `is_medical()` 帮 fallback LLM 生成的候选扩写词推断医学 label/domain。

## 核心速记

> 1. **一句定位**:NERService 是医学实体识别层,输入一句文本,输出医学实体列表:`text / label / score / start / end`。
> 2. **用现成医学 NER 模型**:`Clinical-AI-Apollo/Medical-NER`,通过 HuggingFace `pipeline(task="token-classification")` 加载,不是自己训练。
> 3. **V11 主链路真实作用**:`ABBRService._get_abbreviation_candidates()` 里,fallback 候选会调用 `self.ner_service.is_medical(expansion)` 来推断 label,再映射成 domain,用于后续 `domain_boost` 和多源路由。
> 次要(trivia):`_merge_adjacent_entities()` 会把相邻医学实体按白名单合并,例如身体部位 + 症状;代码里变量名 `should_merga` 拼错了,但不影响运行。

## 这一段在解决什么

大白话:**给一句临床文本,把里面真正像医学概念的片段圈出来。**

```text
输入:
"The patient has chest pain and hypertension."

NER 输出:
[
  {text:"chest pain", label:"SIGN_SYMPTOM", score:0.98, start:16, end:26},
  {text:"hypertension", label:"DISEASE_DISORDER", score:0.99, start:31, end:43}
]
```

这一步本身不查 SNOMED,也不做缩写扩写。它只回答:

```text
这段文本里哪些片段是医学实体?
它们大概属于什么 label?
模型有多大把握?
它们在原文哪个位置?
```

## 核心1 · 为什么需要 NER

如果直接把整句话丢进向量库:

```text
The patient has chest pain and hypertension.
```

向量会被很多非医学词稀释:

```text
the / patient / has / and
```

更合理的方式是:

```text
先抽出医学实体:
  chest pain
  hypertension

再分别检索:
  chest pain → SNOMED 候选
  hypertension → SNOMED 候选
```

所以在早期 `MedicalStandardizer` 里,流程是:

```text
整句 text
  ↓
NERService.extract_entities()
  ↓
每个 entity 调 MedicalRetriever.retrieve()
  ↓
返回每个实体的候选标准概念
```

但 V11 主链路不再从"整句 NER"启动,而是从"缩写 token gate + 候选召回"启动。这个区别一定要记住。

## 核心2 · 模型加载:站在现成医学 NER 模型上

初始化代码:

```python
from transformers import pipeline

class NERService:
    def __init__(self):
        self.ner_pipeline = pipeline(
            task="token-classification",
            model="Clinical-AI-Apollo/Medical-NER",
            aggregation_strategy="simple"
        )
```

几个点:

- `task="token-classification"`:对文本里的 token 做实体分类;
- `model="Clinical-AI-Apollo/Medical-NER"`:使用 HuggingFace 上的医学 NER 模型;
- `aggregation_strategy="simple"`:把 subword 或相邻 token 聚合成更完整的实体片段。

这说明项目没有自训 NER 模型。它的工程取舍是:先用现成医学模型获得实体识别能力,把项目重点放在缩写候选、检索、校验、反思链路上。

## 核心3 · extract_entities():统一模型输出结构

模型原始输出大概长这样:

```python
[
    {
        "entity_group": "SIGN_SYMPTOM",
        "score": 0.9876,
        "word": "chest pain",
        "start": 12,
        "end": 22
    }
]
```

`extract_entities()` 会把字段整理成项目统一格式:

```python
entities.append({
    "text": item["word"],
    "label": item["entity_group"],
    "score": round(float(item["score"]), 4),
    "start": item["start"],
    "end": item["end"]
})
```

整理后的好处:

```text
text  = 实体文本,后面直接拿去检索
label = 医学实体类型,后面可映射 domain
score = 模型置信度
start/end = 原文位置,用于合并和追踪
```

最后它还会调用:

```python
merged_entities = self._merge_adjacent_entities(text, entities)
return merged_entities
```

也就是说 `extract_entities()` 返回的不是模型原始结果,而是"字段整理 + 相邻实体合并"后的结果。

## 核心4 · 相邻实体合并:把碎片拼回完整概念

模型有时会把一个医学概念切成两个相邻实体:

```text
chest pain
  ↓ 模型可能拆成
chest: BIOLOGICAL_STRUCTURE
pain:  SIGN_SYMPTOM
```

但下游检索更希望拿到:

```text
chest pain
```

所以代码里有 `_merge_adjacent_entities()`:

```python
gap_text = text[current["end"]:next_entity["start"]]

should_merga = (
    gap_text.strip() == ""
    and self._can_merge(current, next_entity)
)
```

两个条件同时满足才合并:

```text
1. 两个实体之间没有实质文本(gap_text.strip()=="")
2. 两个实体 label 组合在白名单里
```

白名单:

```python
merge_laberl_pairs = {
    ("BIOLOGICAL_STRUCTURE", "SIGN_SYMPTOM"),
    ("BIOLOGICAL_STRUCTURE", "DISEASE_DISORDER"),
    ("SIGN_SYMPTOM", "SIGN_SYMPTOM"),
}
```

典型意义:

```text
身体部位 + 症状       chest + pain
身体部位 + 疾病       kidney + disease
症状 + 症状           nausea + vomiting
```

合并后的字段:

```python
current = {
    "text": text[current["start"]:next_entity["end"]].strip(),
    "label": f"{current['label']}+{next_entity['label']}",
    "score": round((current["score"] + next_entity["score"]) / 2, 4),
    "start": current["start"],
    "end": next_entity["end"]
}
```

注意:合并后的 `label` 会变成 `"A+B"` 这种复合 label。下游一般更看重 `text`,label 主要是辅助信号。

## 核心5 · is_medical():V11 fallback 的 domain 推断入口

这是 V11 里最容易被忽略、但很关键的函数:

```python
def is_medical(self, text: str):
    if not text:
        return False, None, 0.0
    ents = self.extract_entities(text)
    if not ents:
        return False, None, 0.0
    top = max(ents, key=lambda e: e["score"])
    return True, top["label"], top["score"]
```

它的作用不是抽整句所有实体,而是对一个孤立短语判断:

```text
这个 expansion 是否像医学实体?
如果是,最高分 label 是什么?
置信度是多少?
```

V11 主链路调用点在 `ABBRService._get_abbreviation_candidates()`:

```python
if candidate_source == "fallback":
    for candidate in candidates:
        _, label, _ = self.ner_service.is_medical(candidate.get("expansion"))
        candidate["domain"] = NER_LABEL_TO_DOMAIN.get(label)
```

意思是:

```text
fallback LLM 给了一个候选 expansion
  ↓
NERService 判断它像哪类医学实体
  ↓
ABBRService 用 NER_LABEL_TO_DOMAIN 把 label 映射成 domain
  ↓
domain 后面参与 domain_boost 和 source 路由
```

例如:

```text
"aspirin" → label 可能是 MEDICATION → domain Drug
"chest pain" → label 可能是 SIGN_SYMPTOM → domain Condition
```

这就是 NERService 在 V11 主链路里的真实价值:不是直接标准化整句,而是给 fallback 候选补 domain 标签。

## label 到 domain 的映射

映射表不在 `ner_service.py`,而在 `abbr_service.py` 顶部:

```python
NER_LABEL_TO_DOMAIN = {
    "DISEASE_DISORDER": "Condition",
    "SIGN_SYMPTOM": "Condition",
    "BIOLOGICAL_STRUCTURE": "Spec Anatomic Site",
    "MEDICATION": "Drug",
    "DIAGNOSTIC_PROCEDURE": "Procedure",
    "THERAPEUTIC_PROCEDURE": "Procedure",
    "LAB_VALUE": "Measurement",
    "DETAILED_DESCRIPTION": "Observation",
}
```

这个映射后面会影响两件事:

```text
domain_boost:
  MedicalRetriever 里 domain_id 命中 domain 就 +0.2

source route:
  ABBRService._route_source(domain)
  domain == "Drug" → rxnorm
  其它 → snomed
```

所以 NER label 的质量会间接影响检索排序和多源路由。

## V11 主链路里它在哪里

### 不走 fallback 时

```text
ABBR_CANDIDATES 里已有缩写
  ↓
候选自带 domain
  ↓
一般不需要 NERService 推断 domain
```

例如:

```python
"CP": [
    {"expansion": "chest pain", "domain": "Condition"}
]
```

### 走 fallback 时

```text
未知大写缩写
  ↓
ABBRCandidateFallbackRetriever 让 LLM 生成候选 expansion
  ↓
NERService.is_medical(expansion)
  ↓
label → domain
  ↓
coverage evaluator 再判断候选是否适合上下文
```

也就是说,NerService 在 V11 里主要补的是 fallback 候选缺失的 `domain` 字段。

## 数据快照

### extract_entities 输出

```json
[
  {
    "text": "chest pain",
    "label": "BIOLOGICAL_STRUCTURE+SIGN_SYMPTOM",
    "score": 0.9432,
    "start": 16,
    "end": 26
  }
]
```

### is_medical 输出

```python
(True, "SIGN_SYMPTOM", 0.9876)
```

### fallback 候选被补 domain 后

```json
{
  "abbreviation": "XYZ",
  "expansion": "some medical term",
  "source": "fallback_llm",
  "confidence": 0.72,
  "domain": "Condition"
}
```

注意:如果 `label` 没有命中 `NER_LABEL_TO_DOMAIN`,domain 可能是 `None`。这时后面默认不会得到 domain boost,路由也会走 `snomed`。

## 和 MedicalStandardizer 的关系

`MedicalStandardizer` 仍然是:

```text
NERService.extract_entities(text)
  ↓
对每个 entity_text 调 MedicalRetriever.retrieve()
  ↓
返回每个实体的 SNOMED 候选
```

这条路径适合理解"整句医学实体标准化",但 V11 的 `/expand/simple` 主链路返回的 `standardized_entities`,主要来自 `ABBRService` 的 per-abbreviation 标准化结果:

```text
mapping_standardizations → chosen_concept → standardized_entities
```

所以学习时要分清:

```text
NERService + MedicalStandardizer
  = 早期/辅助的整句实体标准化能力

ABBRService + MedicalRetriever + ABBVerifier
  = 当前 V11 缩写扩写与标准概念对齐主链路
```

## 其余细节(次要,一行带过)

【次要】`start/end` 是字符索引,可用 `text[start:end]` 回切原文;`score` 保留 4 位;合并后 score 取平均;`aggregation_strategy="simple"` 已经做了一层模型级聚合,项目又额外做了一层医学概念级合并。

## 死代码 / 盲肠提醒

- `should_merga` 是拼写错误,应为 `should_merge`,但变量只在本地使用,不影响功能。
- `merge_laberl_pairs` 也拼错了,应为 `merge_label_pairs`,同样不影响功能。
- `MedicalStandardizer.standardize()` 会调用 `extract_entities()`,但当前 V11 主 API 的最终标准化输出不依赖这条整句路径。
- `is_medical()` 的返回值第一个 `bool` 在当前 fallback 调用里被 `_` 忽略了,主链路只拿 label 映射 domain。

## 优化方向(更好 / 更稳)

1. **把 label-domain 映射收口成共享配置**:现在映射表放在 `abbr_service.py`,但语义上和 NERService 强相关。可以抽到 `utils` 或医学 schema 常量里。
2. **处理复合 label 的 domain 映射**:合并后 label 可能是 `"BIOLOGICAL_STRUCTURE+SIGN_SYMPTOM"`,当前映射表没有这种 key。可按优先级拆分后映射,例如症状优先于部位。
3. **修正拼写变量**:`should_merga` / `merge_laberl_pairs` 改名,降低阅读成本。
4. **支持 device 配置**:pipeline 当前没有显式设置 GPU/CPU。可以读 env 或检测 cuda,让 benchmark 更稳定。
5. **缓存 is_medical 结果**:fallback 候选短语可能重复出现,可以给 `is_medical(expansion)` 加简单缓存,减少 NER 模型调用。
6. **增强合并规则**:当前只支持少数 label pair,三词以上实体容易断。可以改成 while/窗口式合并,或基于实体间距和 label 优先级做更稳的 chunking。
7. **给 NER 做独立评估集**:现在 benchmark 更多测缩写扩写,NER 自身的 precision/recall 没有单独量化。

## 会被追问 / 诚实局限(主动说)

- **不是自训模型**:NER 能力来自现成 HuggingFace 模型,项目没有医学 NER 标注训练过程。
- **NER 错了会传导**:如果 fallback 候选被错误 label,domain 可能错,进而影响 domain_boost 或 source 路由。
- **合并规则是启发式**:只覆盖常见相邻实体组合,不是完整医学短语 chunker。
- **复合 label 映射有空洞**:`A+B` 这类 label 不一定能映射到 domain。
- **V11 主链路不靠 NER 抽缩写**:缩写识别主要靠 token gate 和候选库;不要把 NERService 说成主链路的缩写发现器。

## 面试怎么说

**合格版(30 秒)**:
> NERService 是医学实体识别层,用 HuggingFace 的 `Clinical-AI-Apollo/Medical-NER` 模型把临床文本里的医学实体抽出来,返回 text、label、score、start/end。它还做一层相邻实体合并,比如把 chest + pain 合成 chest pain。V11 里它主要作为能力层保留,并通过 `is_medical()` 给 fallback LLM 生成的候选扩写推断 domain。

**优秀版(1 分钟)**:
> 这个模块我没有自训 NER,而是用现成医学 NER pipeline,工程重点是把它接进标准化链路。`extract_entities()` 会把模型输出整理成统一结构,再用一个手写白名单合并相邻实体,避免把 chest pain 这种概念拆成 chest 和 pain 分别检索。V11 主链路里,缩写发现不是靠 NER,而是靠 token gate 和候选召回;NER 的关键作用变成 fallback 候选的 domain 推断:LLM 生成一个候选 expansion 后,`is_medical()` 判断它的医学 label,再映射成 Condition/Drug/Procedure 等 domain,后面影响 domain boost 和 SNOMED/RxNorm 路由。我也清楚它的边界:现成模型会有识别错误,合并规则是启发式,复合 label 还需要更好的 domain 映射。

## 易错点 / 面试问答

**Q:NERService 是用来识别缩写的吗?**  
A:不是。V11 缩写发现主要靠 token gate 和候选库。NERService 识别的是医学实体/医学短语,不是专门识别缩写。

**Q:它在 V11 主链路里到底用在哪里?**  
A:主要在 fallback 候选阶段。LLM 生成候选 expansion 后,`is_medical()` 推断 label,再映射成 domain,用于后续检索加分和多源路由。

**Q:为什么还保留 MedicalStandardizer 那条整句 NER 路径?**  
A:它是早期整句实体标准化能力,也方便测试 NER→Retriever 的基本链路。只是当前 `/expand/simple` 的最终输出主要走 `ABBRService` 的缩写状态机。

**Q:相邻实体为什么要合并?**  
A:模型可能把一个完整医学概念拆成多个实体。比如 `chest pain` 拆成 chest 和 pain,分别检索会偏离目标;合并后更容易命中标准概念。

**Q:NER label 怎么影响多源路由?**  
A:label 会映射成 domain。比如 `MEDICATION → Drug`,然后 `ABBRService._route_source("Drug")` 会选择 RxNorm;其它 domain 默认走 SNOMED。

**Q:如果 NER 没识别出来怎么办?**  
A:`is_medical()` 会返回 `(False, None, 0.0)`,fallback 候选可能没有 domain。后续就没有 domain boost,路由默认走 SNOMED,再由 coverage/verifier 继续把关。

## 一句话总结

> NERService 是项目里的医学实体识别能力层:它用现成医学 NER 模型把文本片段识别成 `{text,label,score,start,end}`,再用简单白名单合并相邻实体。V11 主链路并不靠它发现缩写,而是主要用 `is_medical()` 给 fallback 候选扩写推断 domain,从而影响后续 domain_boost 和 SNOMED/RxNorm 路由。它很有用,但要诚实承认:这是现成模型 + 启发式后处理,不是完整、已独立评估的医学实体识别系统。
