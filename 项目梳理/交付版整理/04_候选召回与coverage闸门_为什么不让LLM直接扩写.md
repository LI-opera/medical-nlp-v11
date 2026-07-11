# 04_候选召回与 coverage 闸门：为什么不让 LLM 直接扩写

> 这一章回答一个最重要的问题：
> `record.expansion` 到底是怎么来的？

---

## 先说结论

V11 不让 LLM 直接把整句改写成扩写后的句子。

它采用的是四步：

```text
先判断 token 值不值得处理
  ↓
从主候选词典召回可能扩写
  ↓
主候选没有时，才让 LLM fallback 生成候选
  ↓
coverage evaluator 判断候选是否足够支持当前上下文
  ↓
只有通过闸门的 best_expansion 才写进 record.expansion
```

也就是说：

```text
LLM 不是直接改原文的人。
LLM 只是候选生成器或候选裁判。
真正替换原文的是后面的确定性替换函数。
```

这就是这章的核心。

---

## 1. 为什么不能让 LLM 直接扩写整句

假设输入：

```text
The patient took ASA for CP and denies SOB.
```

如果直接把整句丢给 LLM：

```text
请把所有医学缩写扩写出来。
```

它可能会返回：

```text
The patient took aspirin for chest pain and denies shortness of breath.
```

看起来很好。

但问题是，你很难控制它有没有同时做了这些事：

- 改写了非缩写部分。
- 把不确定缩写强行扩写。
- 根据常识补充了原文没有的信息。
- 把某个缩写扩成了罕见或错误含义。
- 输出格式不稳定，后面不好评估。

医疗场景里最怕的是：

```text
看起来通顺，但临床含义被悄悄改了。
```

所以 V11 的原则是：

```text
LLM 可以帮忙判断，但不要让它直接拿笔改原文。
```

面试说法：

> 我没有让 LLM 直接重写整句，而是把扩写问题拆成候选召回和候选选择。LLM 的作用被限制在生成候选、判断候选覆盖度、校验标准概念这些受控节点，最终文本替换是确定性完成的。

---

## 2. 第一道门：token gate

位置：

```text
backend/services/abbr_service.py
_should_consider_abbreviation()
```

这一步先决定：

```text
一个 token 值不值得进入缩写处理流程？
```

比如：

```text
The patient took ASA for CP and denies SOB.
```

拆词后大概是：

```text
The / patient / took / ASA / for / CP / and / denies / SOB
```

gate 规则简化理解：

| 规则 | 结果 |
|---|---|
| 空 token | 跳过 |
| 不是纯字母 | 跳过 |
| 已知缩写 | 放行 |
| 未知且长度小于 2 | 跳过 |
| 未知但原文全大写且长度不超过 8 | 放行，允许 fallback |
| 其他 | 跳过 |

所以样例里：

| token | 是否进入候选召回 | 原因 |
|---|---|---|
| `The` | 否 | 不是已知缩写，也不是全大写 |
| `patient` | 否 | 普通小写词 |
| `took` | 否 | 普通小写词 |
| `ASA` | 是 | 全大写，候选库中有 |
| `for` | 否 | 普通小写词 |
| `CP` | 是 | 全大写，候选库中有 |
| `denies` | 否 | 普通小写词 |
| `SOB` | 是 | 全大写，候选库中有 |

这一步的价值：

```text
先把普通词挡掉，不要让后面的 LLM 和候选召回处理所有 token。
```

面试说法：

> 我先用一个轻量 token gate 降低噪音。已知缩写直接进入候选召回；未知缩写只有在原文全大写、长度合理时才允许进入 fallback，避免普通英文词触发 LLM 过度解释。

---

## 3. 第二道门：主候选词典 primary candidates

位置：

```text
backend/data/abbr_candidates.py
backend/services/abbr_candidate_retriever.py
```

主候选词典长这样：

```python
ABBR_CANDIDATES = {
    "SOB": [
        {"expansion": "shortness of breath", "domain": "Condition"},
    ],
    "CP": [
        {"expansion": "chest pain", "domain": "Condition"},
        {"expansion": "cerebral palsy", "domain": "Condition"},
        {"expansion": "chronic pancreatitis", "domain": "Condition"},
    ],
    "ASA": [
        {"expansion": "aspirin", "domain": "Drug"},
    ],
}
```

`ABBRCandidateRetriever.retrieve()` 做的事很简单：

```python
abbr = abbreviation.upper().strip()
candidates = ABBR_CANDIDATES.get(abbr, [])
return [
    {
        "abbreviation": abbr,
        "expansion": c["expansion"],
        "domain": c.get("domain")
    }
    for c in candidates
]
```

也就是说：

```text
输入 CP
  ↓
查 ABBR_CANDIDATES["CP"]
  ↓
返回 chest pain / cerebral palsy / chronic pancreatitis
```

为什么要先用候选词典？

因为它把问题从：

```text
请自由猜 CP 是什么
```

变成：

```text
请在这些候选里判断哪个更符合当前上下文
```

这会显著降低幻觉空间。

面试说法：

> 主候选词典相当于一个受控候选空间。它不要求一次性覆盖所有医学缩写，但能把常见缩写从开放生成问题变成候选选择问题，降低 LLM 自由发挥。

---

## 4. 第三道门：fallback 只在 primary 没结果时启动

位置：

```text
backend/services/abbr_candidate_fallback_retriever.py
```

主链路里：

```python
candidates = self.candidate_retriever.retrieve(abbr)
candidate_source = "primary"

if not candidates:
    fallback_result = self.fallback_retriever.retrieve(
        abbreviation=abbr,
        context_text=text
    )
    candidates = fallback_result.get("candidates", [])
    candidate_source = "fallback"
```

也就是说：

```text
只要 primary 有候选，就不走 fallback。
```

fallback 的 prompt 里有几个非常关键的限制：

- 只生成候选扩写。
- 不改写整句。
- 不添加诊断、治疗、症状或假设。
- 不把首字母硬凑成扩写。
- 不认识或上下文不支持时返回空候选。
- 只返回 JSON。

fallback 返回结构是：

```json
{
  "abbreviation": "XYZ",
  "candidates": [
    {
      "abbreviation": "XYZ",
      "expansion": "candidate expansion here",
      "source": "fallback_llm",
      "confidence": 0.0
    }
  ],
  "reason": "brief explanation"
}
```

注意这里：

```text
fallback 仍然不是最终答案。
```

它只是补候选。

面试说法：

> fallback 只在主候选库没有结果时启用，而且它只允许生成候选列表，不允许改写原句。这样既补了词典覆盖不足，又不会把 LLM 变成无约束的文本改写器。

---

## 5. fallback 后还要补 domain

primary 候选里通常自带：

```json
{
  "expansion": "aspirin",
  "domain": "Drug"
}
```

但 fallback 生成的候选未必有可靠 domain。

所以代码里：

```python
if candidate_source == "fallback":
    for candidate in candidates:
        _, label, _ = self.ner_service.is_medical(candidate.get("expansion"))
        candidate["domain"] = NER_LABEL_TO_DOMAIN.get(label)
```

这一步意思是：

```text
fallback 生成 expansion 后，再用 NER 判断它大概属于什么医学域。
```

NER label 会被映射到后续标准化 domain：

| NER label | domain |
|---|---|
| `MEDICATION` | `Drug` |
| `DISEASE_DISORDER` | `Condition` |
| `SIGN_SYMPTOM` | `Condition` |
| `DIAGNOSTIC_PROCEDURE` | `Procedure` |
| `LAB_VALUE` | `Measurement` |

为什么这个重要？

因为后面标准化要靠 domain 决定查哪个库：

```text
Drug → RxNorm
非 Drug → SNOMED
```

面试说法：

> fallback 候选生成后，还会用 NER 给 expansion 补 domain。这个 domain 后面会参与 SNOMED/RxNorm 路由，尤其是药品类缩写需要走 RxNorm。

---

## 6. 如果 primary 和 fallback 都没有候选

代码会直接加入一个失败结果：

```python
found.append({
    "abbreviation": abbr,
    "candidates": [],
    "filtered_candidates": [],
    "coverage": {
        "coverage_ok": False,
        "confidence": 0.0,
        "plausible_candidates": [],
        "reason": "No candidates found from primary or fallback retriever.",
        "issues": ["no_candidates"]
    },
    "candidate_source": "none",
    "best_expansion": None,
    "chosen_label": None,
    "chosen_domain": None
})
```

后面转 record 时：

```text
best_expansion = None
  ↓
status = NOT_EXPANDED
```

这说明：

```text
没有候选时，系统不会硬扩。
```

这是安全设计，不是能力不足的遮羞布。

面试说法：

> 如果 primary 和 fallback 都没有候选，我会显式记录 `no_candidates`，并让这个缩写进入 `NOT_EXPANDED`，而不是让系统猜一个答案。

---

## 7. 第四道门：coverage evaluator

位置：

```text
backend/services/abbr_candidate_coverage_evaluator.py
```

它拿到：

```python
original_text
abbreviation
candidates
```

它的任务不是最终标准化，也不是改写句子。

prompt 里明确写了：

```text
Coverage evaluation asks:
"Is there at least one reasonable candidate in this candidate set?"
It does NOT need to perform final expansion.
It should not rewrite the clinical text.
```

它返回：

```json
{
  "abbreviation": "CP",
  "coverage_ok": true,
  "confidence": 0.0,
  "plausible_candidates": [
    "chest pain"
  ],
  "best_expansion": "chest pain",
  "reason": "brief explanation",
  "issues": []
}
```

这里最重要的是三个字段：

| 字段 | 用途 |
|---|---|
| `coverage_ok` | 候选集合是否覆盖当前语境 |
| `plausible_candidates` | 哪些候选可能合理 |
| `best_expansion` | 最终写入 record.expansion 的候选 |

面试说法：

> coverage evaluator 是扩写前的安全闸门。它不负责生成新答案，只判断候选集合里是否有上下文支持的合理扩写，并从中选择一个 best expansion。

---

## 8. coverage 不允许 invent

coverage prompt 里有两条很关键：

```text
Do not invent new candidate expansions.
best_expansion must be copied verbatim from the candidate list.
```

这意味着：

```text
如果 candidates 里没有 aspirin，coverage 不能自己写 aspirin。
如果 candidates 里只有 chest pain / cerebral palsy，coverage 只能从这里选。
```

为什么要这么做？

因为系统想保证：

```text
最终 expansion 可以追溯到候选来源。
```

否则错误分析时会变成：

```text
这个 expansion 到底从哪来的？
是词典？
是 fallback？
是 coverage 自己编的？
```

V11 不允许这个混乱发生。

面试说法：

> coverage 阶段不能 invent expansion，`best_expansion` 必须逐字来自候选列表。这样每个 expansion 都能追溯到 primary 或 fallback 来源，便于错误归因。

---

## 9. filtered_candidates 是干什么的

代码里：

```python
plausible_expansions = coverage.get("plausible_candidates", [])

filtered_candidates = [
    candidate
    for candidate in candidates
    if candidate["expansion"] in plausible_expansions
]
```

这一步的意思是：

```text
把所有候选中，被 coverage 认为 plausible 的留下来。
```

例如 `CP` 原始候选：

```json
[
  {"expansion": "chest pain"},
  {"expansion": "cerebral palsy"},
  {"expansion": "chronic pancreatitis"}
]
```

coverage 判断：

```json
{
  "plausible_candidates": ["chest pain"],
  "best_expansion": "chest pain"
}
```

那么：

```json
{
  "filtered_candidates": [
    {"expansion": "chest pain"}
  ]
}
```

`filtered_candidates` 可以用于调试：

```text
coverage 到底排除了哪些候选？
哪些候选还算 plausible？
```

---

## 10. fallback 为什么更严格

代码里有一个特殊逻辑：

```python
if candidate_source == "fallback":
    conf = coverage.get("confidence") or 0.0
    if (not coverage.get("coverage_ok")) or conf < 0.8:
        best = None
```

这说明：

```text
primary 和 fallback 不是同等信任级别。
```

primary 来自人工维护候选库，更可控。

fallback 来自 LLM 生成，更容易产生：

- 罕见扩写
- 上下文过拟合
- 人工拼字母
- 医学上看似合理但实际不常用的 expansion

所以 fallback 必须满足：

```text
coverage_ok = true
confidence >= 0.8
```

否则：

```text
best = None
```

后面 record 就会：

```text
status = NOT_EXPANDED
```

面试说法：

> fallback 候选不是和词典候选同等信任的。因为 fallback 是 LLM 生成的，所以我额外加了 confidence 门槛，coverage 不通过或置信度低于 0.8 就不扩写。

---

## 11. ASA、CP、SOB 走一遍候选链路

原句：

```text
The patient took ASA for CP and denies SOB.
```

### ASA

token gate：

```text
ASA 是全大写，放行
```

primary candidates：

```json
[
  {
    "abbreviation": "ASA",
    "expansion": "aspirin",
    "domain": "Drug"
  }
]
```

coverage 示意：

```json
{
  "coverage_ok": true,
  "confidence": 0.9,
  "plausible_candidates": ["aspirin"],
  "best_expansion": "aspirin"
}
```

输出到 candidate_infos：

```json
{
  "abbreviation": "ASA",
  "candidate_source": "primary",
  "best_expansion": "aspirin",
  "chosen_domain": "Drug"
}
```

后续 record：

```json
{
  "abbreviation": "ASA",
  "expansion": "aspirin",
  "domain": "Drug",
  "status": "PENDING"
}
```

---

### CP

primary candidates：

```json
[
  {"expansion": "chest pain", "domain": "Condition"},
  {"expansion": "cerebral palsy", "domain": "Condition"},
  {"expansion": "chronic pancreatitis", "domain": "Condition"}
]
```

coverage 根据上下文选：

```json
{
  "coverage_ok": true,
  "plausible_candidates": ["chest pain"],
  "best_expansion": "chest pain"
}
```

后续 record：

```json
{
  "abbreviation": "CP",
  "expansion": "chest pain",
  "domain": "Condition",
  "status": "PENDING"
}
```

这里你要看懂：

```text
CP 不是因为词典第一项是 chest pain 就直接选它。
它是候选召回后，经 coverage 结合上下文选出来的。
```

---

### SOB

primary candidates：

```json
[
  {
    "expansion": "shortness of breath",
    "domain": "Condition"
  }
]
```

coverage：

```json
{
  "coverage_ok": true,
  "plausible_candidates": ["shortness of breath"],
  "best_expansion": "shortness of breath"
}
```

后续 record：

```json
{
  "abbreviation": "SOB",
  "expansion": "shortness of breath",
  "domain": "Condition",
  "status": "PENDING"
}
```

---

## 12. 一个失败例子：未知缩写 XYZ

输入：

```text
Patient has XYZ.
```

token gate：

```text
XYZ 全大写，长度合理 → 允许进入 fallback
```

primary：

```text
ABBR_CANDIDATES 里没有 XYZ
```

fallback 可能返回：

```json
{
  "candidates": []
}
```

系统写入：

```json
{
  "abbreviation": "XYZ",
  "candidates": [],
  "coverage": {
    "coverage_ok": false,
    "confidence": 0.0,
    "issues": ["no_candidates"]
  },
  "candidate_source": "none",
  "best_expansion": null
}
```

转 record：

```json
{
  "abbreviation": "XYZ",
  "expansion": null,
  "status": "NOT_EXPANDED",
  "failure": {
    "type": "ABBR_NOT_EXPANDED",
    "stage": "coverage"
  }
}
```

这就是“保守失败”。

面试说法：

> 对未知缩写，即使 token gate 放行，也必须经过 fallback 和 coverage。没有候选或置信度不足时会进入 `NOT_EXPANDED`，系统保留原文，不会为了看起来完整而强行扩写。

---

## 13. 候选召回和 record 状态的关系

你可以把这章和 03 章连起来：

```text
candidate retrieval + coverage
    ↓
best_expansion ?
    ├─ yes → record.expansion = best_expansion, status = PENDING
    └─ no  → record.expansion = null, status = NOT_EXPANDED
```

也就是说：

```text
04 章决定 record 能不能进入 PENDING。
03 章讲 PENDING 后面如何变成 CODED / WITHHELD。
```

---

## 14. 这套设计到底防了什么风险

### 风险 1：LLM 直接改写整句

解决：

```text
LLM 不直接输出 expanded_text。
expanded_text 由确定性替换生成。
```

---

### 风险 2：LLM 编造 expansion

解决：

```text
coverage 的 best_expansion 必须来自候选列表。
```

---

### 风险 3：候选库覆盖不足

解决：

```text
primary 没有时允许 fallback 生成候选。
```

---

### 风险 4：fallback 过度扩写

解决：

```text
fallback 候选必须通过 coverage，且 confidence >= 0.8。
```

---

### 风险 5：普通词误触发缩写流程

解决：

```text
token gate 只放行已知缩写或全大写未知 token。
```

---

## 15. 面试怎么讲这章

30 秒版本：

> 我没有让 LLM 直接扩写整句，而是把扩写拆成候选召回和 coverage 闸门。系统先用 token gate 找出可能缩写，然后优先查结构化候选词典；词典没有时才用 LLM fallback 生成候选。fallback 也不能直接改原文，只能返回候选列表。最后 coverage evaluator 判断候选集合里是否有上下文支持的扩写，并且 `best_expansion` 必须逐字来自候选列表。只有通过这个闸门的缩写才会进入 `PENDING`，否则就是 `NOT_EXPANDED`。

2 分钟版本：

> 缩写扩写最大的风险是 LLM 看起来把句子改得很顺，但实际上改了临床含义。所以我的设计不是让 LLM 直接输出扩写后的句子，而是先做 token gate，只处理已知缩写或全大写的可疑 token。进入候选召回后，系统优先查 `ABBR_CANDIDATES`，比如 `CP` 会召回 `chest pain`、`cerebral palsy`、`chronic pancreatitis`，`ASA` 会召回 `aspirin` 并标成 `Drug`。
>
> 如果主候选库没有结果，才启用 fallback LLM。但 fallback 的 prompt 被限制为只生成候选扩写，不能重写原文，不能添加诊断或治疗，也不能硬凑首字母。fallback 生成后还会用 NER 给 expansion 补 domain，方便后续药品走 RxNorm，其他走 SNOMED。
>
> 候选拿到后，coverage evaluator 会判断候选集合中是否至少有一个符合当前上下文的合理扩写，并选出 `best_expansion`。这里还有一个重要约束：`best_expansion` 必须逐字来自候选列表，不能由 coverage 自己 invent。对于 fallback 候选，coverage 还必须通过且 confidence 至少 0.8，否则不扩写。最终只有有 `best_expansion` 的缩写才会写入 `record.expansion` 并进入 `PENDING`；没有可靠扩写的会进入 `NOT_EXPANDED`。

---

## 16. 你要记住的 7 句话

1. LLM 不直接扩写整句，只生成候选或做判断。
2. token gate 用来避免普通词进入缩写流程。
3. primary candidates 来自 `ABBR_CANDIDATES`，是受控候选空间。
4. fallback 只在 primary 没结果时启用。
5. fallback 生成的是候选，不是最终扩写。
6. coverage 的 `best_expansion` 必须来自候选列表。
7. fallback 候选 coverage 不通过或 confidence 小于 0.8，就进入 `NOT_EXPANDED`。

---

## 17. 下一章建议

下一章建议写：

```text
05_确定性替换_为什么expanded_text不是LLM写的.md
```

因为 04 解释了 `record.expansion` 怎么来，下一步就该讲：

```text
有了 expansion 后，系统怎么安全地把 ASA / CP / SOB 替换成完整术语？
为什么要用 token 边界？
为什么要从后往前替换？
为什么 ABSTAIN 不可见？
```

