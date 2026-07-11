# error_triage_report 改进方案

> 目标：把错误分析报告从“多口径并列拉扯”改成“成功/失败主口径 + 失败标签分析”。  
> 本文是待审核方案，不代表已经修改 `error_analysis_report.py` 或 `error_triage.py`。

## 1. 当前核心问题

现在的 `error_triage_report.md` 同时使用了多种口径：

```text
benchmark_correct / benchmark accuracy
business_success
expansion_success
standardization_success
failed_cases
expansion_failure_cases
standardization_failure_cases
record_status_summary
```

这些指标都不是错的，但它们回答的是不同问题。

问题在于：报告把它们放在同一个主叙事里反复切换，读者会产生一种感觉：

```text
这份报告一会儿说很好，一会儿说很差。
一会儿说 71/74 成功，一会儿说 59/74 成功。
一会儿说 7 个扩写失败，一会儿说 15 个标准化失败。
这些数字到底能不能相加？
```

根本原因是：

```text
当前报告没有一个统一的“总成功 / 总失败”主口径。
```

## 2. 新版报告主口径

建议正式错误分析报告采用：

```text
overall_success / overall_failure
```

作为主口径。

### 2.1 overall_success 定义

一个 case 只有同时满足下面三个条件，才算最终成功：

```text
benchmark_correct == true
expansion_success == true
standardization_success == true
```

也就是：

```text
overall_success =
benchmark_correct
AND expansion_success
AND standardization_success
```

### 2.2 overall_failure 定义

只要下面任一条件成立，就进入总失败池：

```text
benchmark_correct == false
OR expansion_success == false
OR standardization_success == false
```

也就是：

```text
overall_failure =
benchmark_mismatch
OR expansion_failure
OR standardization_failure
```

这比单独看 benchmark accuracy 或 standardization_success 更严格，也更适合项目交付报告。

原因：

```text
benchmark_correct 只看是否匹配 gold。
expansion_success 只看扩写是否完成。
standardization_success 只看最终是否 CODED。

项目评估报告应该暴露任一重要口径失败的样例。
```

## 3. 当前数据下的新口径

根据当前结果：

```text
total_cases = 74
benchmark_failed = 3
expansion_failed = 7
standardization_failed = 15
```

其中集合有重叠：

```text
benchmark_failed = {coverage_003, coverage_005, coverage_006}

standardization_failed 中包含：
coverage_003
coverage_006
```

所以：

```text
benchmark_failed ∩ standardization_failed = 2
benchmark_failed_only = 1
```

也就是：

```text
coverage_003：benchmark 错误 + 标准化失败
coverage_005：benchmark 错误，但扩写和标准化技术链路成功
coverage_006：benchmark 错误 + 标准化失败
```

因此总失败集合不是简单相加：

```text
overall_failure_cases =
benchmark_failed ∪ expansion_failed ∪ standardization_failed
```

当前可以推导为：

```text
overall_failure_count = 16
overall_success_count = 74 - 16 = 58
```

注意：

```text
benchmark_failed、expansion_failed、standardization_failed 是失败标签。
标签可以重叠，所以标签数量不能直接相加。
```

## 4. benchmark 错误算不算扩写错误或标准化错误

不一定。

### 4.1 coverage_003

```text
系统额外扩写 ABC。
ABC 标准化失败，status = WITHHELD。
```

所以它属于：

```text
benchmark_mismatch
standardization_failure
```

但它不属于：

```text
expansion_blocked
```

因为系统确实给 ABC 产出了 expansion。

### 4.2 coverage_006

```text
系统额外扩写 QRS。
QRS 标准化失败，status = WITHHELD。
```

所以它属于：

```text
benchmark_mismatch
standardization_failure
```

### 4.3 coverage_005

```text
系统扩写 LMN -> lower motor neuron。
并且成功 CODED。
```

所以从技术链路看：

```text
expansion_success = true
standardization_success = true
```

但 gold 期望：

```text
expected_mappings = []
```

所以它属于：

```text
benchmark_mismatch
```

但不属于：

```text
expansion_failure
standardization_failure
```

这就是为什么必须用“失败标签可重叠”的设计。

## 5. 指标层级建议

新版报告中，指标应该分层展示。

### 5.1 主指标

主指标只放：

```text
overall_success_count
overall_failure_count
overall_success_rate
```

例如：

```text
overall_success = 58 / 74
overall_failure = 16 / 74
```

### 5.2 失败标签统计

失败标签用于解释失败原因。

```text
benchmark_mismatch = 3
expansion_failure = 7
standardization_failure = 15
```

必须注明：

```text
这些标签可以重叠，不能直接相加。
```

### 5.3 辅助指标

辅助指标可以保留，但不要作为主成功率。

```text
benchmark_accuracy = 71 / 74
expansion_success = 67 / 74
standardization_success = 59 / 74
```

它们用于解释系统在哪一层出了问题。

### 5.4 record 级统计

record 级统计放在最后。

例如：

```text
CODED = 80
WITHHELD = 8
NOT_EXPANDED = 7
```

必须注明：

```text
这是 record 数，不是 case 数。
不能与 case 级失败数直接相加。
```

## 6. 新版报告建议结构

建议 `error_triage_report.md` 改成下面的结构。

## 1. 总体结论

先用一句话给出主口径：

```text
本轮共 74 条样例。
最终 overall_success 为 58 条，overall_failure 为 16 条。
```

再解释辅助口径：

```text
benchmark accuracy 为 71/74。
这个数字表示 gold 对齐情况，不等于端到端成功率。
```

## 2. 口径说明

用表格说明：

| 指标 | 数值 | 单位 | 是否主指标 | 含义 |
|---|---:|---|---|---|
| overall_success | 58/74 | case | 是 | gold 对齐、扩写、标准化三者都成功 |
| overall_failure | 16/74 | case | 是 | 三者任一失败 |
| benchmark_accuracy | 71/74 | case | 否 | predicted_mappings 是否匹配 gold |
| expansion_success | 67/74 | case | 否 | 扩写是否完成 |
| standardization_success | 59/74 | case | 否 | 是否最终全部 CODED |
| record_status_summary | CODED/WITHHELD/NOT_EXPANDED | record | 否 | record 状态分布 |

## 3. 总失败集合关系

这一章必须明确展示集合关系。

```text
overall_failure_cases =
benchmark_mismatch ∪ expansion_failure ∪ standardization_failure
```

当前：

```text
benchmark_mismatch = 3
expansion_failure = 7
standardization_failure = 15
overall_failure = 16
```

并说明：

```text
标签可重叠，所以 3 + 7 + 15 不能相加。
```

建议额外展示：

```text
benchmark_mismatch_only = 1
benchmark_mismatch_and_standardization_failure = 2
expansion_failure_subset_of_standardization_failure = true
```

## 4. benchmark 错误分析

单独列出 benchmark 判错的 3 条。

```text
coverage_003
coverage_005
coverage_006
```

并说明每条是否也属于技术失败：

| case | benchmark_mismatch | expansion_failure | standardization_failure | 说明 |
|---|---|---|---|---|
| coverage_003 | 是 | 否 | 是 | 多扩 ABC，且 ABC 标准化 WITHHELD |
| coverage_005 | 是 | 否 | 否 | LMN 技术链路成功，但 gold 认为不该扩写 |
| coverage_006 | 是 | 否 | 是 | 多扩 QRS，且 QRS 标准化 WITHHELD |

## 5. 扩写错误分析

这里分析：

```text
expansion_success = false
```

的样例。

建议命名为：

```text
expansion_blocked
```

而不是泛泛叫 `expansion_failure`。

原因：

```text
这些 case 的核心问题是没有得到可靠 expansion，
导致后续不可能 CODED。
```

这一章主要列出：

```text
NOT_EXPANDED
ABSTAIN
PENDING
```

相关样例。

## 6. 标准化错误分析

这里分析：

```text
standardization_success = false
```

的样例。

它可以包含扩写错误原因，因为：

```text
没有 expansion，自然无法标准化。
```

建议拆成两类：

```text
1. no_expansion_cannot_standardize
   扩写阻断导致无法 CODED。

2. expansion_exists_but_withheld
   扩写成功，但标准概念校验不通过。
```

## 7. record 级诊断

最后展示：

```text
CODED
WITHHELD
NOT_EXPANDED
```

并强调：

```text
这是 record 数，不是 case 数。
```

## 8. 后续改进建议

按失败标签给建议：

```text
benchmark_mismatch:
检查 gold 预期、低上下文目标识别、过度扩写。

expansion_blocked:
补充候选词典、增加上下文、保留安全拒绝策略。

standardization_failure:
检查标准库覆盖、检索召回、verify rubric、是否需要允许部分非疾病实体编码。
```

## 7. 建议 JSON 结构

建议 `error_analysis_report.json` 新增：

```json
{
  "overall_failure_analysis": {
    "total_cases": 74,
    "overall_success_count": 58,
    "overall_failure_count": 16,
    "overall_success_rate": 0.7838,
    "success_definition": {
      "benchmark_correct": true,
      "expansion_success": true,
      "standardization_success": true
    },
    "failure_definition": "benchmark_mismatch OR expansion_failure OR standardization_failure",
    "failure_label_summary": {
      "benchmark_mismatch": 3,
      "expansion_blocked": 7,
      "standardization_failure": 15
    },
    "failure_set_relationship": {
      "labels_are_overlapping": true,
      "labels_should_not_be_summed": true,
      "benchmark_mismatch_only_count": 1,
      "benchmark_mismatch_and_standardization_failure_count": 2,
      "expansion_blocked_is_subset_of_standardization_failure": true
    },
    "failure_cases": []
  }
}
```

每个 `failure_case` 建议包含：

```json
{
  "id": "coverage_003",
  "category": "low_context_abbreviation",
  "text": "...",
  "labels": {
    "benchmark_mismatch": true,
    "expansion_blocked": false,
    "standardization_failure": true
  },
  "failure_reasons": [
    "target_selection_error",
    "standardization_withheld"
  ],
  "mapping_states": []
}
```

## 8. 实施步骤

### Step 1：重构 error_analysis_report.py

新增：

```text
overall_failure_analysis
```

保留旧字段，但新报告优先使用新字段。

### Step 2：重构 error_triage.py

让 LLM prompt 和 markdown 模板围绕：

```text
overall_failure_analysis
```

而不是围绕三套并列口径。

### Step 3：重新生成报告

运行：

```powershell
E:\Work\B_RAG\Try\medical-nlp\.venv\Scripts\python.exe backend\evaluation\error_analysis_report.py
E:\Work\B_RAG\Try\medical-nlp\.venv\Scripts\python.exe backend\evaluation\error_triage.py
```

注意：

```text
error_triage.py 会调用 DeepSeek API。
运行前需要确认允许发送当前 error_analysis_report.json 给 DeepSeek。
```

## 9. 最终推荐

建议采用这一版。

原因：

```text
它既不会忽略 benchmark 设定的既定错误，
也不会忽略程序自身扩写不到、标准化不到的问题。
```

最终报告主线应该是：

```text
成功案例 / 失败案例
```

失败案例再打标签：

```text
benchmark_mismatch
expansion_blocked
standardization_failure
```

这样报告就不会再出现：

```text
多种统计口径在同一篇文章中反复拉扯
```

的问题。

面试时也可以这样讲：

> 我没有只看 benchmark accuracy，因为它可能掩盖技术链路失败；也没有只看标准化成功率，因为它可能掩盖 gold 对齐问题。最终我定义了一个更严格的 overall_success：只有 gold 对齐、扩写成功、标准化成功三者同时满足才算成功。失败样例再按 benchmark mismatch、扩写阻断、标准化失败打标签分析。这样能同时看到评测错误和真实系统能力边界。

