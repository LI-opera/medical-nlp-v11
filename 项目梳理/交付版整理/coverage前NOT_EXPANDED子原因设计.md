# coverage 前 NOT_EXPANDED 子原因设计

> 目标：只解决一个问题：当 record 是 `NOT_EXPANDED / NO_CANDIDATES` 时，报告要说清楚“为什么没有候选”，尤其要说明 fallback 到底有没有起作用。

## 1. 先把问题收窄

当前链路是：

```text
token gate
  -> primary candidate retriever
  -> fallback candidate retriever
  -> coverage evaluator
```

`coverage 前 NOT_EXPANDED` 指的是：

```text
候选召回阶段就没有得到候选。
因此没有候选可以送进 coverage evaluator。
```

这类失败现在统一表现为：

```json
{
  "status": "NOT_EXPANDED",
  "failure": {
    "type": "NO_CANDIDATES",
    "stage": "candidate_retrieval"
  }
}
```

问题是：

```text
NO_CANDIDATES 只说明最终没有候选。
但它没说明：
1. primary 是否查过？
2. fallback 是否调用过？
3. fallback 是正常返回空，还是 fallback 本身失败？
```

所以这次设计只补这层解释。

不做大而全的错误 taxonomy。

## 2. 最终只保留两个 subtype

coverage 前的 `NO_CANDIDATES` 只分两类：

```text
FALLBACK_RETURNED_EMPTY
FALLBACK_FAILED
```

### 2.1 FALLBACK_RETURNED_EMPTY

含义：

```text
primary 没有候选；
fallback 已调用；
fallback 正常返回；
但 fallback 返回 candidates = []。
```

这类是业务上的“安全失败”：

```text
系统没有找到任何可信扩写证据，
所以保守地不扩写。
```

典型例子：

```text
Patient has XYZ.
Patient reports QQQ.
The patient has MNO.
```

它回答的是：

```text
不是没走 fallback。
fallback 走了。
但 fallback 也没有给出候选。
```

注意：

```text
fallback 为什么返回空，不再继续拆成标签。
```

例如：

```text
low context
not recognized
unsupported
rare
not plausible
```

这些都不做 subtype。

它们只保存在：

```text
fallback_reason
```

报告直接引用 fallback 的原始解释即可。

### 2.2 FALLBACK_FAILED

含义：

```text
primary 没有候选；
fallback 本应兜底；
但 fallback 调用、返回或解析过程失败；
系统没有得到可用候选。
```

这类是工程链路失败，不是医学语义失败。

可能情况包括：

```text
DeepSeek API 报错
请求超时
环境变量缺失
fallback 返回非法 JSON
fallback 返回结构不符合预期
```

这些细节不再拆成多个 subtype。

统一放进 evidence：

```text
fallback_error_kind
fallback_raw_output
fallback_error
```

例如：

```json
{
  "subtype": "FALLBACK_FAILED",
  "evidence": {
    "fallback_error_kind": "invalid_json",
    "fallback_raw_output": "...",
    "fallback_error": null
  }
}
```

或：

```json
{
  "subtype": "FALLBACK_FAILED",
  "evidence": {
    "fallback_error_kind": "exception",
    "fallback_raw_output": null,
    "fallback_error": "DeepSeek API timeout"
  }
}
```

## 3. 不再设计这些标签

以下内容不作为 subtype：

```text
LOW_CONTEXT
NOT_RECOGNIZED_MEDICAL_ABBR
UNSUPPORTED_OR_RARE
FORMAT_ERROR
RUNTIME_ERROR
UNKNOWN
TOKEN_GATE_REJECTED
PRIMARY_EMPTY_FALLBACK_DISABLED
NO_PRIMARY_NO_FALLBACK_CANDIDATES
FALLBACK_EMPTY_LOW_CONTEXT
```

删除原因：

```text
1. LOW_CONTEXT / NOT_RECOGNIZED / UNSUPPORTED_OR_RARE
   都只是 fallback 返回空的解释，不需要变成分类标签。

2. FORMAT_ERROR / RUNTIME_ERROR
   都只是 fallback 失败的细节，不需要变成分类标签。

3. UNKNOWN
   太空，没必要作为正式标签。

4. TOKEN_GATE_REJECTED
   会污染报告，因为一句话里大量普通单词都会被 gate 拒绝。

5. PRIMARY_EMPTY_FALLBACK_DISABLED
   当前系统没有 fallback 关闭开关，暂时没有真实场景。

6. NO_PRIMARY_NO_FALLBACK_CANDIDATES / FALLBACK_EMPTY_LOW_CONTEXT
   和 FALLBACK_RETURNED_EMPTY 重叠，统一合并。
```

一句话原则：

```text
subtype 只回答“fallback 最终是空返回，还是 fallback 自己失败了”。
fallback 为什么空返回，直接看 fallback_reason。
```

## 4. 推荐 failure 结构

### 4.1 fallback 正常返回空

```json
{
  "type": "NO_CANDIDATES",
  "subtype": "FALLBACK_RETURNED_EMPTY",
  "stage": "candidate_retrieval",
  "reason": "No expansion candidates were returned by primary or fallback retriever.",
  "suggestion": "Need more clinical context or abbreviation dictionary/source update.",
  "evidence": {
    "primary_called": true,
    "primary_candidate_count": 0,
    "fallback_called": true,
    "fallback_candidate_count": 0,
    "fallback_reason": "The abbreviation is not recognized or plausible in the given context.",
    "fallback_error_kind": null,
    "fallback_raw_output": null,
    "fallback_error": null,
    "candidate_count": 0,
    "candidates_seen": []
  }
}
```

### 4.2 fallback 失败

```json
{
  "type": "NO_CANDIDATES",
  "subtype": "FALLBACK_FAILED",
  "stage": "candidate_retrieval",
  "reason": "Fallback retriever failed before returning usable candidates.",
  "suggestion": "Check fallback API, JSON format, or runtime configuration.",
  "evidence": {
    "primary_called": true,
    "primary_candidate_count": 0,
    "fallback_called": true,
    "fallback_candidate_count": 0,
    "fallback_reason": "Fallback retriever did not return valid JSON.",
    "fallback_error_kind": "invalid_json",
    "fallback_raw_output": "...",
    "fallback_error": null,
    "candidate_count": 0,
    "candidates_seen": []
  }
}
```

## 5. 与 coverage 阶段失败的关系

完整 `NOT_EXPANDED` 关系变成：

```text
NOT_EXPANDED
  |
  |-- candidate_retrieval
  |     |-- NO_CANDIDATES
  |           |-- FALLBACK_RETURNED_EMPTY
  |           |-- FALLBACK_FAILED
  |
  |-- candidate_coverage
        |-- CANDIDATES_REJECTED_BY_COVERAGE
        |-- AMBIGUOUS_LOW_CONTEXT
```

这样就足够了。

不要再继续扩展更多标签。

## 6. 代码改动点

### 6.1 `abbr_candidate_fallback_retriever.py`

目标：

```text
确保 fallback 结果总是结构化返回。
```

正常返回空：

```json
{
  "abbreviation": "XYZ",
  "candidates": [],
  "reason": "The abbreviation is not recognized or plausible in the given context."
}
```

非法 JSON：

```json
{
  "abbreviation": "XYZ",
  "candidates": [],
  "reason": "Fallback retriever did not return valid JSON.",
  "raw_output": "..."
}
```

调用异常：

```json
{
  "abbreviation": "XYZ",
  "candidates": [],
  "reason": "Fallback retriever raised an exception.",
  "error": "..."
}
```

### 6.2 `abbr_service.py`

在 `_get_abbreviation_candidates()` 中记录：

```text
primary_candidate_count
fallback_called
fallback_candidate_count
fallback_reason
fallback_error_kind
fallback_raw_output
fallback_error
```

然后在 `_build_not_expanded_failure()` 中生成：

```text
failure.subtype
```

建议判断规则：

```text
如果 fallback_error 或 raw_output 存在：
  subtype = FALLBACK_FAILED

否则如果 fallback_called = true 且 fallback_candidate_count = 0：
  subtype = FALLBACK_RETURNED_EMPTY
```

### 6.3 `error_analysis_report.py`

新增统计：

```text
not_expanded_failure_subtype_summary
```

示例：

```json
{
  "not_expanded_failure_subtype_summary": {
    "FALLBACK_RETURNED_EMPTY": 7,
    "FALLBACK_FAILED": 1
  }
}
```

### 6.4 `error_triage.py`

payload 和 markdown 原始证据区展示：

```text
failure_subtype
fallback_called
fallback_candidate_count
fallback_reason
fallback_error_kind
fallback_raw_output
fallback_error
```

LLM prompt 要求：

```text
解释扩写失败时，不能只说 NOT_EXPANDED。
必须说明：
1. failure.type
2. failure.subtype
3. fallback 是否调用
4. fallback 是正常返回空，还是 fallback 本身失败
5. fallback_reason 或 fallback_error
```

## 7. 报告目标写法

### 7.1 FALLBACK_RETURNED_EMPTY

```text
XYZ 通过 token gate 后进入候选召回。
primary 缩写词典没有候选。
fallback 已调用，但正常返回 candidates = []。
因此本例属于 NO_CANDIDATES / FALLBACK_RETURNED_EMPTY。
这说明系统没有找到可信扩写证据，所以保守 NOT_EXPANDED。
fallback reason: The abbreviation is not recognized or plausible in the given context.
```

### 7.2 FALLBACK_FAILED

```text
ABC 通过 token gate 后进入候选召回。
primary 缩写词典没有候选。
fallback 本应兜底，但 fallback 返回非法 JSON，系统无法解析候选。
因此本例属于 NO_CANDIDATES / FALLBACK_FAILED。
这不是医学语义问题，而是 fallback 工程链路失败。
```

## 8. 验收标准

修改完成后至少满足：

```text
1. coverage_001 / coverage_002 / coverage_004 不再只显示 NO_CANDIDATES。
2. 每个 NO_CANDIDATES 都有 subtype。
3. subtype 只允许 FALLBACK_RETURNED_EMPTY 或 FALLBACK_FAILED。
4. 报告中能看到 fallback_called。
5. 报告中能看到 fallback_candidate_count。
6. 报告中能看到 fallback_reason。
7. 如果 fallback 失败，报告中能看到 fallback_error_kind。
8. error_analysis_report.json 有 not_expanded_failure_subtype_summary。
9. benchmark 原有 correct / accuracy 不应因为只加诊断字段而改变。
```

建议验证命令：

```powershell
.\.venv\Scripts\python.exe -m py_compile .\backend\services\abbr_service.py .\backend\services\abbr_candidate_fallback_retriever.py .\backend\evaluation\error_analysis_report.py .\backend\evaluation\error_triage.py
.\.venv\Scripts\python.exe .\backend\evaluation\run_benchmark.py
.\.venv\Scripts\python.exe .\backend\evaluation\error_analysis_report.py
```

如果要生成最终 LLM 人话报告，需要用户明确同意后运行：

```powershell
.\.venv\Scripts\python.exe .\backend\evaluation\error_triage.py
```

因为它会调用 DeepSeek API，并发送当前错误样例。

## 9. 推荐实施顺序

```text
第一步：
改 fallback retriever，让 JSON 解析失败和调用异常都结构化返回。

第二步：
改 abbr_service，让 fallback 诊断信息进入 failure.evidence，并生成 subtype。

第三步：
改 error_analysis_report.py，增加 subtype 汇总。

第四步：
改 error_triage.py，让报告引用 subtype 和 fallback 证据。

第五步：
跑 benchmark，确认准确率不变，再更新 error_analysis_report.json。
```

暂时不要改 fallback prompt，也不要扩大 fallback 召回。

原因：

```text
当前问题是“失败解释不清楚”，不是“fallback 必须给更多答案”。
先把失败证据记录完整，再决定是否调整召回策略。
```

