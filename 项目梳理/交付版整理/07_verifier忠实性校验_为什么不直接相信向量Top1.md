# 07_verifier 忠实性校验：为什么不直接相信向量 Top1

> 这一章接着 06 讲：
> 06 已经把 `record.expansion` 查成了 `std_cache` 候选列表，07 解释为什么还不能直接取 Top1。

---

## 先说结论

向量检索 Top1 不等于最终标准概念。

V11 会把 `std_cache` 交给：

```text
backend/services/abbr_verifier.py
ABBVerifier.verify_mappings()
```

让 verifier 做一件事：

```text
在候选标准概念里，选择和 expansion 最忠实的那个 concept。
如果没有忠实候选，就弃码 WITHHELD。
```

它不做三件事：

1. 不重新判断缩写该不该扩成这个 expansion。
2. 不自由生成 SNOMED/RxNorm concept。
3. 不为了有 code 而强行选择不忠实候选。

你可以把 verifier 理解成：

```text
标准概念 grounding 裁判。
```

---

## 1. 为什么不能直接相信向量 Top1

假设 expansion 是：

```text
chest pain
```

向量检索可能返回：

```text
1. Chest pain rating
2. Chest pain
3. Chest pain management
```

从字符串上看，它们都和 `chest pain` 很像。

但医学语义不一样：

| 候选 | 是否忠实 | 原因 |
|---|---|---|
| `Chest pain` | 是 | 同一临床实体 |
| `Chest pain rating` | 否 | 这是评分/量表，不是症状本身 |
| `Chest pain management` | 否 | 这是管理/处理，不是症状本身 |

向量检索擅长：

```text
找相似文本。
```

但标准化需要的是：

```text
找同一临床实体。
```

这两个不是一回事。

所以 V11 不直接取 Top1，而是：

```text
向量检索召回候选
  ↓
verifier 判断忠实性
  ↓
只有忠实候选才 CODED
```

面试说法：

> 向量 Top1 只代表语义相似，不一定代表标准化忠实。比如 `Chest pain rating` 和 `chest pain` 很相似，但前者是量表，后者是症状。Verifier 的作用就是在候选里判断是否是同一临床实体。

---

## 2. verifier 在主链路的位置

当前链路已经走到：

```text
record.expansion
  ↓
MedicalRetriever.retrieve()
  ↓
record.std_cache
```

接下来主状态机会构造：

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

然后调用：

```python
verification = self.verifier.verify_mappings(
    original_text=text,
    expanded_text=current_expanded_text,
    mapping_standardizations=mapping_standardizations,
)
```

所以 verifier 的输入是：

```text
原文
扩写后文本
每个 expansion 的标准概念候选列表
```

它输出：

```text
每个 mapping 选哪个 candidate index，或者不选。
```

---

## 3. verify_mappings 的输入结构

假设 `CP -> chest pain` 的 `std_cache` 是：

```json
[
  {
    "concept_id": "111",
    "concept_name": "Chest pain rating",
    "domain_id": "Observation",
    "concept_code": "...",
    "score": 0.91,
    "rerank_score": 1.06
  },
  {
    "concept_id": "222",
    "concept_name": "Chest pain",
    "domain_id": "Condition",
    "concept_code": "...",
    "score": 0.88,
    "rerank_score": 1.38
  }
]
```

传给 verifier 前，会包成：

```json
[
  {
    "abbreviation": "CP",
    "expansion": "chest pain",
    "candidates": [
      {
        "concept_id": "111",
        "concept_name": "Chest pain rating",
        "domain_id": "Observation",
        "score": 0.91
      },
      {
        "concept_id": "222",
        "concept_name": "Chest pain",
        "domain_id": "Condition",
        "score": 0.88
      }
    ]
  }
]
```

`verify_mappings()` 内部还会给每个候选加 `index`：

```python
{
    "index": index,
    **candidate
}
```

所以 LLM 看到的是带编号的候选：

```json
[
  {
    "index": 0,
    "concept_name": "Chest pain rating"
  },
  {
    "index": 1,
    "concept_name": "Chest pain"
  }
]
```

它只能返回：

```text
chosen_index = 0 / 1 / null
```

不能自己编一个 concept。

---

## 4. verifier 不重判 expansion

prompt 里有一句非常关键：

```text
Your job is NOT to re-judge whether the abbreviation expansion is correct.
That decision has already been made by the abbreviation coverage stage.
```

这说明 V11 把两个问题拆开了：

| 阶段 | 问题 |
|---|---|
| coverage | `CP` 是否应该扩成 `chest pain` |
| verifier | `chest pain` 应该绑定哪个标准概念 |

verifier 不应该说：

```text
我觉得 CP 不该是 chest pain。
```

它只能说：

```text
在给定 chest pain 这个 expansion 的前提下，哪个候选概念最忠实？
```

面试说法：

> Coverage 决定 abbreviation 到 expansion，Verifier 决定 expansion 到 standard concept。这样职责不会混在一起，避免同一个 LLM 节点既改扩写又改标准化，导致错误不好归因。

---

## 5. 什么叫 faithful

verifier prompt 定义了 faithful：

```text
A candidate is FAITHFUL when its concept_name denotes the SAME clinical entity as the expansion.
```

可以选的情况：

| expansion | candidate | 是否可选 | 原因 |
|---|---|---|---|
| `chest pain` | `Chest pain` | 是 | 同一临床实体 |
| `hypertension` | `Hypertensive disorder` | 是 | 忠实父概念/同义表达 |
| `coronary artery disease` | `Disorder of coronary artery` | 是 | 更一般但仍忠实 |

prompt 允许：

```text
exact clinical synonym
faithful parent term
```

原因是标准库里不一定刚好有完全同名概念。

如果没有完全同名，但有不增加额外信息的忠实父概念，也可以接受。

---

## 6. 什么不叫 faithful

prompt 也明确了不能选的情况：

### 1. 添加了 expansion 没说的信息

例如 expansion：

```text
myocardial infarction
```

候选：

```text
acute inferior wall myocardial infarction
```

这个候选多了：

```text
acute
inferior wall
```

原 expansion 没说，就不能选。

### 2. 相关但不是同一临床实体

例如 expansion：

```text
chest pain
```

候选：

```text
Chest pain rating
Chest pain education
Chest pain management service
Family history of chest pain
```

这些都包含 chest pain，但不是同一件事。

所以不能选。

面试说法：

> Faithful 的标准不是字符串相似，而是同一临床实体。相关服务、量表、检查、教育、家族史，或者添加了 subtype、cause、stage、site 的候选，都不能因为相似就选。

---

## 7. verifier 的输出结构

verifier 要返回：

```json
{
  "mapping_validations": [
    {
      "abbreviation": "CP",
      "expansion": "chest pain",
      "chosen_index": 1,
      "standardization_faithful": true,
      "reason": "Candidate 1 denotes the same clinical finding."
    }
  ]
}
```

`verify_mappings()` 会包成：

```json
{
  "sentence_validity": {
    "is_valid": true,
    "confidence": 1.0,
    "reason": "Expansion validity is decided upstream by coverage.",
    "issues": []
  },
  "mapping_validations": [
    {
      "abbreviation": "CP",
      "expansion": "chest pain",
      "chosen_index": 1,
      "standardization_faithful": true,
      "reason": "Candidate 1 denotes the same clinical finding."
    }
  ],
  "overall_valid": true
}
```

注意：

```text
sentence_validity 是兼容结构。
真正重要的是 mapping_validations。
```

---

## 8. `overall_valid` 不等于全部忠实

代码里：

```python
"overall_valid": len(mapping_validations) == len(mapping_standardizations)
```

这说明当前 `overall_valid` 只检查：

```text
返回 validation 的数量是否等于输入 mapping 数量。
```

它不检查：

```text
每个 mapping 是否 faithful。
```

所以不能在面试里说：

```text
overall_valid=true 表示所有标准化都成功。
```

更准确的说法是：

```text
真正是否 CODED，要看 ABBRService 对每条 validation 的 chosen_index 和 standardization_faithful 检查。
```

面试说法：

> 当前 `overall_valid` 更像返回结构完整性检查，不是严格的全部忠实判断。真正是否编码成功是在 ABBRService 里逐条判断 `standardization_faithful` 和 `chosen_index` 合法性。

---

## 9. ABBRService 怎么使用 verifier 结果

主状态机先找到每条 record 对应的 validation：

```python
def _find_validation(rec):
    for v in validations:
        if v.get("abbreviation") == rec["abbreviation"] and v.get("expansion") == rec["expansion"]:
            return v
    return None
```

然后取：

```python
chosen_index = v.get("chosen_index") if v else None
faithful = bool(v and v.get("standardization_faithful") is True)
```

再做合法性检查：

```python
valid_index = (
    faithful
    and isinstance(chosen_index, int)
    and not isinstance(chosen_index, bool)
    and 0 <= chosen_index < len(r["std_cache"])
)
```

这里有四个条件：

| 条件 | 意义 |
|---|---|
| `faithful` | verifier 必须明确说忠实 |
| `chosen_index` 是 int | 不能是 null、字符串等 |
| `not isinstance(chosen_index, bool)` | 防止 Python 里 `True/False` 被当成 1/0 |
| index 在范围内 | 不能越界 |

只有都满足：

```python
r["std_concept"] = r["std_cache"][chosen_index]
```

否则：

```python
r["std_concept"] = None
```

这一步是很好的防御式编程。

---

## 10. CODED 是怎么来的

如果 `std_concept` 不为空：

```python
if r["std_concept"]:
    r["status"] = "CODED"
    r["failure"] = None
```

也就是说：

```text
CODED = verifier 选出忠实候选 + chosen_index 合法。
```

示例：

```json
{
  "abbreviation": "CP",
  "expansion": "chest pain",
  "std_cache": [
    {"concept_name": "Chest pain rating"},
    {"concept_name": "Chest pain"}
  ],
  "std_concept": {
    "concept_name": "Chest pain"
  },
  "status": "CODED",
  "failure": null
}
```

---

## 11. WITHHELD 是怎么来的

如果没有合法忠实候选：

```python
else:
    r["status"] = "WITHHELD"
    r["failure"] = {
        "type": "CODE_WITHHELD",
        "stage": "standardization",
        "reason": ...,
        "evidence": {
            "retrieved_top": [...]
        },
    }
```

常见原因：

- verifier 返回 `chosen_index = null`。
- `standardization_faithful` 不是 `true`。
- `chosen_index` 不是整数。
- `chosen_index` 越界。
- verifier JSON 解析失败，导致没有 validation。
- `std_cache` 里没有忠实概念。

`WITHHELD` 的含义：

```text
扩写可以保留，但标准编码不输出。
```

例如：

```json
{
  "abbreviation": "CP",
  "expansion": "chest pain",
  "status": "WITHHELD",
  "std_concept": null,
  "failure": {
    "type": "CODE_WITHHELD",
    "stage": "standardization",
    "reason": "no faithful SNOMED concept among retrieved candidates",
    "evidence": {
      "retrieved_top": [
        "Chest pain rating",
        "Chest pain management service"
      ]
    }
  }
}
```

面试说法：

> 选不到忠实 concept 时，我不会强行拿 Top1，而是把 record 标成 `WITHHELD`，并记录 `CODE_WITHHELD`、原因和检索到的 top candidates。这样扩写文本可以保留，但标准编码不会乱给。

---

## 12. 为什么 WITHHELD 不撤销扩写

这个问题很容易被问。

原因是：

```text
扩写是否成立
标准概念是否忠实
是两个问题
```

比如：

```text
SOB -> shortness of breath
```

coverage 很确定这个扩写是对的。

但是标准库检索出来的候选都不太忠实。

这时系统应该：

```text
保留 shortness of breath
但不输出 concept code
```

而不是：

```text
因为没有 concept，就把 SOB 也撤回。
```

所以：

| 层级 | 结果 |
|---|---|
| expansion | 可以成功 |
| standardization | 可以 withheld |

这就是扩写和编码解耦。

---

## 13. 用 ASA、CP、SOB 走一遍

输入：

```text
The patient took ASA for CP and denies SOB.
```

经过 06 后：

```json
[
  {
    "abbreviation": "ASA",
    "expansion": "aspirin",
    "std_cache": ["rxnorm candidate 0", "rxnorm candidate 1"]
  },
  {
    "abbreviation": "CP",
    "expansion": "chest pain",
    "std_cache": ["snomed candidate 0", "snomed candidate 1"]
  },
  {
    "abbreviation": "SOB",
    "expansion": "shortness of breath",
    "std_cache": ["snomed candidate 0", "snomed candidate 1"]
  }
]
```

verifier 返回示意：

```json
{
  "mapping_validations": [
    {
      "abbreviation": "ASA",
      "expansion": "aspirin",
      "chosen_index": 0,
      "standardization_faithful": true
    },
    {
      "abbreviation": "CP",
      "expansion": "chest pain",
      "chosen_index": 1,
      "standardization_faithful": true
    },
    {
      "abbreviation": "SOB",
      "expansion": "shortness of breath",
      "chosen_index": null,
      "standardization_faithful": false,
      "reason": "No candidate denotes the same clinical entity."
    }
  ]
}
```

主状态机更新：

```json
[
  {
    "abbreviation": "ASA",
    "status": "CODED",
    "std_concept": "rxnorm candidate 0"
  },
  {
    "abbreviation": "CP",
    "status": "CODED",
    "std_concept": "snomed candidate 1"
  },
  {
    "abbreviation": "SOB",
    "status": "WITHHELD",
    "std_concept": null,
    "failure": {
      "type": "CODE_WITHHELD"
    }
  }
]
```

最终：

```text
expanded_text 仍然可以包含 shortness of breath。
standardized_entities 只包含 ASA 和 CP。
```

---

## 14. verifier 旧方法和新方法不要混

`abbr_verifier.py` 里还有一个旧方法：

```python
def verify(self, original_text, expanded_text, standardization):
```

它是早期整句校验接口，返回：

```text
is_valid / confidence / reason / issues
```

V11 主链路主要用的是：

```python
verify_mappings()
```

它返回：

```text
chosen_index / standardization_faithful
```

所以读代码时不要把两者混在一起。

| 方法 | 当前主链路地位 | 判断对象 |
|---|---|---|
| `verify()` | 旧接口/兼容遗留 | 整句扩写是否保持原意 |
| `verify_mappings()` | V11 主链路使用 | 每个 expansion 的标准概念是否忠实 |

面试时建议只讲 `verify_mappings()`。

---

## 15. verifier 用哪个 LLM

`ABBVerifier` 初始化：

```python
def __init__(self, config: LLMConfig = DEEPSEEK_CONFIG):
    self.llm = create_llm(config)
```

LLM 配置：

```python
DEEPSEEK_CONFIG = LLMConfig(
    provider=LLMProvider.DEEPSEEK,
    model_name="deepseek-chat",
)

QWEN_CONFIG = LLMConfig(
    provider=LLMProvider.QWEN,
    model_name="qwen3.6-flash",
)
```

工厂：

```python
create_llm(config)
```

当前默认：

```text
DeepSeek / deepseek-chat
temperature = 0.0
max_retries = 2
```

这比 fallback/coverage 里直接 `ChatDeepSeek(...)` 更统一。

面试说法：

> Verifier 通过 LLM config/factory 创建模型，默认是 DeepSeek，temperature 为 0。这个设计方便后续把 verifier 切到别的模型，比如 Qwen，而不改业务逻辑。

---

## 16. 这章和前后章节怎么连起来

前一章 06：

```text
record.expansion
  ↓
MedicalRetriever / StdService / Milvus
  ↓
std_cache
```

本章 07：

```text
std_cache
  ↓
verify_mappings()
  ↓
chosen_index + standardization_faithful
  ↓
CODED / WITHHELD
```

下一章要讲：

```text
WITHHELD 或非精确结果
  ↓
反思生成 requery
  ↓
重检索
  ↓
再 verifier
```

---

## 17. 面试怎么讲这章

30 秒版本：

> 标准化时我不会直接相信向量 Top1，因为相似不等于忠实。比如 `chest pain` 可能检索到 `Chest pain rating`，但它是评分量表，不是症状本身。V11 会把候选列表交给 `verify_mappings()`，让 LLM 只能在候选 index 里选择最忠实概念，或者返回 null。ABBRService 只有在 `standardization_faithful=true` 且 `chosen_index` 合法时才把 record 标成 `CODED`，否则 `WITHHELD`。

2 分钟版本：

> 多源检索阶段只负责召回候选概念，不能直接把 Top1 当最终标准化结果。因为向量相似经常会召回相关但不等价的概念，比如 rating、management、history、procedure 这些词面相近但临床实体不同的结果。所以我在检索之后加了 verifier 层。
>
> Verifier 的职责边界很清楚。Coverage 已经决定缩写扩成什么，verifier 不再重判 expansion 是否正确；它只判断某个 expansion 在候选标准概念中有没有 faithful concept。Prompt 里限制它只能返回候选的 0-based `chosen_index` 或 null，不能发明 concept。Faithful 的标准是同一临床实体，可以是同义词或不添加额外信息的父概念；但如果候选添加了 subtype、cause、stage、site，或者只是相关服务、量表、检查、家族史，就必须弃码。
>
> ABBRService 还会做防御式检查：`standardization_faithful` 必须是 true，`chosen_index` 必须是合法 int，不能是 bool，也不能越界。通过后 record 变成 `CODED`，否则变成 `WITHHELD`，并记录 `CODE_WITHHELD` 的原因和候选证据。这样系统可以保留扩写文本，但不乱给标准编码。

---

## 18. 你要记住的 8 句话

1. 向量 Top1 只是相似，不一定忠实。
2. verifier 只判断 expansion 到 standard concept，不重判 abbreviation 到 expansion。
3. verifier 只能选候选 index 或 null，不能发明 concept。
4. faithful 表示同一临床实体。
5. rating、service、procedure、history 这类相关但不同的概念不能选。
6. `overall_valid` 不是全部忠实成功，只是数量完整性检查。
7. `standardization_faithful=true + chosen_index 合法` 才能 CODED。
8. 选不到忠实概念就 WITHHELD，不强行给 code。

---

## 19. 下一章建议

下一章建议写：

```text
08_标准化反思重检索_如何把WITHHELD救回CODED.md
```

因为现在我们已经知道：

```text
verifier 可能选不到忠实 concept
```

下一步要讲：

```text
系统怎么用 propose_requeries 生成同义检索词？
怎么重新查 Milvus？
怎么合并新旧候选？
为什么反思不能发明 concept？
为什么采纳规则要保守？
```

