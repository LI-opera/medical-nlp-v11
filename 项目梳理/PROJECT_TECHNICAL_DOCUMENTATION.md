# Medical NLP 项目技术文档

## 1. 项目定位

本项目是一个面向英文临床文本的医学 NLP 后端原型，核心目标是将临床病历中的自由文本、医学缩写和非标准医学表达，转换为更标准、可检索、可验证、可追踪的医学结构化结果。

项目重点不是简单调用大模型完成文本改写，而是围绕医学场景中最关键的可靠性问题，构建了一条包含候选召回、医学实体识别、SNOMED 标准术语检索、结果校验和反思重试的处理流水线。

可以用一句话概括：

```text
Clinical Text -> Abbreviation Expansion -> Medical NER -> SNOMED Retrieval -> Verification -> Standardized Output
```

面试表达版本：

> 我做的是一个医学文本标准化系统，主要处理临床病历中的医学缩写和非标准术语。系统通过候选召回、上下文判断、SNOMED 向量检索和双层校验，尽量避免直接让大模型自由生成，从而降低医学场景下错误扩写和幻觉的风险。

## 2. 项目解决的核心问题

### 2.1 临床文本中缩写多且存在歧义

临床病历中大量使用缩写，例如：

- `SOB` 可以表示 `shortness of breath`
- `HTN` 可以表示 `hypertension`
- `DM` 可以表示 `diabetes mellitus`
- `CP` 在不同上下文中可能表示 `chest pain`、`cerebral palsy` 或 `chronic pancreatitis`

如果只做简单字典替换，就无法处理上下文歧义。例如：

```text
The patient reports CP radiating to the left arm.
```

这里的 `CP` 更可能是 `chest pain`。

```text
The child has a history of CP since birth.
```

这里的 `CP` 更可能是 `cerebral palsy`。

项目通过候选扩写召回和上下文判断，将缩写扩展问题从开放式生成问题转化为候选选择问题。

### 2.2 直接使用 LLM 容易产生医学幻觉

医学场景对准确性要求高。直接让 LLM 扩写临床文本，可能出现以下问题：

- 把不确定的缩写强行扩写
- 添加原文没有的诊断或症状
- 改变否定、时间、严重程度等临床语义
- 对没有足够上下文的缩写做过度推断

因此本项目采用：

```text
Candidate Retrieval -> Coverage Evaluation -> Candidate-Constrained LLM Selection
```

也就是先召回候选，再判断候选是否被上下文支持，最后才让 LLM 在候选范围内做选择。

### 2.3 非标准医学表达需要映射到标准医学概念

临床文本中的表达通常是不统一的，例如：

- `chest pain`
- `pain in chest`
- `shortness of breath`
- `hypertension`

这些表达如果不能映射到标准医学概念，后续很难做结构化分析、知识库检索、RAG 或统计评估。

本项目使用 SNOMED 数据构建医学概念向量库，通过 Milvus 实现语义检索，将临床实体映射到标准医学候选概念。

## 3. 总体技术架构

系统完整流程如下：

```text
Input Clinical Text
  -> Abbreviation Detection Gate
  -> Primary Candidate Retrieval
  -> Fallback Candidate Retrieval
  -> Candidate Coverage Evaluation
  -> Candidate Coverage Filtering
  -> LLM Candidate Selection
  -> Expanded Clinical Text
  -> Medical NER
  -> SNOMED Vector Retrieval
  -> Rule-Based Rerank
  -> Mapping Standardization
  -> Dual-Level Verification
  -> Candidate-Constrained Reflection
  -> Retry Loop
  -> Final Output
```

系统可以分为三层：

1. Retrieval Layer：负责医学知识召回，包括缩写候选召回和 SNOMED 标准概念召回。
2. Quality Control Layer：负责覆盖度评估、语义校验、映射校验和失败控制。
3. Reflection Layer：负责在校验失败后，根据错误反馈进行受约束修正。

## 4. 技术栈

| 技术 | 项目中的作用 |
| --- | --- |
| Python | 后端主语言 |
| HuggingFace Transformers | 医学 NER 模型加载与实体识别 |
| Clinical-AI-Apollo/Medical-NER | 医学命名实体识别模型 |
| LangChain HuggingFaceEmbeddings | Embedding 模型封装 |
| BAAI/bge-m3 | 医学术语和 query 的向量表示 |
| Milvus | SNOMED 医学概念向量库检索 |
| SNOMED 数据 | 标准医学概念来源 |
| DeepSeek Chat | 缩写扩展、候选覆盖评估、校验和反思 |
| Pydantic | 结构化校验结果建模 |
| JSON Structured Output | 让 LLM 输出可被代码解析和决策 |

## 5. 核心模块说明

### 5.1 `StdService`

位置：

```text
backend/services/std_service.py
```

职责：

- 加载 embedding 模型
- 连接 Milvus
- 加载 SNOMED collection
- 将输入 query 转成向量
- 从 Milvus 中检索相似医学概念

核心流程：

```text
query
  -> embedding_model.embed_query(query)
  -> Milvus vector search
  -> concept_id / concept_name / domain_id / concept_code / FSN
```

这个模块是医学术语标准化的底层检索服务。

### 5.2 `MedicalRetriever`

位置：

```text
backend/services/medical_retriever.py
```

职责：

- 调用 `StdService` 检索 SNOMED 候选概念
- 将检索结果包装成 RAG document 格式
- 对候选结果进行简单规则重排
- 支持 domain 过滤和最低分数过滤

重排逻辑包括：

- concept_name 与 query 完全一致时加分
- concept_name 以 query 开头时加分
- concept_name 包含 query 时加分
- 过长术语适当扣分

这个模块体现了 RAG 中 Retriever 层的思想：从医学知识库中召回可供后续模型或校验器使用的证据。

### 5.3 `NERService`

位置：

```text
backend/services/ner_service.py
```

职责：

- 使用 HuggingFace 的医学 NER 模型抽取临床文本中的医学实体
- 输出实体文本、实体类别、置信度和位置
- 对相邻实体进行合并，例如身体部位加症状可以合并成更完整的医学表达

输入输出示例：

```text
Input:
The patient reports chest pain.

Output:
[
  {
    "text": "chest pain",
    "label": "SIGN_SYMPTOM",
    "score": 0.98
  }
]
```

### 5.4 `MedicalStandardizer`

位置：

```text
backend/services/medical_standardizer.py
```

职责：

- 组合 `NERService` 和 `MedicalRetriever`
- 先从文本中抽取医学实体
- 再对每个实体检索 SNOMED 候选术语
- 输出结构化标准化结果

核心流程：

```text
clinical text
  -> NERService.extract_entities()
  -> MedicalRetriever.retrieve(entity_text)
  -> standardized candidates
```

这个模块负责把一整段临床文本中的医学实体映射到标准医学概念候选。

### 5.5 `ABBRCandidateRetriever`

位置：

```text
backend/services/abbr_candidate_retriever.py
backend/data/abbr_candidates.py
```

职责：

- 从本地缩写候选库中召回扩写候选
- 将缩写扩展从自由生成转化为候选选择

示例：

```python
"CP": [
    "chest pain",
    "cerebral palsy",
    "chronic pancreatitis"
]
```

### 5.6 `ABBRCandidateFallbackRetriever`

位置：

```text
backend/services/abbr_candidate_fallback_retriever.py
```

职责：

- 当本地候选库没有对应缩写时，调用 LLM 生成候选扩写
- 注意它只生成候选，不直接改写原始文本

这样设计的原因是：即使使用 LLM，也要限制它的职责，避免直接开放式生成导致幻觉。

### 5.7 `ABBRCandidateCoverageEvaluator`

位置：

```text
backend/services/abbr_candidate_coverage_evaluator.py
```

职责：

- 判断候选集中是否存在至少一个被当前上下文支持的合理扩写
- 输出 `coverage_ok`、`confidence`、`plausible_candidates`、`issues`

它解决的是：

```text
有候选，不代表当前上下文一定支持这个候选。
```

例如：

```text
The patient was evaluated for LMN.
```

即使 `LMN` 可以表示 `Lower Motor Neuron`，但当前文本上下文太弱，也不一定应该扩写。

### 5.8 `ABBRService`

位置：

```text
backend/services/abbr_service.py
```

职责：

- 缩写识别
- 候选召回
- 候选覆盖度评估
- LLM 缩写扩写
- 医学实体标准化
- 缩写映射标准化
- 结果校验
- reflection retry

这是整个项目的主流程入口。

核心能力包括：

- `simple_llm_expansion(text)`：基于候选集进行缩写扩写
- `expand_and_standardize(text)`：扩写后做医学实体标准化
- `expand_standardize_and_verify(text)`：扩写、标准化、校验
- `expand_verify_with_retry(text)`：完整闭环，包括失败后的反思重试

### 5.9 `ABBVerifier`

位置：

```text
backend/services/abbr_verifier.py
```

职责：

- 从句子级别判断扩写后文本是否保留原意
- 从 mapping 级别判断每个缩写扩写是否合理
- 检查 SNOMED 候选是否支持扩写结果

双层校验包括：

1. Sentence-level validity
   - 是否只扩写缩写
   - 是否保留否定、时间、严重程度和原始临床含义
   - 是否添加了原文没有的信息

2. Mapping-level validity
   - abbreviation 是否出现在原文
   - expansion 是否出现在扩写后文本
   - expansion 是否符合上下文
   - SNOMED 候选是否提供支持

### 5.10 `ABBRReflectionService`

位置：

```text
backend/services/abbr_reflection_service.py
```

职责：

- 当 verifier 判断扩写失败时，根据校验反馈进行修正
- 反思过程仍然受到候选集约束，不能随意创造新的扩写

核心思想：

```text
不是盲目 retry，而是根据 verifier 的错误原因进行有方向的修正。
```

### 5.11 `MappingSupportVerifier`

位置：

```text
backend/services/mapping_support_verifier.py
```

职责：

- 判断当前文本是否有足够上下文支持某个 abbreviation -> expansion 映射
- 它不判断 expansion 在医学上是否存在，而是判断当前句子是否支持这个映射

例如：

```text
The patient has DM and QRS.
```

这里 `QRS -> QRS complex` 在医学上存在，但当前文本上下文未必足够支持扩写。

这个模块主要用于发现和缓解 low-context over-expansion 问题。

## 6. 完整处理链路示例

输入：

```text
The patient denies CP but reports SOB.
```

处理步骤：

1. Abbreviation Detection Gate 识别 `CP` 和 `SOB`
2. Candidate Retriever 召回候选：
   - `CP`: `chest pain`, `cerebral palsy`, `chronic pancreatitis`
   - `SOB`: `shortness of breath`
3. Coverage Evaluator 判断哪些候选被上下文支持
4. LLM 在候选范围内选择扩写
5. 得到扩写文本：

```text
The patient denies chest pain but reports shortness of breath.
```

6. Medical NER 抽取：
   - `chest pain`
   - `shortness of breath`
7. MedicalRetriever 从 SNOMED 向量库召回标准概念候选
8. Verifier 检查：
   - 是否保留 `denies` 否定语义
   - 是否只扩写缩写
   - 每个映射是否被上下文和 SNOMED 支持
9. 如果通过，返回最终结果；如果失败，进入 reflection retry

## 7. 输出结果结构

系统最终输出不仅是扩写文本，而是一组可追踪的结构化信息：

```json
{
  "original_text": "The patient denies CP but reports SOB.",
  "final_expanded_text": "The patient denies chest pain but reports shortness of breath.",
  "success": true,
  "attempts": [
    {
      "expanded_text": "...",
      "abbreviation_candidates": [],
      "mappings": [],
      "standardization": {},
      "mapping_standardizations": [],
      "verification": {}
    }
  ],
  "final_result": {}
}
```

这些字段的意义：

- `original_text`：原始临床文本
- `final_expanded_text`：最终扩写文本
- `mappings`：缩写到扩写的映射
- `abbreviation_candidates`：候选召回和过滤过程
- `standardization`：扩写后文本的医学实体标准化结果
- `mapping_standardizations`：每个扩写词对应的 SNOMED 检索结果
- `verification`：句子级和映射级校验结果
- `attempts`：每次尝试的中间状态，用于 debug 和可解释性分析

## 8. 评估体系

项目中包含两类评估脚本：

```text
backend/evaluation/evaluate_abbr_expansion.py
backend/evaluation/run_benchmark.py
```

### 8.1 初始评估集

初始评估集包含 6 个 case，覆盖：

- 单义缩写扩展
- 歧义缩写上下文消歧
- 多缩写同时扩展
- fallback retrieval
- coverage failed

目标是验证系统链路是否能跑通。

### 8.2 Benchmark V1

扩展后的 benchmark 包含 50 个 case，覆盖：

| 类别 | 目标 |
| --- | --- |
| Single Meaning | 测试单义缩写扩写能力 |
| Ambiguous Abbreviation | 测试上下文消歧能力 |
| Multi-Abbreviation | 测试单句多缩写处理能力 |
| Coverage Failed | 测试无合理候选时拒绝扩写能力 |
| Low Context Abbreviation | 测试上下文不足时是否能保守处理 |
| Negation Preservation | 测试否定语义保持能力 |

根据已有总结，当前 benchmark 结果为：

```text
Total Cases: 50
Correct: 45
Accuracy: 0.90
```

分类表现：

```text
Single Meaning: 100%
Ambiguous: 90%
Multi-Abbreviation: 100%
Coverage Failed: 100%
Low Context Abbreviation: 0%
Negation Preservation: 100%
```

这个结果说明系统在常见缩写、歧义缩写、多缩写和否定保持上表现较稳定，但在低上下文缩写场景中仍存在过度扩写问题。

## 9. 当前系统暴露的问题

### 9.1 Low-Context Over-Expansion

当前最主要的问题是：当某个缩写存在医学候选，但上下文不足时，系统仍可能倾向于扩写。

典型例子：

```text
The patient was evaluated for LMN.
```

系统可能扩写为：

```text
Lower Motor Neuron
```

但当前文本没有足够证据支持这个映射。

这说明系统需要进一步强化：

```text
候选存在 != 上下文支持
```

### 9.2 部分专业上下文利用不足

例如：

```text
The patient has MS with a diastolic murmur.
```

期望：

```text
MS -> mitral stenosis
```

错误预测可能为：

```text
MS -> multiple sclerosis
```

这说明系统在某些细分医学上下文中，还需要更强的专业特征识别能力。

### 9.3 数据和候选库规模有限

当前项目中的本地缩写候选库规模较小，SNOMED 数据也是样例级别。真实应用中需要：

- 更完整的医学缩写词典
- 更完整的 SNOMED / UMLS 数据
- 更多真实临床文本测试集
- 更细粒度的错误分析

## 10. 工程设计亮点

### 10.1 Retrieval 优先于 Free Generation

项目没有直接让 LLM 自由扩写，而是先召回候选，再让 LLM 选择。

面试表达：

> 在医学场景里，我更倾向于让 LLM 做判断，而不是让它自由生成。候选召回可以把开放式生成问题转化为受约束选择问题，从而降低幻觉风险。

### 10.2 Coverage 优先于 Blind Selection

即使有候选，也先判断候选集是否被上下文支持。

面试表达：

> 候选存在不代表应该扩写，所以我加了 coverage evaluation，用来判断候选集中是否真的有适合当前上下文的解释。

### 10.3 Verification 优先于 Blind Trust

LLM 输出后不直接相信，而是再做句子级和映射级校验。

面试表达：

> 医学文本最怕改错原意，所以我把校验分成 sentence-level 和 mapping-level。前者看整句语义有没有变，后者看每个 abbreviation-expansion 是否被上下文和 SNOMED 支持。

### 10.4 Reflection 优先于 Blind Retry

失败后不是重新随机生成，而是根据 verifier 的反馈修正。

面试表达：

> Retry 不是简单重跑，而是把 verifier 给出的错误反馈传给 reflection 模块，让它基于候选集做受约束修正。

### 10.5 Code 负责决策，LLM 负责判断

系统中 LLM 负责：

- 候选覆盖判断
- 上下文选择
- 校验解释
- 反思修正

代码负责：

- 路由
- 状态管理
- 失败控制
- retry 次数
- JSON 解析
- 检索和过滤

这体现了比较清晰的工程边界。

## 11. 项目演进路线

项目可以按以下路线讲：

```text
V1: 直接 LLM 缩写扩展
V2: 引入本地 Candidate Retrieval
V3: 引入 Fallback Candidate Retrieval
V4: 引入 Candidate Coverage Evaluation
V5: 引入 SNOMED Retrieval 和 Medical Standardization
V6: 引入 Dual-Level Verification
V7: 引入 Candidate-Constrained Reflection
V8: 引入 Retry Loop
V9: 引入 Evaluation Framework
V10: 扩展 Benchmark Dataset 和 Error Analysis
```

这条路线很适合面试表达，因为它能体现你不是一开始就堆复杂模块，而是围绕真实错误逐步迭代。

## 12. 面试陈述模板

### 12.1 一分钟版本

> 这个项目是一个医学 NLP 标准化系统，主要处理英文临床文本中的医学缩写和非标准术语。比如 CP 在不同上下文中可能表示 chest pain 或 cerebral palsy，直接用字典替换或让大模型自由生成都不可靠。
>
> 我的方案是先召回候选扩写，再根据上下文判断候选是否合理，然后让 LLM 在候选范围内选择。扩写后，系统会用医学 NER 抽取实体，并通过 BGE embedding 和 Milvus 从 SNOMED 知识库中召回标准医学概念。最后再用 verifier 检查扩写是否保留原意、是否被 SNOMED 候选支持。如果失败，会进入 reflection retry 进行修正。
>
> 这个项目的核心亮点是把 LLM 放在受约束的医学 NLP 流水线里，通过 retrieval、verification 和 reflection 降低医学场景下的幻觉风险。

### 12.2 三分钟版本

> 项目一开始是为了解决临床文本中医学缩写和非标准术语的问题。临床病历里经常出现 SOB、CP、DM 这类缩写，而且很多缩写是多义的，比如 CP 可以表示 chest pain，也可以表示 cerebral palsy。如果直接靠字典替换，会忽略上下文；如果直接让 LLM 扩写，又容易产生幻觉。
>
> 所以我把系统设计成一个受约束的流水线。第一步是 abbreviation detection gate，只让真正像缩写的 token 进入候选流程，避免普通英文单词被误判。第二步是 candidate retrieval，优先从本地候选库中召回扩写候选，如果没有候选，再用 LLM 做 fallback candidate retrieval，但这一步只生成候选，不直接改写原句。
>
> 接下来我加入 coverage evaluation，用来判断候选集中是否存在被当前上下文支持的合理扩写。只有候选覆盖通过后，才让 LLM 基于候选集完成上下文选择和扩写。
>
> 扩写完成后，我会用医学 NER 抽取实体，然后通过 BAAI/bge-m3 embedding 和 Milvus 从 SNOMED 向量库中召回标准医学概念，并做简单 rerank。最后系统会进行双层校验：sentence-level 检查整句是否保留原意，尤其是否保留否定、时间、严重程度等临床语义；mapping-level 检查每个 abbreviation-expansion 是否被上下文和 SNOMED 候选支持。
>
> 如果校验失败，系统不会盲目重试，而是把 verifier 的反馈传给 reflection 模块，让它在候选集约束下修正扩写结果。这个闭环让系统具备一定的自我纠错能力。
>
> 后续我还做了 benchmark，把 case 分成单义缩写、歧义缩写、多缩写、coverage failed、low-context 和否定语义保持等类别。当前系统整体表现较稳定，但也暴露出 low-context over-expansion 的问题，也就是有候选但上下文不足时仍可能扩写。这个问题后来可以通过 mapping support verifier 和更保守的 abstention 策略继续优化。

## 13. 面试常见追问与回答

### Q1：为什么不直接用 LLM？

答：

> 医学场景不能完全依赖自由生成，因为 LLM 可能会添加原文没有的诊断或错误扩写缩写。我在系统中把 LLM 的职责限制为候选选择、校验和反思，而不是让它直接开放式生成。前面有候选召回和 coverage evaluation，后面有 SNOMED 检索和 verifier，这样整体更可控。

### Q2：RAG 在项目中体现在哪里？

答：

> RAG 主要体现在 MedicalRetriever 这一层。系统会把医学实体或扩写词转成 embedding，然后从 Milvus 中检索 SNOMED 标准概念，并将结果包装成带 metadata 的 documents，供后续标准化和 verifier 使用。

### Q3：Milvus 存的是什么？

答：

> Milvus 中存的是 SNOMED 医学概念的向量表示，以及对应的 concept_id、concept_name、domain_id、concept_code 和 FSN 等字段。检索时输入一个医学实体，系统返回语义最相近的标准医学概念候选。

### Q4：如何处理 CP 这类歧义缩写？

答：

> 我会先召回 CP 的多个候选，比如 chest pain、cerebral palsy、chronic pancreatitis，然后通过上下文判断选择最合理的扩写。例如出现 radiating to left arm 时更支持 chest pain；出现 child、since birth 时更支持 cerebral palsy。

### Q5：怎么保证扩写不改变原意？

答：

> 我加了 verifier，分成句子级和映射级。句子级检查扩写后文本是否只扩写缩写，是否保留否定、时间、严重程度和原始临床含义。映射级检查每个 abbreviation-expansion 是否被上下文和 SNOMED 候选支持。

### Q6：项目当前最大的不足是什么？

答：

> 当前最大问题是 low-context over-expansion。也就是某些缩写虽然有医学候选，但当前文本没有足够上下文支持，系统仍可能扩写。后续可以通过 MappingSupportVerifier、更严格的 abstention 策略和更多低上下文样本来优化。

## 14. 简历项目描述

可以写成：

> 设计并实现医学 NLP 标准化后端原型，面向英文临床文本中的医学缩写扩展和 SNOMED 术语标准化问题。系统基于 HuggingFace Medical-NER 抽取医学实体，使用 BAAI/bge-m3 生成向量并通过 Milvus 检索 SNOMED 标准概念；针对 CP、SOB、DM 等医学缩写，构建 primary/fallback candidate retrieval、coverage evaluation、candidate-constrained LLM expansion、dual-level verification 和 reflection retry 闭环，降低 LLM 自由生成带来的医学幻觉风险。构建 50 条 benchmark case，覆盖单义缩写、歧义缩写、多缩写、候选缺失、低上下文和否定语义保持等场景，并基于错误分析定位 low-context over-expansion 问题。

## 15. 后续优化方向

1. 扩展医学缩写候选库，引入更完整的临床缩写资源。
2. 扩展 SNOMED / UMLS 数据规模，提高标准术语覆盖率。
3. 强化 low-context abstention，当上下文不足时主动拒绝扩写。
4. 将 `MappingSupportVerifier` 接入主链路，减少过度扩写。
5. 增加 FastAPI 接口，形成可调用的后端服务。
6. 增加日志和可视化 trace 页面，方便展示每一步候选、校验和重试过程。
7. 引入更多真实临床文本样本，提升 benchmark 的可信度。
8. 对比不同 embedding 模型和 rerank 策略，做 A/B evaluation。

## 16. 最适合面试强调的三句话

1. 这个项目不是让 LLM 直接生成医学结论，而是用候选召回和医学知识库检索约束 LLM。
2. 我重点解决的是医学缩写的上下文消歧、SNOMED 标准化和扩写结果可验证问题。
3. 系统通过 coverage、verification 和 reflection retry 构建了质量控制闭环，能发现并修正部分错误扩写。

