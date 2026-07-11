# ABBVerifier —— 标准概念忠实性校验 / Grounding Verifier · V11

> 文件:`backend/services/abbr_verifier.py`(约 270 行)
> 相关入口:`verify_mappings()`、`propose_requeries()`；旧入口:`verify()`
> 衔接:第 11 篇 Coverage 已经决定"缩写扩成哪个 expansion";第 12 篇确定性替换已经生成 `expanded_text`;第 06 篇 MedicalRetriever 已经为每个 expansion 检索出 SNOMED/RxNorm 候选。本篇的 ABBVerifier 负责**在这些候选概念里选最忠实的标准概念,或者明确弃码**。
> **V11 必看变化**:Verifier 不再重判"扩写是否正确"。Prompt 明确写着:`Your job is NOT to re-judge whether the abbreviation expansion is correct. That decision has already been made by the abbreviation coverage stage.` 它现在只管 grounding: expansion → candidate standard concept。

## 核心速记

> 1. **一句定位**:ABBVerifier 是标准概念忠实性裁判,负责从检索候选里选择 `chosen_index`,或在没有忠实概念时 abstain/弃码。
> 2. **不越权**:Coverage 管 abbreviation → expansion;Verifier 管 expansion → standard concept。Verifier 不应该推翻 coverage 的扩写选择。
> 3. **只在候选里选**:不能发明 SNOMED/RxNorm 概念,只能返回候选的 0-based `chosen_index` 或 `null`。
> 次要(trivia):旧 `verify()` 仍在文件里,但 V11 主链路主要用 `verify_mappings()`;`propose_requeries()` 给反思重检索用,下一篇/后篇会更细讲。

## 这一段在解决什么

大白话:**扩写已经选好了,现在要判断检索回来的标准概念里,哪个真正表达这个扩写。**

例如:

```text
原句:
"The patient reports CP."

Coverage 已选:
CP → chest pain

MedicalRetriever 检索候选:
0. Chest pain
1. Chest pain rating
2. History of chest pain

ABBVerifier 判断:
0 是忠实概念
1 是评分量表,不是同一个临床实体
2 是病史,多了 history 信息

输出:
chosen_index = 0
standardization_faithful = true
```

如果所有候选都不忠实:

```text
chosen_index = null
standardization_faithful = false
```

后面 `ABBRService` 会把这个 mapping 标为 `WITHHELD`,也就是扩写可以保留,但标准编码弃码。

## 核心1 · V11 分工:Coverage 选扩写,Verifier 选标准概念

这是本篇最重要的边界。

### CoverageEvaluator

问题:

```text
这个缩写在当前上下文里应扩成什么?
```

例子:

```text
CP → chest pain
MS → mitral stenosis
ASA → aspirin
```

### ABBVerifier

问题:

```text
这个 expansion 检索出的候选标准概念里,哪个最忠实?
```

例子:

```text
chest pain → Chest pain
hypertension → Hypertensive disorder
aspirin → aspirin
```

所以 V11 中不要再说:

```text
Verifier 判断扩写是否正确
```

更准确的说法是:

```text
Coverage 决定扩写是否成立;
Verifier 只判断标准概念 grounding 是否忠实。
```

prompt 原文也强调:

```text
Your job is NOT to re-judge whether the abbreviation expansion is correct.
That decision has already been made by the abbreviation coverage stage.
```

## 核心2 · verify_mappings() 的输入结构

入口:

```python
def verify_mappings(
    self,
    original_text: str,
    expanded_text: str,
    mapping_standardizations: list[dict]
)
```

主链路传入的 `mapping_standardizations` 大概是:

```json
[
  {
    "abbreviation": "CP",
    "expansion": "chest pain",
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
```

`verify_mappings()` 会先给每个 candidate 加 index:

```python
indexed_mappings.append({
    "abbreviation": mapping.get("abbreviation"),
    "expansion": mapping.get("expansion"),
    "candidates": [
        {"index": index, **candidate}
        for index, candidate in enumerate(mapping.get("candidates") or [])
    ],
})
```

为什么要 index?

因为 LLM 不应该返回概念文本,而应该返回:

```text
chosen_index = 0 / 1 / 2 / null
```

这样程序可以稳定映射回候选列表。

## 核心3 · 忠实概念的判定标准

prompt 把 faithful 讲得很细。

### 什么算 faithful

```text
candidate concept_name 表示和 expansion 相同的临床实体
```

包括:

```text
1. 精确同义词 / 完全同名
2. 没有精确候选时,更一般但忠实的父概念
```

例子:

```text
expansion = hypertension
candidate = Hypertensive disorder
→ 可以算 faithful
```

```text
expansion = coronary artery disease
candidate = Disorder of coronary artery
→ 可以算 faithful parent
```

### 什么不算 faithful

不忠实的典型情况:

```text
1. 添加了 expansion 没说的限定词
   subtype / cause / stage / acuity / laterality / site

2. 相关但不是同一个临床实体
   rating scale
   measurement
   procedure
   device
   service
   monitoring / education / administration
   risk level
   family history
```

例子:

```text
expansion = chest pain
candidate = Chest pain rating
→ 不 faithful,因为 rating 是评分量表
```

```text
expansion = chest pain
candidate = History of chest pain
→ 不 faithful,因为多了 history
```

这就是 verifier 的核心价值:不盲信向量分数,而是看 concept_name 是否真的表达同一个临床实体。

## 核心4 · 选择规则:能选就选,不能选就弃码

prompt 规则:

```text
chosen_index = BEST faithful candidate 的 0-based index
没有 faithful candidate → chosen_index = null
standardization_faithful = true 只有在 chosen_index 指向忠实候选时才为 true
只能在 supplied candidates 里选
永远不能发明概念
```

还有一个很重要的原则:

```text
Do NOT abstain just because no candidate is a word-for-word match.
```

意思是:

```text
没有完全同名也不要轻易弃码;
忠实同义词或忠实父概念也可以选。
```

这避免系统过度保守。

但同时:

```text
不要选添加信息的更具体 subtype
不要选相关但不同的服务/量表/病史
```

这又避免系统过度乱选。

## 核心5 · 输出结构

LLM 应返回:

```json
{
  "mapping_validations": [
    {
      "abbreviation": "CP",
      "expansion": "chest pain",
      "chosen_index": 0,
      "standardization_faithful": true,
      "reason": "brief explanation"
    }
  ]
}
```

代码包装成:

```python
return {
    "sentence_validity": {
        "is_valid": True,
        "confidence": 1.0,
        "reason": "Expansion validity is decided upstream by coverage.",
        "issues": []
    },
    "mapping_validations": mapping_validations,
    "overall_valid": len(mapping_validations) == len(mapping_standardizations)
}
```

注意这里的 `sentence_validity` 已经不是 V9 那种真实句子级校验。它固定说:

```text
Expansion validity is decided upstream by coverage.
```

也就是说这是为了保持旧返回结构兼容,不是当前 verifier 的核心判断。

JSON 解析失败时:

```python
return {
    "sentence_validity": {...},
    "mapping_validations": [],
    "overall_valid": False,
    "raw_output": content
}
```

解析失败 → 没有 mapping_validations → 后面无法选概念。

## 核心6 · ABBRService 怎么使用 verify_mappings 结果

在 `ABBRService.expand_verify_with_retry()` 中:

```python
verification = self.verifier.verify_mappings(
    original_text=text,
    expanded_text=current_expanded_text,
    mapping_standardizations=mapping_standardizations,
)
validations = verification.get("mapping_validations", [])
```

然后每个 pending record 找自己的 validation:

```python
chosen_index = v.get("chosen_index") if v else None
faithful = bool(v and v.get("standardization_faithful") is True)
valid_index = (
    faithful
    and isinstance(chosen_index, int)
    and not isinstance(chosen_index, bool)
    and 0 <= chosen_index < len(r["std_cache"])
)
```

这里有几个防御点:

```text
standardization_faithful 必须是 True
chosen_index 必须是 int
bool 不算 int
chosen_index 必须在 std_cache 范围内
```

如果 valid:

```python
r["std_concept"] = r["std_cache"][chosen_index]
r["status"] = "CODED"
r["failure"] = None
```

否则:

```python
r["std_concept"] = None
r["status"] = "WITHHELD"
r["failure"] = {
    "type": "CODE_WITHHELD",
    "stage": "standardization",
    "reason": ...,
    "evidence": {"retrieved_top": [...]}
}
```

一句话:

```text
Verifier 选得出忠实概念 → CODED
Verifier 选不出忠实概念 → WITHHELD
```

## 核心7 · CODED 和 WITHHELD 的区别

这点很重要。

### CODED

```text
扩写被 coverage 接受
标准概念也被 verifier 选中
```

结果:

```text
expanded_text 中显示 expansion
standardized_entities 中有 chosen_concept
```

### WITHHELD

```text
扩写被 coverage 接受
但标准概念没有忠实候选
```

结果:

```text
expanded_text 仍可以显示 expansion
但 standardized_entities 不输出 concept
mapping_states 里记录 CODE_WITHHELD
```

为什么这么设计?

因为:

```text
扩写正确 ≠ 标准概念一定可编码
```

如果检索库没召回忠实概念,不能为了有 code 而乱选。V11 选择保守弃码。

## 核心8 · propose_requeries():反思重检索的检索词生成器

`ABBVerifier` 里还有一个重要方法:

```python
def propose_requeries(self, expansion: str, current_concept, seen_concepts):
```

它不是主 verify,而是给反思阶段用。

作用:

```text
当当前 std_concept 非精确或 WITHHELD 时,
让 LLM 提出最多 2 个同义/规范检索词,
再用这些词重新检索候选。
```

它的边界也很严:

```text
只输出 SEARCH WORDS
不能发明 SNOMED concept
不能添加 subtype/cause/stage/site/mechanism
不能重复 expansion 原词
```

代码还额外过滤:

```python
if query_lower == expansion_lower:
    continue
if any(term in query_lower and term not in expansion_lower for term in mechanism_terms):
    continue
```

其中 `mechanism_terms = ("arteriosclerosis", "atherosclerosis")`,用来阻止对 coronary artery disease 这类词引入未陈述机制。

这个函数后面会在反思重检索文档里展开。本篇先记住:

```text
verify_mappings 选概念
propose_requeries 只产新检索词
```

## 数据快照

### 输入

```json
[
  {
    "abbreviation": "CP",
    "expansion": "chest pain",
    "candidates": [
      {"concept_name": "Chest pain", "domain_id": "Condition", "score": 0.91},
      {"concept_name": "Chest pain rating", "domain_id": "Observation", "score": 0.89}
    ]
  }
]
```

### LLM 输出

```json
{
  "mapping_validations": [
    {
      "abbreviation": "CP",
      "expansion": "chest pain",
      "chosen_index": 0,
      "standardization_faithful": true,
      "reason": "Chest pain denotes the same clinical finding as the expansion."
    }
  ]
}
```

### ABBRService 状态更新

```json
{
  "abbreviation": "CP",
  "expansion": "chest pain",
  "status": "CODED",
  "std_concept": {
    "concept_name": "Chest pain"
  }
}
```

### 没有忠实候选时

```json
{
  "chosen_index": null,
  "standardization_faithful": false,
  "reason": "Candidates are related services or measurements, not the clinical entity."
}
```

状态:

```json
{
  "status": "WITHHELD",
  "failure": {
    "type": "CODE_WITHHELD",
    "stage": "standardization"
  }
}
```

## 和 V9/V10 老校验的区别

旧 `verify()` 方法还在:

```python
def verify(self, original_text, expanded_text, standardization):
```

它的 prompt 会判断:

```text
expanded_text 是否保持 original_text 意义
是否只扩写缩写
SNOMED candidates 是否支持扩写
```

但 V11 主链路主要不走它。当前主路走:

```python
verify_mappings()
```

区别:

| 维度 | 旧 verify() | V11 verify_mappings() |
|---|---|---|
| 判断对象 | 整句扩写是否保意 | 每个 expansion 的标准概念候选 |
| 是否重判扩写正确 | 是 | 否,交给 coverage |
| 输出 | is_valid/confidence/issues | chosen_index/standardization_faithful |
| 主链路状态 | 基本旧接口/遗留 | 当前主用 |
| 是否选择概念 index | 否 | 是 |

所以这篇文档的核心不要沿用"双层校验"旧说法。V11 更准确是:

```text
标准概念 grounding verifier
```

## 其余细节(次要,一行带过)

【次要】`ABBVerifier.__init__` 走 `utils.llm_factory.create_llm()`,比 fallback/coverage 的直接 `ChatDeepSeek` 更统一;`verify_mappings()` 会清理 ```json fence;`overall_valid` 当前只是数量一致检查,不是"所有标准化都忠实"的严格总判断;`sentence_validity` 是兼容字段。

## 死代码 / 盲肠提醒

- `verify()` 是旧整句校验接口,当前主链路没有使用,可视为遗留能力/死代码候选。
- 文件底部三引号注释还描述旧的 `context_supported/snomed_supported/is_valid` 结构,和 V11 当前 `chosen_index/standardization_faithful` 不一致。
- `overall_valid` 在 `verify_mappings()` 中只检查返回数量是否等于输入数量,不检查每个 validation 的 faithful 是否为 true。真正是否 CODED 在 `ABBRService` 里逐条判断。
- prompt 多处写 SNOMED,但 V11 多源后 candidates 也可能来自 RxNorm。语义上应改成 standard terminology candidates / SNOMED or RxNorm candidates。

## 优化方向(更好 / 更稳)

1. **重命名 prompt 里的 SNOMED**:改成 "standard terminology candidates (SNOMED/RxNorm)" 以匹配多源事实。
2. **增强 output 校验**:检查每个 validation 的 abbreviation/expansion 是否与输入一致,chosen_index 是否合法,数量是否一致。
3. **让 overall_valid 更名**:当前它不是最终有效性,更像 `response_shape_valid`;避免误解。
4. **拆掉旧 verify 或标 deprecated**:减少文档和代码读者混淆。
5. **加入确定性规则辅助**:exact match 可以先规则通过或强加解释,LLM 专注复杂候选。
6. **cross-model verifier**:如果生成/coverage 和 verifier 都用同一模型,有同源判断风险;可用不同 provider 做裁判。
7. **候选证据压缩**:候选很多时 prompt 会变长,可只传必要字段和 top-k。
8. **为 RxNorm 增加药品专用 rubric**:药品成分、商品名、剂型、强度的忠实标准与 SNOMED 疾病概念不完全一样。

## 会被追问 / 诚实局限(主动说)

- **裁判仍是 LLM**:会误选,不能说绝对可靠。
- **同源盲区**:Coverage、Fallback、Verifier 多数都用 DeepSeek,同一模型可能有一致性偏差。
- **只能在候选里选**:如果 retriever 没召回正确概念,verifier 无法凭空补出正确 code。
- **prompt 仍写 SNOMED**:对 RxNorm 多源不够严谨,需要修正措辞。
- **旧方法和旧注释会误导**:文件里同时存在旧 verify 和新 verify_mappings,读代码时要分清主链路。

## 面试怎么说

**合格版(30 秒)**:
> ABBVerifier 在 V11 里主要做标准概念 grounding。Coverage 已经决定缩写扩成什么,Verifier 不再重判扩写是否正确,而是在 MedicalRetriever 检索出的候选概念里选择最忠实的 `chosen_index`;如果没有忠实候选,就返回 null,系统把该 mapping 标成 WITHHELD,不乱给 code。

**优秀版(1 分钟)**:
> 我把扩写选择和标准概念选择拆开了。Coverage 负责 abbreviation 到 expansion,Verifier 负责 expansion 到 standard concept。`verify_mappings()` 会把每个候选概念编号,让 LLM 只能返回候选 index 或 null,不能发明概念。Prompt 里定义了 faithful 的标准:同一临床实体、同义词或忠实父概念可以选;但添加了 subtype/cause/stage/site,或者变成 rating、procedure、history、service 这类相关但不同的概念,必须弃码。ABBRService 会检查 chosen_index 合法且 standardization_faithful 为 true 才 CODED,否则 WITHHELD。这样扩写和编码解耦:扩写可以保留,但没有忠实标准概念时不强行编码。

## 易错点 / 面试问答

**Q:Verifier 会判断 CP 应不应该扩成 chest pain 吗?**  
A:V11 主链路里不会。这个判断由 Coverage 完成。Verifier 只判断 chest pain 检索到的候选标准概念哪个忠实。

**Q:chosen_index 是什么?**  
A:检索候选列表的 0-based index。LLM 只能返回这个 index 或 null,程序再用它取回候选 concept。

**Q:没有完全同名候选怎么办?**  
A:不一定弃码。忠实同义词或更一般但不添加信息的父概念也可以选。

**Q:什么时候 WITHHELD?**  
A:没有 faithful candidate、chosen_index 非法、standardization_faithful 不是 true、或 JSON 解析失败导致没有 validation,都会导致无法 CODED,进入 WITHHELD。

**Q:扩写 WITHHELD 后 expanded_text 会怎样?**  
A:WITHHELD 不等于撤销扩写。扩写仍可显示,只是没有 chosen_concept,API 的 standardized_entities 不输出该 code。

**Q:它支持 RxNorm 吗?**  
A:数据链路支持,因为 candidates 来自 source 路由后的检索结果;但 prompt 文案仍偏 SNOMED,这是需要修正的文档/提示词债务。

## 一句话总结

> ABBVerifier 在 V11 中是标准概念忠实性裁判:Coverage 已经决定 expansion,Verifier 只在检索候选里选择最忠实的 standard concept index,没有忠实候选就弃码。它不能发明概念,也不重判扩写正确性;ABBRService 会用 `chosen_index + standardization_faithful` 决定 record 是 `CODED` 还是 `WITHHELD`。它让"扩写文本"和"标准编码"解耦,避免为了有 code 而乱选概念。
