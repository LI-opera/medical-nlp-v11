# 09_API 最终返回：为什么 mappings 和 standardized_entities 不是一回事

> 这一章接着 08 讲：
> 核心链路已经处理完了，现在要看用户最终拿到什么，以及哪些内部字段用于调试和评估。

---

## 先说结论

`/expand/simple` 最终返回四个字段：

```json
{
  "success": true,
  "expanded_text": "...",
  "mappings": [],
  "standardized_entities": []
}
```

这四个字段不是一个意思。

| 字段 | 回答的问题 |
|---|---|
| `success` | 缩写扩写流程是否完成 |
| `expanded_text` | 最终扩写后的文本 |
| `mappings` | 哪些缩写被扩成了什么 |
| `standardized_entities` | 哪些扩写被成功绑定到标准概念 |

最容易混的是：

```text
mappings ≠ standardized_entities
```

一句话记：

```text
mappings 表示扩写成功。
standardized_entities 表示标准编码成功。
```

所以：

```text
WITHHELD 可能有 mapping，但没有 standardized_entity。
```

---

## 1. API 入口只返回简化版

入口：

```text
backend/api/main.py
POST /expand/simple
```

响应模型：

```python
class SimpleExpandResponse(BaseModel):
    success: bool
    expanded_text: str
    mappings: list[dict]
    standardized_entities: list[dict] = []
```

也就是说，对外接口只暴露：

```text
success
expanded_text
mappings
standardized_entities
```

不会把所有内部细节都返回给普通用户。

内部完整结果在：

```python
result = abbr_service.expand_verify_with_retry(...)
final_result = result.get("final_result", {}) or {}
```

`/expand/simple` 会从 `final_result` 里挑一部分返回。

面试说法：

> API 层返回的是简化结果，主要给调用方看扩写文本、扩写映射和成功标准化的实体。更详细的 attempts、mapping_states、coverage、std_cache 留在内部结果里，用于调试和评估。

---

## 2. expanded_text 从哪里来

API 返回：

```python
"expanded_text": final_result.get(
    "expanded_text",
    request.text
)
```

`final_result["expanded_text"]` 来自主状态机最终重建：

```python
current_expanded_text = self._build_expanded_text_deterministic(
    text,
    _visible(records)
)
```

所以：

```text
expanded_text = 原始文本 + 当前可见 records 的确定性替换结果
```

它不是 LLM 直接写出来的。

例如：

```text
The patient took ASA for CP and denies SOB.
```

可能返回：

```text
The patient took aspirin for chest pain and denies shortness of breath.
```

---

## 3. mappings 是什么

主状态机里先算：

```python
resolved = [
    r for r in records
    if r["status"] in ("CODED", "WITHHELD")
]
```

然后：

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

所以 `mappings` 的含义是：

```text
这些缩写已经有可接受的 expansion。
```

它不保证：

```text
每个 expansion 都有标准概念 code。
```

例如：

```json
[
  {
    "abbreviation": "CP",
    "expansion": "chest pain",
    "label": null,
    "source": "primary"
  },
  {
    "abbreviation": "SOB",
    "expansion": "shortness of breath",
    "label": null,
    "source": "primary"
  }
]
```

这只说明：

```text
CP 和 SOB 被扩写了。
```

不说明：

```text
CP 和 SOB 都成功编码了。
```

面试说法：

> `mappings` 是 abbreviation 到 expansion 的结果，表示扩写层成功。它不等价于标准化成功，因为 `WITHHELD` 的扩写也会进入 mappings。

---

## 4. standardized_entities 是什么

API 层会遍历：

```python
for ms in final_result.get("mapping_standardizations", []):
    top = ms.get("chosen_concept")
    if not top:
        continue
```

只有存在 `chosen_concept` 的 mapping，才会进入：

```python
standardized_entities.append({
    "abbreviation": ms.get("abbreviation"),
    "expansion": ms.get("expansion"),
    "concept_id": top.get("concept_id"),
    "concept_name": top.get("concept_name"),
    "concept_code": top.get("concept_code"),
    "domain_id": top.get("domain_id"),
    "score": top.get("score"),
})
```

所以 `standardized_entities` 的含义是：

```text
成功绑定标准概念的扩写实体。
```

它要求：

```text
chosen_concept != None
```

也就是 record 至少要有：

```text
std_concept
```

通常对应：

```text
status = CODED
```

示意：

```json
[
  {
    "abbreviation": "CP",
    "expansion": "chest pain",
    "concept_id": "...",
    "concept_name": "Chest pain",
    "concept_code": "...",
    "domain_id": "Condition",
    "score": 0.86
  }
]
```

面试说法：

> `standardized_entities` 只输出 verifier 选择了忠实 `chosen_concept` 的结果。也就是说，它代表编码成功，而不是单纯扩写成功。

---

## 5. WITHHELD 为什么有 mapping 但没有 standardized_entity

这是这一章最关键的点。

假设：

```json
{
  "abbreviation": "SOB",
  "expansion": "shortness of breath",
  "status": "WITHHELD",
  "std_concept": null
}
```

它会进入 `mappings`，因为：

```python
r["status"] in ("CODED", "WITHHELD")
```

但不会进入 `standardized_entities`，因为：

```python
top = ms.get("chosen_concept")
if not top:
    continue
```

也就是说：

```text
SOB 可以被扩写成 shortness of breath。
但因为没有忠实标准概念，所以不输出 concept_id/concept_code。
```

这不是矛盾。

这是项目有意把两层拆开：

| 层级 | 字段 | 成功条件 |
|---|---|---|
| 扩写层 | `mappings` | 有可信 expansion |
| 标准化层 | `standardized_entities` | 有 chosen_concept |

---

## 6. NOT_EXPANDED 为什么两边都没有

如果 record 是：

```json
{
  "abbreviation": "XYZ",
  "expansion": null,
  "status": "NOT_EXPANDED",
  "failure": {
    "type": "ABBR_NOT_EXPANDED"
  }
}
```

它不会进入 `mappings`，因为：

```text
resolved 只收 CODED / WITHHELD。
```

它也不会进入 `standardized_entities`，因为：

```text
没有 expansion，更没有 chosen_concept。
```

最终外部用户可能只看到：

```json
{
  "success": false,
  "expanded_text": "The patient has XYZ.",
  "mappings": [],
  "standardized_entities": []
}
```

内部 `mapping_states` 才能解释为什么：

```text
XYZ coverage 不足，没有扩写。
```

---

## 7. success 到底是什么意思

主状态机里：

```python
success = len(_expanded(records)) > 0 and all(
    r["status"] in ("CODED", "WITHHELD")
    for r in _expanded(records)
)
```

拆开看：

### 条件 1：至少有一个 expansion

```python
len(_expanded(records)) > 0
```

如果没有任何缩写被扩写：

```text
success = False
```

### 条件 2：所有已扩写 record 都落到 CODED 或 WITHHELD

```python
r["status"] in ("CODED", "WITHHELD")
```

这表示：

```text
扩写流程已经处理完。
```

注意：

```text
WITHHELD 也算 success 条件里的完成状态。
```

所以当前 `success` 不是：

```text
所有实体都标准编码成功。
```

更准确是：

```text
至少有扩写，并且所有扩写都完成了编码决策。
```

面试说法：

> 当前 `success` 更偏 expansion pipeline success，而不是 full coding success。是否编码成功要看 `standardized_entities` 或内部 `mapping_states` 的 CODED/WITHHELD。

---

## 8. final_result 里还有哪些内部字段

主状态机最终返回：

```python
return {
    "original_text": text,
    "final_expanded_text": current_expanded_text,
    "success": success,
    "attempts": attempts,
    "final_result": final_result,
}
```

其中 `final_result` 包括：

```python
{
    "attempt": len(attempts),
    "expanded_text": current_expanded_text,
    "abbreviation_candidates": current_abbreviation_candidates,
    "mappings": final_mappings,
    "standardization": standardization_result,
    "mapping_standardizations": [...],
    "verification": ...,
    "mapping_support_results": mapping_support_results,
    "mapping_states": [...]
}
```

这些内部字段的用途：

| 字段 | 用途 |
|---|---|
| `abbreviation_candidates` | 看候选召回和 coverage 情况 |
| `mapping_standardizations` | 看每个 expansion 的 std_cache 和 chosen_concept |
| `verification` | 看 verifier 的判断结果 |
| `mapping_states` | 看每个缩写最终状态和失败原因 |
| `attempts` | 看每轮处理过程 |
| `mapping_support_results` | V10 历史兼容字段，当前为空 |

---

## 9. mapping_standardizations 是什么

它来自：

```python
"mapping_standardizations": [
    {
        "abbreviation": r["abbreviation"],
        "expansion": r["expansion"],
        "candidates": r["std_cache"],
        "chosen_concept": r["std_concept"]
    }
    for r in resolved
]
```

它回答的是：

```text
每个扩写查到了哪些标准概念候选？
最后选中了哪个？
```

示意：

```json
[
  {
    "abbreviation": "CP",
    "expansion": "chest pain",
    "candidates": [
      {"concept_name": "Chest pain"},
      {"concept_name": "Chest pain rating"}
    ],
    "chosen_concept": {
      "concept_name": "Chest pain"
    }
  },
  {
    "abbreviation": "SOB",
    "expansion": "shortness of breath",
    "candidates": [
      {"concept_name": "Respiratory assessment"}
    ],
    "chosen_concept": null
  }
]
```

API 层的 `standardized_entities` 就是从这里抽取：

```text
chosen_concept 非空的项。
```

---

## 10. mapping_states 是什么

它来自：

```python
"mapping_states": [
    {
        "abbreviation": r["abbreviation"],
        "expansion": r["expansion"],
        "status": r["status"],
        "failure": r["failure"]
    }
    for r in records
]
```

它回答的是：

```text
每个缩写最终处于什么状态，失败原因是什么？
```

示意：

```json
[
  {
    "abbreviation": "ASA",
    "expansion": "aspirin",
    "status": "CODED",
    "failure": null
  },
  {
    "abbreviation": "SOB",
    "expansion": "shortness of breath",
    "status": "WITHHELD",
    "failure": {
      "type": "CODE_WITHHELD",
      "stage": "standardization"
    }
  },
  {
    "abbreviation": "XYZ",
    "expansion": null,
    "status": "NOT_EXPANDED",
    "failure": {
      "type": "ABBR_NOT_EXPANDED",
      "stage": "coverage"
    }
  }
]
```

这个字段普通 API 不返回，但评估系统会用它。

---

## 11. benchmark 怎么用这些字段

`backend/evaluation/run_benchmark.py` 会取：

```python
final_result = result.get("final_result", {})
predicted_mappings = final_result.get("mappings", [])
final_expanded_text = final_result.get("expanded_text", "")
```

然后比较：

```text
expected_mappings vs predicted_mappings
expected_text_contains vs final_expanded_text
```

另外它还会把 `mapping_states` 交给 error collector：

```python
collect_unresolved(
    text=case["text"],
    records=final_result.get("mapping_states", []),
    source="benchmark:main",
    gold_abbrs=gold_abbrs,
)
```

所以：

```text
mappings 用来评估扩写是否对。
mapping_states 用来解释失败原因。
```

面试说法：

> Benchmark 主要比较 predicted_mappings 和 expected_mappings，同时用 final_expanded_text 做文本包含检查。mapping_states 则进入 error collector，用于分析失败发生在 coverage 还是 standardization。

---

## 12. 用 ASA、CP、SOB 看最终返回

输入：

```text
The patient took ASA for CP and denies SOB.
```

假设最终状态：

```json
[
  {
    "abbreviation": "ASA",
    "expansion": "aspirin",
    "status": "CODED",
    "std_concept": {"concept_name": "aspirin"}
  },
  {
    "abbreviation": "CP",
    "expansion": "chest pain",
    "status": "CODED",
    "std_concept": {"concept_name": "Chest pain"}
  },
  {
    "abbreviation": "SOB",
    "expansion": "shortness of breath",
    "status": "WITHHELD",
    "std_concept": null
  }
]
```

外部 `/expand/simple` 可能返回：

```json
{
  "success": true,
  "expanded_text": "The patient took aspirin for chest pain and denies shortness of breath.",
  "mappings": [
    {
      "abbreviation": "ASA",
      "expansion": "aspirin",
      "label": null,
      "source": "primary"
    },
    {
      "abbreviation": "CP",
      "expansion": "chest pain",
      "label": null,
      "source": "primary"
    },
    {
      "abbreviation": "SOB",
      "expansion": "shortness of breath",
      "label": null,
      "source": "primary"
    }
  ],
  "standardized_entities": [
    {
      "abbreviation": "ASA",
      "expansion": "aspirin",
      "concept_id": "...",
      "concept_name": "aspirin",
      "concept_code": "...",
      "domain_id": "Drug",
      "score": 0.91
    },
    {
      "abbreviation": "CP",
      "expansion": "chest pain",
      "concept_id": "...",
      "concept_name": "Chest pain",
      "concept_code": "...",
      "domain_id": "Condition",
      "score": 0.86
    }
  ]
}
```

注意：

```text
SOB 在 mappings 里。
SOB 不在 standardized_entities 里。
```

因为它是：

```text
WITHHELD
```

这是合理的。

---

## 13. 为什么 simple 接口不直接返回 mapping_states

当前 `/expand/simple` 是简化接口。

它主要面向：

```text
我要看扩写文本和成功标准化实体。
```

所以没有返回：

- `mapping_states`
- `coverage`
- `std_cache`
- `verification`
- `attempts`

好处：

```text
响应更短，更适合普通调用。
```

代价：

```text
调用方看不到某个缩写为什么 WITHHELD 或 NOT_EXPANDED。
```

这也是后续可改进点：

```text
可以增加 debug=true 参数或另开 /expand/debug 接口。
```

面试说法：

> 当前 simple 接口隐藏了内部状态，适合普通调用。如果要做可解释产品，可以增加 debug 模式，把 mapping_states 和 failure reason 返回给前端。

---

## 14. 当前返回结构的真实边界

### 1. `success` 容易被误解

当前 `success=true` 不代表：

```text
所有缩写都有标准 code。
```

它代表：

```text
至少有扩写，且扩写都处理到 CODED/WITHHELD。
```

如果做正式产品，建议拆成：

```text
expansion_success
coding_success
partial_success
```

### 2. `standardized_entities` 不显示 WITHHELD 原因

WITHHELD 的原因在内部：

```text
mapping_states.failure
```

simple 接口目前不返回。

### 3. `mapping_support_results` 是历史兼容字段

`final_result` 里还有：

```python
mapping_support_results = []
```

这是 V10 实验遗留兼容字段，当前主链路不靠它。

GitHub 清理时可以考虑：

```text
保留但标 legacy
或删除并更新响应/文档
```

---

## 15. 这章和前后章节怎么连起来

前面 02-08 已经讲完主链路：

```text
候选召回
  → coverage
  → records
  → 确定性替换
  → 多源检索
  → verifier
  → 反思重检索
```

本章 09 讲：

```text
records 最终怎么变成 API response
```

下一章应该讲：

```text
benchmark 和 error analysis 如何用这些结果判断项目好坏
```

因为找工作时你不仅要讲系统怎么跑，还要讲：

```text
我怎么知道它有没有变好？
错了怎么定位？
```

---

## 16. 面试怎么讲这章

30 秒版本：

> API 返回里我把扩写结果和标准化结果分开了。`mappings` 表示 abbreviation 到 expansion 的扩写结果，`standardized_entities` 只包含 verifier 成功选择了 `chosen_concept` 的标准编码结果。所以 `WITHHELD` 的缩写可能出现在 `mappings` 里，但不会出现在 `standardized_entities` 里。这样可以保留可信扩写，同时避免乱给标准 code。

2 分钟版本：

> `/expand/simple` 是一个简化接口，只返回 `success`、`expanded_text`、`mappings` 和 `standardized_entities`。其中 `expanded_text` 是根据最终 records 确定性替换出来的文本；`mappings` 是扩写层结果，表示哪些缩写被扩成了什么；`standardized_entities` 是标准化层结果，只输出有 `chosen_concept` 的实体。
>
> 这两个列表故意不等价。比如某个缩写 coverage 认为可以扩写，但 verifier 没有找到忠实标准概念，它会变成 `WITHHELD`。这种情况下它仍然会出现在 `mappings`，因为扩写是可信的；但不会出现在 `standardized_entities`，因为没有可靠 code。这体现了扩写和编码解耦。
>
> 内部 `final_result` 还保留了更多字段，比如 `mapping_standardizations`、`verification`、`mapping_states` 和 `attempts`。其中 `mapping_states` 会进入 benchmark 和 error collector，用来分析失败是发生在 coverage 阶段还是 standardization 阶段。当前 `success` 更接近 expansion pipeline 是否完成，不等于所有实体都编码成功，这是后续可以进一步拆字段优化的地方。

---

## 17. 你要记住的 8 句话

1. `expanded_text` 是最终可见 records 渲染出来的。
2. `mappings` 表示扩写成功。
3. `standardized_entities` 表示标准编码成功。
4. `WITHHELD` 可以有 mapping，但没有 standardized_entity。
5. `NOT_EXPANDED` 两边都没有。
6. `success` 当前不是 full coding success。
7. `mapping_states` 用来解释每个缩写的最终状态和失败原因。
8. simple API 隐藏了调试字段，后续可加 debug 模式。

---

## 18. 下一章建议

下一章建议写：

```text
10_Benchmark与ErrorAnalysis_系统怎么知道自己错在哪.md
```

这会把：

```text
run_benchmark.py
error_collector.py
analyze_errors.py
error_triage.py
```

串起来，解释这个项目不是只靠感觉调 prompt，而是有评估和错误归因闭环。

