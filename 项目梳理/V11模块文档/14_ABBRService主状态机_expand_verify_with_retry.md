# ABBRService 主状态机 —— expand_verify_with_retry · V11

> 文件:`backend/services/abbr_service.py`
> 入口:`ABBRService.expand_verify_with_retry(text, max_retries=2)`
> 衔接:前面 09-13 篇讲的是零件:主候选召回、fallback 候选、coverage、确定性替换、retriever、verifier。本篇是装配图:一个请求进来后,这些零件如何被串成一条 V11 主链路。
> **V11 必看变化**:这里已经不是 V9/V10 那种"扩写整句 → verify 不过 → reflect 重写整句 → retry"。当前实现是**统一 per-abbreviation record 状态机**:每个缩写从候选召回一路带着 `status/std_cache/std_concept/failure`,标准化失败时做的是候选重检索反思,不是重新生成整句扩写。

## 核心速记

> 1. **一句定位**:`expand_verify_with_retry()` 是 V11 主编排。它把每个缩写变成一个 record,统一管理扩写、检索、校验、状态和失败原因。
> 2. **状态机核心**:`NOT_EXPANDED / PENDING / CODED / WITHHELD / ABSTAIN`。这五个状态比单纯 `success=true/false` 更能解释系统为什么这么返回。
> 3. **扩写和编码解耦**:Coverage 决定是否扩写;Verifier 只决定是否能选出忠实标准概念。扩写可以成功但编码 `WITHHELD`。
> 次要(trivia):`max_retries` 参数还在,但当前主循环里 pending record 第一轮就会转成 `CODED` 或 `WITHHELD`,所以它不像旧版那样驱动多轮整句重写。

## 这一段在解决什么

大白话:**一句临床文本进来,这里负责把所有缩写从"发现候选"一路处理到"最终扩写文本 + 标准概念 + 状态解释"。**

例如:

```text
输入:
"The patient denies SOB but reports CP."

主状态机做:
1. 找到 SOB / CP
2. 查候选并用 coverage 选 expansion
3. 把原句确定性替换成 expanded_text
4. 对每个 expansion 检索 SNOMED/RxNorm 候选
5. verifier 选择忠实标准概念或弃码
6. 必要时做标准化反思重检索
7. 返回 expanded_text、mappings、mapping_standardizations、mapping_states
```

它是前面所有模块的汇合点。

## 核心1 · 初始化:把主链路零件都备齐

`ABBRService.__init__` 里创建:

```python
self.standardizer = MedicalStandardizer()
self.ner_service = self.standardizer.ner_service
self.retriever = MedicalRetriever()
self.verifier = ABBVerifier()
self.candidate_retriever = ABBRCandidateRetriever()
self.fallback_retriever = ABBRCandidateFallbackRetriever()
self.coverage_evaluator = ABBRCandidateCoverageEvaluator()
```

对应能力:

```text
candidate_retriever       本地词典候选召回
fallback_retriever        LLM 兜底候选召回
coverage_evaluator        候选 coverage + best_expansion
ner_service               给 fallback 候选推 domain
retriever                 标准概念候选检索
verifier                  忠实标准概念选择/弃码
standardizer              旧整句标准化能力,当前主要为了复用 ner_service
```

注意:

```text
self.llm 和 self.abbr_dict 也还在 __init__ 里,
但 V11 当前主扩写链路不是靠 self.llm 直接改写整句,
也不是靠 self.abbr_dict 那 6 条旧硬编码词典。
```

## 核心2 · 第一步:候选召回 + coverage 选 best_expansion

主函数开头:

```python
attempts = []
candidate_infos = self._get_abbreviation_candidates(text)
current_abbreviation_candidates = candidate_infos
mapping_support_results = []
standardization_result = None
```

`_get_abbreviation_candidates(text)` 已经完成:

```text
token gate
  ↓
primary 本地候选召回
  ↓ 如无候选
fallback LLM 兜底候选
  ↓
fallback 候选补 domain
  ↓
coverage_evaluator.evaluate()
  ↓
best_expansion / chosen_domain
```

返回的每个 `info` 大概是:

```json
{
  "abbreviation": "CP",
  "candidates": [...],
  "filtered_candidates": [...],
  "coverage": {...},
  "candidate_source": "primary",
  "best_expansion": "chest pain",
  "chosen_domain": "Condition"
}
```

这一步决定:

```text
哪些缩写有 expansion
哪些缩写没有 expansion
每个 expansion 的 domain 是什么
```

## 核心3 · 第二步:把每个缩写变成统一 record

V11 的关键是这个 record:

```python
rec = {
    "abbreviation": info.get("abbreviation"),
    "source": info.get("candidate_source"),
    "candidates": info.get("candidates") or [],
    "coverage": info.get("coverage") or {},
    "expansion": best if best else None,
    "label": info.get("chosen_label"),
    "domain": info.get("chosen_domain"),
    "std_cache": None,
    "std_concept": None,
    "status": "PENDING" if best else "NOT_EXPANDED",
    "failure": None,
}
```

字段解释:

```text
abbreviation      原缩写,如 CP
source            primary / fallback / none
candidates        召回候选
coverage          coverage 判断结果
expansion         coverage 选出的 best_expansion
domain            expansion 对应 domain
std_cache         后续检索到的标准概念候选
std_concept       verifier 最终选中的标准概念
status            生命周期状态
failure           失败原因与证据
```

这就是 V11 的统一数据流:一个缩写从头到尾都用同一个 record 表示,不再散落在多个列表里。

## 核心4 · 五种状态

### NOT_EXPANDED

```text
coverage 没有给 best_expansion
或 primary/fallback 都没有候选
```

代码:

```python
"status": "PENDING" if best else "NOT_EXPANDED"
```

失败原因:

```json
{
  "type": "ABBR_NOT_EXPANDED",
  "stage": "coverage",
  "reason": "coverage withheld expansion (not confident enough)",
  "evidence": {
    "coverage_confidence": 0.0,
    "coverage_ok": false,
    "candidates_seen": []
  }
}
```

### PENDING

```text
已有 expansion,等待标准概念检索和 verifier 裁决
```

### CODED

```text
verifier 选出了忠实标准概念
std_concept 有值
```

### WITHHELD

```text
expansion 有了,但没有忠实标准概念可选
扩写保留,编码弃掉
```

### ABSTAIN

```text
循环结束后仍然 PENDING 的兜底状态
```

当前代码里,正常情况下 PENDING 会在第一轮转成 CODED 或 WITHHELD,所以 ABSTAIN 更像安全兜底。

## 核心5 · _expanded 和 _visible 的区别

内部函数:

```python
def _expanded(recs):
    return [r for r in recs if r["expansion"]]

def _visible(recs):
    return [r for r in recs if r["expansion"] and r["status"] != "ABSTAIN"]
```

含义:

```text
_expanded:
  有 expansion 的 record,用于判断系统是否至少扩出了一个缩写

_visible:
  有 expansion 且不是 ABSTAIN 的 record,用于构造 expanded_text
```

这说明:

```text
WITHHELD 仍然 visible
```

也就是说:

```text
标准概念弃码 ≠ 撤销文本扩写
```

这正是 V11 扩写和编码解耦的体现。

## 核心6 · 早停:一个扩写都没有就 coverage_failed

代码:

```python
if not _expanded(records):
    ...
    "stop_reason": "coverage_failed_no_valid_expansion"
    ...
    return {
        "success": False,
        "reason": "No valid abbreviation expansion found. Candidate coverage failed."
    }
```

含义:

```text
所有 record 都没有 expansion
  → 没有任何东西可替换
  → 没有必要继续检索标准概念
  → 直接返回 coverage_failed
```

这是很重要的工程判断:

```text
没有 expansion 时,检索和 verifier 都没有意义;
宁可不扩,不强行编。
```

早停时也会:

```python
collect_unresolved(text, records)
```

用于错误日志/后续 triage。

## 核心7 · 标准概念检索:只处理 PENDING record

主循环:

```python
for attempt_index in range(max_retries + 1):
    pending = [r for r in records if r["status"] == "PENDING"]
    if not pending:
        break
```

对每个 pending:

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

注意这里串起了多个前文模块:

```text
query = coverage 选出的 expansion
domain_boost = candidate domain
source = _route_source(domain)
  Drug → rxnorm
  其它 → snomed
retriever = MedicalRetriever
```

结果写入:

```python
r["std_cache"] = [
    {
        "concept_id": ...,
        "concept_name": ...,
        "domain_id": ...,
        "concept_code": ...,
        "score": ...,
        "rerank_score": ...,
    }
    for d in docs[:10]
]
```

也就是每个 record 自己携带标准概念候选池。

## 核心8 · verifier:从 std_cache 里选 std_concept

构造输入:

```python
mapping_standardizations = [
    {
        "abbreviation": r["abbreviation"],
        "expansion": r["expansion"],
        "candidates": r["std_cache"]
    }
    for r in pending
]
```

调用:

```python
verification = self.verifier.verify_mappings(
    original_text=text,
    expanded_text=current_expanded_text,
    mapping_standardizations=mapping_standardizations,
)
```

处理结果:

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

如果合法:

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
    "evidence": {
        "retrieved_top": [...]
    }
}
```

这一步的核心:

```text
verifier 不决定 expansion 是否保留
verifier 只决定有没有忠实 code
```

## 核心9 · 标准化反思:WITHHELD 可被救回 CODED

在 verifier 后:

```python
for r in pending:
    self._reflect_refine_standardization(r, text, current_expanded_text)
    if r.get("std_concept") and r["status"] == "WITHHELD":
        r["status"] = "CODED"
        r["failure"] = None
```

含义:

```text
如果初次 verifier 没选到忠实概念,
或选到的概念不够精确,
_reflect_refine_standardization() 可以让 verifier 提新检索词,
重新检索候选,
再 verify,
如果拿到更好 std_concept,就从 WITHHELD 救回 CODED。
```

注意这不是旧版"重新扩写整句":

```text
反思对象 = 标准概念检索/候选池
不是 expansion 本身
```

更细的反思机制可放到后续单篇文档讲。

## 核心10 · attempts 记录每轮中间结果

每轮 append:

```python
attempts.append({
    "attempt": attempt_index + 1,
    "expanded_text": current_expanded_text,
    "abbreviation_candidates": current_abbreviation_candidates,
    "mappings": [...],
    "standardization": standardization_result,
    "mapping_standardizations": mapping_standardizations,
    "verification": verification,
    "mapping_support_results": mapping_support_results,
})
```

它用于调试/评估:

```text
这一轮 expanded_text 是什么?
每个 abbreviation 候选是什么?
mapping_standardizations 里候选有哪些?
verifier 怎么判?
```

注意:

```text
standardization_result 当前始终是 None
mapping_support_results 当前也是空列表
```

这是为了兼容旧结构/保留扩展口子,不是当前主判断依据。

## 核心11 · 最终输出怎么组装

循环结束后:

```python
resolved = [r for r in records if r["status"] in ("CODED", "WITHHELD")]
```

只有 CODED/WITHHELD 进入 final mappings:

```python
final_mappings = [
    {
        "abbreviation": r["abbreviation"],
        "expansion": r["expansion"],
        "label": r["label"],
        "source": r["source"]
    }
    for r in resolved
]
```

成功条件:

```python
success = len(_expanded(records)) > 0 and all(
    r["status"] in ("CODED", "WITHHELD")
    for r in _expanded(records)
)
```

含义:

```text
至少有一个 expansion
并且所有有 expansion 的 record 都已经落到 CODED 或 WITHHELD
```

注意:

```text
WITHHELD 也算 success 条件里的已处理状态
```

因为 WITHHELD 的含义是:

```text
扩写可接受,只是没有忠实标准概念可编码
```

最终:

```python
final_result = {
    "expanded_text": current_expanded_text,
    "mappings": final_mappings,
    "mapping_standardizations": [
        {
            "abbreviation": r["abbreviation"],
            "expansion": r["expansion"],
            "candidates": r["std_cache"],
            "chosen_concept": r["std_concept"]
        }
        for r in resolved
    ],
    "mapping_states": [...]
}
```

API `/expand/simple` 后面会从 `mapping_standardizations` 里挑 `chosen_concept` 非空的项,组成 `standardized_entities`。

## 数据流总图

```text
text
  ↓
_get_abbreviation_candidates()
  ↓
candidate_infos
  ↓
records
  ├─ no expansion → NOT_EXPANDED
  └─ has expansion → PENDING
        ↓
_build_expanded_text_deterministic()
        ↓
MedicalRetriever.retrieve(expansion, domain_boost, source)
        ↓
std_cache
        ↓
ABBVerifier.verify_mappings()
        ├─ chosen_index valid → CODED
        └─ no faithful concept → WITHHELD
                 ↓
          _reflect_refine_standardization()
                 └─ may rescue → CODED
        ↓
final_result
  ├─ expanded_text
  ├─ mappings
  ├─ mapping_standardizations
  └─ mapping_states
```

## 和旧版文档最大的区别

旧版常说:

```text
扩写 → verify → reflect → retry
```

而 V11 当前代码更准确是:

```text
coverage 选 expansion
  ↓
每个 abbreviation record 独立检索标准概念
  ↓
verifier 选择 code 或 withheld
  ↓
标准化反思尝试改善 code
```

`max_retries` 仍在函数签名里,但当前循环中:

```text
PENDING 第一轮就会转成 CODED 或 WITHHELD
下一轮 pending 为空,循环 break
```

所以不要把它讲成"最多三轮整句扩写重试"。那是旧主线叙述。

## 其余细节(次要,一行带过)

【次要】`collect_unresolved(text, records)` 在 coverage_failed 和最终返回前都会尝试记录 unresolved;异常被吞掉,避免日志系统影响主链路;`final_expanded_text` 和 `final_result["expanded_text"]` 基本一致;`label` 当前多为 None;`attempt` 是 attempts 数量,不是复杂 retry 轮数。

## 死代码 / 盲肠提醒

- `standardization_result = None` 当前没有被填充,但仍放进 attempts/final_result。
- `mapping_support_results = []` 当前没有实际填充,属于兼容/预留字段。
- `max_retries` 在当前状态机里作用有限,不像旧版那样驱动整句扩写多轮重写。
- `ABSTAIN` 状态当前更多是安全兜底,正常 verifier 后 PENDING 会变 CODED/WITHHELD。
- `standardizer = MedicalStandardizer()` 主要为了复用 `ner_service`,但会顺带创建 retriever/std_service,可能重复初始化底座。

## 优化方向(更好 / 更稳)

1. **明确 max_retries 语义**:如果不再做整句 retry,可移除或改名;如果想保留,应让反思失败后重新进入 PENDING 机制更清晰。
2. **拆分主函数**:`expand_verify_with_retry()` 已经承担候选、record、检索、verify、输出组装多件事,可拆成 `_build_records/_retrieve_records/_verify_records/_build_final_result`。
3. **清理兼容字段**:`standardization_result`、`mapping_support_results` 若长期不用,应标 deprecated 或删除。
4. **减少重复初始化**:ABBRService 可直接注入 NERService,不必为了 `ner_service` 创建整个 MedicalStandardizer。
5. **status 枚举化**:把字符串状态改成 Enum/常量,避免拼写错误。
6. **完善 mapping_states 输出**:加入 domain、source、coverage reason、chosen concept summary,便于前端/日志分析。
7. **精细化 success**:现在 WITHHELD 也算 success;可考虑单独返回 `expansion_success` 和 `coding_success`。
8. **为主状态机补单测**:尤其是 NOT_EXPANDED、WITHHELD、CODED、fallback confidence 低拒绝等分支。

## 会被追问 / 诚实局限(主动说)

- **WITHHELD 也算 success**:因为它表示扩写被接受但没有忠实 code。面试时要说清这是 expansion success,不是 full coding success。
- **max_retries 名实不完全一致**:当前不是旧的多轮整句扩写 retry。
- **反思补救的是标准化检索,不是重新判断 expansion**。
- **旧字段仍在返回结构里**:为了兼容,但会让读代码的人困惑。
- **主函数偏长**:可读性和测试粒度还有提升空间。

## 面试怎么说

**合格版(30 秒)**:
> `expand_verify_with_retry()` 是 V11 主状态机。它先通过 gate、primary/fallback、coverage 得到每个缩写的 best_expansion,再把每个缩写统一成 record。没有 expansion 的是 NOT_EXPANDED,有 expansion 的进入 PENDING。随后对每个 PENDING expansion 检索标准概念候选,交给 verifier 选择忠实 concept;选到就是 CODED,选不到就是 WITHHELD,必要时用反思重检索救回。

**优秀版(1 分钟)**:
> V11 的主链路是 per-abbreviation record 状态机,不是旧版整句反复重写。每个缩写从候选召回开始就带着同一个 record 往下走,里面有 expansion、domain、std_cache、std_concept、status 和 failure。Coverage 决定 expansion,确定性替换生成 expanded_text;标准化阶段根据 domain 路由到 SNOMED/RxNorm 检索候选,verifier 只在候选里选忠实概念,选不到就 WITHHELD。WITHHELD 不会撤销扩写,只是不给标准 code。这样扩写和编码解耦,也能通过 mapping_states 解释每个缩写为什么成功、为什么弃码。诚实说,当前 max_retries 这个名字有历史包袱,standardization_result/mapping_support_results 也是兼容字段,主函数后续应该拆小并清理。

## 易错点 / 面试问答

**Q:V11 还会反复重写 expanded_text 吗?**  
A:不会按旧版那种方式。当前 coverage 选 expansion 后,反思主要补救标准化候选/检索词,不是重新生成整句扩写。

**Q:WITHHELD 是失败吗?**  
A:不是扩写失败。它表示扩写可以保留,但没有忠实标准概念可编码。API 的 standardized_entities 不会输出它的 concept。

**Q:success=true 是否代表所有缩写都编码成功?**  
A:不一定。当前 success 条件允许 WITHHELD,所以更像 expansion pipeline 已处理完成。是否有 code 要看 chosen_concept。

**Q:max_retries=2 表示最多三轮吗?**  
A:代码结构是 `range(max_retries+1)`,但当前 PENDING 第一轮会转成 CODED/WITHHELD,下一轮通常无 pending 而 break,所以它不等同旧版三轮整句重写。

**Q:标准概念候选从哪来?**  
A:每个 PENDING record 用 `MedicalRetriever.retrieve(expansion, domain_boost, source)` 检索,结果放进 `std_cache`。

**Q:mapping_states 有什么价值?**  
A:它记录每个缩写最终状态和 failure,能解释 NOT_EXPANDED / CODE_WITHHELD / ABSTAIN,是错误分析和调试的关键。

## 一句话总结

> `expand_verify_with_retry()` 是 V11 的主状态机:它先用候选召回和 coverage 为每个缩写确定 expansion,再把缩写统一成 record,通过确定性替换生成 expanded_text,对 PENDING record 检索 SNOMED/RxNorm 候选,由 verifier 选择忠实标准概念或 WITHHELD,并用标准化反思尝试救回编码。它的核心价值是把扩写、检索、编码、失败原因都收进同一条 per-abbreviation 生命周期里,让系统不只是返回结果,还能解释每个缩写为什么这么处理。
