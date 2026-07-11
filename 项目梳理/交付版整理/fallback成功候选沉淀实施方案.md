# fallback 成功候选沉淀实施方案

## 1. 目标

这个功能的目标是：

```text
每轮 benchmark / 错误分析之后，
把本轮由 fallback 生成扩写、并且最终成功标准化为 CODED 的缩写结果收集出来，
形成一份“可审核的候选库扩充清单”。
```

之后人工确认没问题，再通过专门写入脚本把这些候选追加进 primary 候选库：

```text
backend/data/abbr_candidates.py
```

这样系统后续遇到同类缩写时，可以优先从 primary 候选库召回，减少 fallback LLM 自由生成的不稳定性。

## 2. 核心边界

这个机制不是：

```text
fallback 生成什么就直接相信什么
```

而是：

```text
fallback 生成候选
  -> coverage 接受扩写
  -> 标准化检索拿到标准概念
  -> verifier 判定 CODED
  -> 进入候选沉淀清单
  -> 人工审核
  -> 追加写入 primary 候选库
```

也就是说，fallback 结果必须先经过系统现有链路验证，才有资格被沉淀。

## 3. 为什么必须分两步

用户希望后续可能在前端页面中看到这些候选，再点击按钮确认写入。

所以流程必须拆成两步：

```text
第一步：提取合格候选，只展示，不修改 primary
第二步：用户确认后，再执行写入脚本，追加更新 primary
```

这样可以避免系统自动把错误候选、偶然正确候选、或者过拟合 benchmark 的候选直接写进主库。

## 4. 第一步：提取并展示候选

已新增脚本：

```text
backend/evaluation/collect_fallback_candidate_promotions.py
```

它只负责读取本轮结果，生成候选清单，不修改任何生产数据。

### 输入

优先读取：

```text
backend/evaluation/benchmark_results.json
```

需要用到的字段：

```text
results[*].mapping_states
results[*].mapping_standardizations
results[*].correct
results[*].success
results[*].category
results[*].text
```

### 筛选条件

候选必须同时满足：

```text
mapping_state.source == "fallback"
mapping_state.status == "CODED"
同一个 abbreviation + expansion 在 mapping_standardizations 中存在 chosen_concept
```

不收集：

```text
source = primary 的样本
NOT_EXPANDED
ABSTAIN
PENDING
WITHHELD
没有 chosen_concept 的样本
benchmark 明显错误且候选有争议的样本
```

### 输出

建议输出两份文件：

```text
backend/evaluation/fallback_candidate_promotions.json
backend/evaluation/fallback_candidate_promotions.md
```

JSON 给后续写入脚本或前端页面读取。

Markdown 给人直接审查。

## 5. 候选数据必须是列表形式

primary 候选库当前适合维持这种结构：

```python
ABBR_CANDIDATES = {
    "PT": [
        {"expansion": "physical therapy", "domain": "Procedure"},
        {"expansion": "prothrombin time", "domain": "Measurement"},
    ]
}
```

重点是：

```text
同一个缩写 key 下必须是 list。
新增扩写时只能 append 到 list。
不能用赋值覆盖整个 key。
```

错误写法：

```python
ABBR_CANDIDATES["PT"] = [
    {"expansion": "prothrombin time", "domain": "Measurement"}
]
```

因为这会把原来的 `physical therapy` 覆盖掉。

正确写法：

```python
ABBR_CANDIDATES.setdefault("PT", [])
ABBR_CANDIDATES["PT"].append(
    {"expansion": "prothrombin time", "domain": "Measurement"}
)
```

但是实际写入脚本还要做去重，不能重复 append 同一个 expansion。

## 6. 去重规则

候选去重 key：

```text
abbreviation.upper()
expansion.lower().strip()
```

例如：

```text
PT + Prothrombin Time
pt + prothrombin time
```

应视为同一个候选。

如果 primary 中已经存在同一个 expansion：

```text
不重复写入
只在报告里标记 already_exists = true
```

如果是同一个缩写的新 expansion：

```text
追加到该缩写的 list 中
```

## 7. 候选清单 JSON 结构

建议第一步输出这种结构：

```json
{
  "source_result_file": "backend/evaluation/benchmark_results.json",
  "selection_rule": "source=fallback AND status=CODED AND chosen_concept exists",
  "items": [
    {
      "abbreviation": "PT",
      "expansion": "prothrombin time",
      "domain": "Measurement",
      "already_exists": false,
      "support_count": 2,
      "case_ids": ["case_001", "case_017"],
      "examples": [
        {
          "id": "case_001",
          "text": "The patient had elevated PT.",
          "final_expanded_text": "The patient had elevated prothrombin time."
        }
      ],
      "chosen_concepts": [
        {
          "concept_id": "...",
          "concept_name": "...",
          "domain_id": "Measurement",
          "concept_code": "..."
        }
      ],
      "candidate_to_append": {
        "expansion": "prothrombin time",
        "domain": "Measurement"
      }
    }
  ]
}
```

这里 `items` 是列表，方便前端展示和勾选。

未来前端可以直接展示：

```text
缩写
扩写
domain
support_count
case_ids
chosen_concept
是否已存在
```

## 8. 第二步：确认后写入 primary

已新增第二个脚本：

```text
backend/evaluation/apply_fallback_candidate_promotions.py
```

它只负责把第一步确认过的候选追加进：

```text
backend/data/abbr_candidates.py
```

### 输入

```text
backend/evaluation/fallback_candidate_promotions.json
```

未来如果接前端，可以由前端传入用户勾选后的 items：

```json
{
  "approved_items": [
    {
      "abbreviation": "PT",
      "expansion": "prothrombin time",
      "domain": "Measurement"
    }
  ]
}
```

### 写入规则

写入脚本必须遵守：

```text
1. 如果 abbreviation 不存在，新建 key，value 是 list。
2. 如果 abbreviation 已存在，只 append 新 expansion。
3. 如果同 abbreviation + same expansion 已存在，跳过。
4. 不覆盖已有 list。
5. 不删除已有候选。
6. 不改变已有候选顺序，除非后续单独设计排序机制。
```

示例：

原来：

```python
"PT": [
    {"expansion": "physical therapy", "domain": "Procedure"},
]
```

写入后：

```python
"PT": [
    {"expansion": "physical therapy", "domain": "Procedure"},
    {"expansion": "prothrombin time", "domain": "Measurement"},
]
```

## 9. 为什么同一个缩写允许多个扩写

这是合理的。

医学缩写天然多义，例如：

```text
PT = physical therapy
PT = prothrombin time
PT = patient
```

primary 候选库不负责直接给最终答案。

primary 的职责是：

```text
提供候选集合
```

真正决定采用哪个扩写的是后面的 coverage：

```text
候选集合 + 原文上下文 -> 选择最合适 expansion
```

所以同一缩写下多个候选不是问题，反而是符合系统设计的。

## 10. 前端交互设想

未来可以在前端做成：

```text
错误分析 / benchmark 完成
  -> 后端生成 fallback_candidate_promotions.json
  -> 前端展示候选表格
  -> 用户勾选想加入 primary 的候选
  -> 点击“加入 primary 候选库”
  -> 调用 apply 脚本或对应 API
  -> 后端追加写入 ABBR_CANDIDATES
```

前端表格可以包含：

```text
是否勾选
abbreviation
expansion
domain
support_count
case_ids
chosen_concept
already_exists
示例原句
```

## 11. 与错误分析报告的关系

这个功能适合放在错误分析之后运行。

完整流程可以是：

```text
run_benchmark.py 或 run_benchmark_parallel.py
  -> error_analysis_report.py
  -> error_triage.py
  -> collect_fallback_candidate_promotions.py
  -> 人工审核
  -> apply_fallback_candidate_promotions.py
```

注意：

```text
error_triage.py 负责分析失败原因；
collect_fallback_candidate_promotions.py 负责收集本轮可沉淀的成功 fallback 候选。
```

它们是相邻流程，但职责不同。

## 12. 保守边界

第一版只设计为：

```text
提取
展示
人工确认
追加写入
```

第一版不做：

```text
自动无审核写入
覆盖已有候选
删除已有候选
根据一次成功调整优先级
把 fallback 结果变成唯一答案
```

这样既能让系统随着使用逐步增强，又不会因为一次 benchmark 结果把主候选库污染。

## 13. 面试说法

可以这样讲：

> 我设计了一个 fallback 成功候选沉淀机制。fallback 生成的扩写不会直接进入主词典，只有当它通过 coverage、标准化检索和 verifier 校验，最终状态为 CODED 时，才会进入候选提升清单。这个清单先展示给用户审核，确认后再以 append 的方式追加到 primary 候选库的 list 中，不覆盖同一缩写下已有扩写。这样系统会逐步减少对 LLM 自由生成的依赖，同时保留上下文消歧能力。
