# ABBRCandidateCoverageEvaluator —— 覆盖度闸门 / 候选中选唯一扩写 · V11

> 文件:`backend/services/abbr_candidate_coverage_evaluator.py`(约 90 行)
> 衔接:第 09/10 篇负责把候选召回来:本地词典候选可能多义,fallback LLM 候选可能带噪声。本篇负责第一道质控:判断候选集中是否有上下文支持的扩写,并从支持的候选里选出一个 `best_expansion`。
> **V11 必看变化**:Coverage 不只是"候选够不够"。当前代码里,它还要返回 `best_expansion`,而 `ABBRService` 会直接把这个 best 作为该缩写的扩写结果。它仍然不负责 SNOMED/RxNorm 标准概念是否忠实,但它已经负责"扩写候选选唯一"。

## 核心速记

> 1. **一句定位**:CoverageEvaluator 是候选召回后的上下文闸门,回答两个问题:候选集中有没有合理扩写?如果有,当前上下文最适合哪一个?
> 2. **它不能发明新候选**:`best_expansion` 必须从候选列表原文复制,不能改写、不能新增。这是防幻觉核心。
> 3. **V11 主链路直接采用 best**:`coverage.get("best_expansion")` 会进入 record 的 `expansion`,后面用于确定性替换和标准概念检索。
> 次要(trivia):JSON 解析失败时返回 `coverage_ok=False`,这是偏保守设计;fallback 候选还会额外要求 coverage confidence >= 0.8。

## 这一段在解决什么

大白话:**召回层给了一堆候选,这一层判断哪些候选在原句里说得通,并选出当前最合适的那个。**

例如:

```text
原句:
"The patient has MS with a diastolic murmur."

缩写:
MS

候选:
multiple sclerosis
mitral stenosis

Coverage 判断:
diastolic murmur 更支持心脏瓣膜病

输出:
coverage_ok = true
plausible_candidates = ["mitral stenosis"]
best_expansion = "mitral stenosis"
```

这一步解决的是"缩写扩写候选选择"。它还没有解决"mitral stenosis 应该对应哪个标准概念",那是后面 `MedicalRetriever + ABBVerifier` 的事。

## 核心1 · 它问的不是"标准概念对不对",而是"扩写候选能不能用"

prompt 里写得很清楚:

```text
Coverage evaluation asks:
"Is there at least one reasonable candidate in this candidate set?"

It does NOT need to perform final expansion.
It should not rewrite the clinical text.
```

V11 这里要稍微拆细:

```text
它不改写整句
它不检索 SNOMED/RxNorm
它不选择标准概念

但它会:
  判断候选集中哪些扩写上下文合理
  从中选一个 best_expansion
```

所以它的边界是:

```text
负责: abbreviation → expansion 的上下文选择
不负责: expansion → standard concept 的忠实选择
```

这和后面的 `ABBVerifier.verify_mappings()` 分工不同:

```text
CoverageEvaluator
  CP → chest pain 是否适合原句?

ABBVerifier
  chest pain → 检索候选里哪个 SNOMED/RxNorm 概念忠实?
```

## 核心2 · prompt 的关键规则

输入给 LLM 的信息:

```python
original_text
abbreviation
candidates
```

候选会用 JSON 传进去:

```python
json.dumps(candidates, ensure_ascii=False, indent=2)
```

核心规则:

```text
1. 至少一个候选上下文合理 → coverage_ok = true
2. 没有候选适合上下文 → coverage_ok = false
3. candidates 为空 → coverage_ok = false
4. 上下文不足但候选包含常见含义 → coverage_ok = true,但 confidence 低
5. 不许发明新候选
8. 从 plausible candidates 中选一个 SINGLE best_expansion
9. coverage_ok=false 时 best_expansion=null
10. best_expansion 必须从候选列表逐字复制
```

最关键的是第 5 和第 10 条:

```text
只能裁决给定候选
不能自己编一个更顺口的扩写
```

这保持了 V11 的受控候选思想。

## 核心3 · 输出结构

要求返回:

```json
{
  "abbreviation": "CP",
  "coverage_ok": true,
  "confidence": 0.92,
  "plausible_candidates": [
    "chest pain"
  ],
  "best_expansion": "chest pain",
  "reason": "brief explanation",
  "issues": []
}
```

字段含义:

```text
coverage_ok
  候选集中是否至少有一个合理扩写

confidence
  LLM 对这个 coverage 判断的置信度,不是严格校准概率

plausible_candidates
  候选中哪些扩写被上下文支持

best_expansion
  单个最终扩写选择,必须来自候选原文

reason / issues
  解释和问题标签
```

解析失败时返回:

```json
{
  "abbreviation": "CP",
  "coverage_ok": false,
  "confidence": 0.0,
  "plausible_candidates": [],
  "reason": "Coverage evaluator did not return valid JSON.",
  "issues": ["invalid_json"],
  "raw_output": "..."
}
```

这是安全侧兜底:LLM 输出解析不了,就不扩。

## 核心4 · ABBRService 怎么使用 coverage 结果

调用位置在 `ABBRService._get_abbreviation_candidates()`:

```python
coverage = self.coverage_evaluator.evaluate(
    original_text=text,
    abbreviation=abbr,
    candidates=candidates
)
```

### 1. 生成 filtered_candidates

```python
plausible_expansions = coverage.get("plausible_candidates", [])

filtered_candidates = [
    candidate
    for candidate in candidates
    if candidate["expansion"] in plausible_expansions
]
```

含义:

```text
coverage 返回哪些 expansion 合理
  ↓
上游用字符串匹配,把原 candidates 过滤成 filtered_candidates
```

注意:这里是字符串精确匹配,如果 LLM 返回大小写/措辞不一致,可能匹配失败。

### 2. 直接取 best_expansion

```python
best = coverage.get("best_expansion")
```

后面会写入:

```python
"best_expansion": best
```

再进入 record:

```python
rec = {
    ...
    "expansion": best if best else None,
    "status": "PENDING" if best else "NOT_EXPANDED",
    ...
}
```

也就是说:

```text
coverage best_expansion 有值
  → 该缩写进入 PENDING
  → 后面会确定性替换
  → 再去检索标准概念

coverage best_expansion 为空
  → NOT_EXPANDED
  → 不替换原句
```

这就是它在 V11 中的重要性。

### 3. fallback 候选额外收紧

如果候选来自 fallback:

```python
if candidate_source == "fallback":
    conf = coverage.get("confidence") or 0.0
    if (not coverage.get("coverage_ok")) or conf < 0.8:
        best = None
```

含义:

```text
primary 候选:
  coverage 给 best 即可进入后续

fallback 候选:
  coverage_ok 必须为 true
  confidence 必须 >= 0.8
  否则 best 清空
```

为什么?

因为 fallback 候选是 LLM 生成的,风险更高;本地词典候选是人工策展的,相对可信。

## 核心5 · Coverage 和 Verification 的区别

这两个非常容易混。

### CoverageEvaluator 管扩写候选

输入:

```text
原句
缩写
候选 expansions
```

输出:

```text
coverage_ok
plausible_candidates
best_expansion
```

问题:

```text
CP 在这句话里是不是 chest pain?
MS 在这句话里是不是 mitral stenosis?
候选集中有没有合理扩写?
```

### ABBVerifier 管标准概念忠实性

输入:

```text
原句
扩写后的句子
每个 expansion 的 SNOMED/RxNorm 候选概念
```

输出:

```text
chosen_index
standardization_faithful
reason
```

问题:

```text
chest pain 检索出来的候选里,哪个概念最忠实?
如果没有忠实概念,是否应该弃码?
```

一句话:

```text
Coverage: 缩写扩成什么
Verifier: 扩写词标准化成哪个概念
```

## 数据快照

### 输入

```python
evaluate(
    original_text="The patient has CP after exertion.",
    abbreviation="CP",
    candidates=[
        {"abbreviation": "CP", "expansion": "chest pain", "domain": "Condition"},
        {"abbreviation": "CP", "expansion": "cerebral palsy", "domain": "Condition"},
        {"abbreviation": "CP", "expansion": "chronic pancreatitis", "domain": "Condition"}
    ]
)
```

### 输出

```json
{
  "abbreviation": "CP",
  "coverage_ok": true,
  "confidence": 0.93,
  "plausible_candidates": ["chest pain"],
  "best_expansion": "chest pain",
  "reason": "Exertional CP commonly refers to chest pain in clinical context.",
  "issues": []
}
```

### 上游转换成 record

```json
{
  "abbreviation": "CP",
  "candidates": [
    {"abbreviation": "CP", "expansion": "chest pain", "domain": "Condition"}
  ],
  "coverage": {
    "coverage_ok": true,
    "confidence": 0.93,
    "best_expansion": "chest pain"
  },
  "candidate_source": "primary",
  "best_expansion": "chest pain",
  "chosen_domain": "Condition"
}
```

再进入 record:

```json
{
  "abbreviation": "CP",
  "expansion": "chest pain",
  "domain": "Condition",
  "status": "PENDING"
}
```

## coverage_failed 是怎么来的

如果所有缩写都没有 best expansion:

```python
if not _expanded(records):
    ...
    "stop_reason": "coverage_failed_no_valid_expansion"
```

最终返回:

```json
{
  "success": false,
  "reason": "No valid abbreviation expansion found. Candidate coverage failed."
}
```

每个未扩写 record 会带 failure:

```json
{
  "type": "ABBR_NOT_EXPANDED",
  "stage": "coverage",
  "reason": "coverage withheld expansion (not confident enough)",
  "evidence": {
    "coverage_confidence": 0.42,
    "coverage_ok": false,
    "candidates_seen": ["..."]
  }
}
```

所以 coverage 不只是过滤,也会直接决定系统是否早停。

## 其余细节(次要,一行带过)

【次要】它直接实例化 `ChatDeepSeek`,没有走 `utils.llm_factory`;`temperature=0` 保持稳定;`parsed.setdefault("best_expansion", None)` 防止旧输出缺字段;prompt 明确 `Do not use markdown`,但代码仍清理 ```json fence,属于防御式处理。

## 死代码 / 盲肠提醒

- 本文件没有明显死代码。
- `coverage_ok` 和 `best_expansion` 可能不一致,比如 LLM 返回 `coverage_ok=true` 但 `best_expansion=null`;代码没有强校验,后续会因为 best 为空而不扩。
- `plausible_candidates` 用字符串匹配回原候选,这是脆弱耦合。
- `confidence` 是 LLM 自报,不是校准概率。fallback 阈值 0.8 是工程闸门,不是统计意义上的置信水平。

## 优化方向(更好 / 更稳)

1. **让 coverage 返回候选 index/id**:不要返回 expansion 字符串,避免大小写/同义改写导致匹配失败。
2. **强校验 best_expansion**:解析后检查 best 是否严格属于 candidates expansion;不属于就置空并记录 issue。
3. **统一 LLM factory**:和 `ABBVerifier` 一样走 `utils.llm_factory`,减少 LLM 初始化分散。
4. **把 fallback 阈值配置化**:`0.8` 可放到 env 或 config,方便做 ablation。
5. **减少低风险调用**:单义 primary 候选是否可以规则直通或轻量判断,减少 LLM 成本。但医疗场景要谨慎。
6. **保存 reason 到 failure evidence**:coverage 拒绝时,把 reason 更完整地写进日志,方便错误分析。
7. **分离 coverage 与 selection**:未来可以拆成两个字段/两个步骤:是否覆盖、选哪个 best,让日志更清晰。

## 会被追问 / 诚实局限(主动说)

- **coverage 自己也是 LLM 判断**:会误判。可能把该扩的拒掉,也可能把不该扩的放过。
- **字符串映射脆弱**:`plausible_candidates` 和 `best_expansion` 必须逐字来自候选,但代码只靠 prompt 约束。
- **fallback 阈值是经验值**:0.8 是工程保守闸门,需要 benchmark 支持,不能说是医学概率。
- **它已经承担扩写选择**:不要再按旧说法说它"不选最终答案"。准确说:它选最终 expansion,但不选最终 standard concept。
- **成本叠加**:fallback 可能一次 LLM,coverage 又一次 LLM,多缩写文本成本会增长。

## 面试怎么说

**合格版(30 秒)**:
> CoverageEvaluator 是候选召回后的上下文闸门。它拿原句、缩写和候选列表,判断候选集中有没有上下文支持的扩写,返回 coverage_ok、plausible_candidates 和 best_expansion。V11 会直接用 best_expansion 作为该缩写的扩写,但标准概念是否忠实还要交给后面的 verifier。

**优秀版(1 分钟)**:
> 这层解决的是"候选够不够、该选哪个扩写"。primary 词典会高召回地列出多义候选,fallback 也可能带噪声,coverage evaluator 用上下文判断哪些候选合理,并且要求 best_expansion 必须逐字来自候选列表,不能让 LLM 发明新扩写。V11 里这个 best 会直接进入 per-abbreviation record,后面由确定性替换生成 expanded_text,再去检索 SNOMED/RxNorm 候选,由 verifier 选择标准概念或弃码。fallback 候选还额外要求 coverage_ok 且 confidence >= 0.8。诚实说,coverage 也是 LLM 裁判,会有误判;而且当前 plausible_candidates 用字符串匹配回候选,比较脆,更稳的实现应该返回候选 index。

## 易错点 / 面试问答

**Q:Coverage 和 Verification 有什么区别?**  
A:Coverage 选 expansion,Verification 选 standard concept。Coverage 判断 CP 是否应扩成 chest pain;Verification 判断 chest pain 应该对齐哪个 SNOMED/RxNorm 概念。

**Q:Coverage 会直接改写原句吗?**  
A:不会。它只返回 best_expansion。真正改写原句由 `ABBRService._build_expanded_text_deterministic()` 做。

**Q:best_expansion 可以是 LLM 自己想出来的吗?**  
A:按 prompt 不可以,必须从候选列表逐字复制。但代码层面目前主要靠 prompt 约束,后续应加硬校验。

**Q:coverage_ok=false 会怎样?**  
A:best_expansion 应为空,record 会是 NOT_EXPANDED。如果所有缩写都没有扩写,主流程会 coverage_failed 早停。

**Q:fallback 候选为什么更严格?**  
A:fallback 候选是 LLM 生成的,比本地词典更容易幻觉。所以 V11 要求 coverage_ok 且 confidence >= 0.8 才采用。

**Q:confidence 能不能当真实概率?**  
A:不能。它是 LLM 自报的判断置信度,是工程信号,不是校准医学概率。

## 一句话总结

> ABBRCandidateCoverageEvaluator 是 V11 缩写扩写的上下文闸门:它在候选召回之后判断候选集中是否有合理扩写,挑出 plausible_candidates,并返回单个 `best_expansion` 供 ABBRService 后续确定性替换。它不能发明候选,只从给定列表里选;它不负责标准概念选择,那是 verifier 的事。fallback 候选还会被 coverage_ok 和 confidence >= 0.8 额外收紧。它提升了精度和"不该扩就不扩"的能力,但也有 LLM 误判、字符串匹配脆弱和成本叠加这些边界。
