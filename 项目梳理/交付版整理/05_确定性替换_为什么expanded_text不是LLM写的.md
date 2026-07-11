# 05_确定性替换：为什么 expanded_text 不是 LLM 写的

> 这一章接着 04 讲：
> 04 解释了 `record.expansion` 怎么来，05 解释系统怎么把它安全地放回原文。

---

## 先说结论

V11 里最终的 `expanded_text` 不是 LLM 直接生成的。

它是由这个函数确定性生成的：

```text
backend/services/abbr_service.py
ABBRService._build_expanded_text_deterministic()
```

核心逻辑：

```text
只拿已经有 expansion、且没有 ABSTAIN 的 record
  ↓
用 abbreviation 在原文里做 token 边界匹配
  ↓
把 abbreviation 替换成 expansion
  ↓
从后往前替换，避免位置错乱
```

所以你可以这样记：

```text
LLM 负责判断。
record 负责记账。
确定性替换函数负责真正改文本。
```

---

## 1. 为什么要专门做确定性替换

输入：

```text
The patient took ASA for CP and denies SOB.
```

如果让 LLM 直接输出扩写句子，它可能输出：

```text
The patient took aspirin for chest pain and denies shortness of breath.
```

但它也可能悄悄做一些你不想要的事：

- 改掉原句语序。
- 补充原文没有的信息。
- 忽略否定词。
- 把一个不确定缩写也强行扩写。
- 让输出格式不稳定。

医疗文本里，这些都很危险。

所以 V11 的做法是：

```text
LLM 只参与候选选择和校验。
原文替换必须由代码按规则完成。
```

这就是确定性替换的意义。

面试说法：

> 我没有让 LLM 直接生成 expanded text，而是让 LLM 只做候选判断。真正修改原句时，用确定性替换函数按 token 边界替换已经确认的缩写，这样可以避免 LLM 自由改写临床文本。

---

## 2. 入口函数长什么样

函数：

```python
def _build_expanded_text_deterministic(self, text: str, chosen: list[dict]) -> str:
    if not chosen:
        return text

    spans = []
    for item in chosen:
        abbr = item.get("abbreviation")
        expansion = item.get("expansion")
        if not abbr or not expansion:
            continue
        pattern = re.compile(rf"\b{re.escape(abbr)}\b")
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end(), expansion))

    spans.sort(key=lambda span: span[0], reverse=True)
    result = text
    for start, end, expansion in spans:
        result = result[:start] + expansion + result[end:]
    return result
```

它的输入不是任意 LLM 文本，而是：

```text
原始 text
已经被主状态机选中的 records
```

---

## 3. chosen 从哪里来

主状态机里有一个内部函数：

```python
def _visible(recs):
    return [
        r for r in recs
        if r["expansion"] and r["status"] != "ABSTAIN"
    ]
```

也就是说，能出现在 `expanded_text` 里的 record 必须满足：

| 条件 | 含义 |
|---|---|
| `r["expansion"]` 存在 | coverage 已经选出了扩写 |
| `r["status"] != "ABSTAIN"` | 这个缩写没有被最终放弃 |

所以：

```text
NOT_EXPANDED 没有 expansion，不会替换。
ABSTAIN 即使有 expansion，也不会替换。
CODED 会替换。
WITHHELD 也会替换。
```

这点很重要。

因为 `WITHHELD` 的意思是：

```text
扩写可信，但标准概念不敢绑定。
```

所以它仍然可以出现在 expanded_text 里。

---

## 4. 各状态对 expanded_text 的影响

| status | 有 expansion 吗 | 会替换进 expanded_text 吗 | 原因 |
|---|---:|---:|---|
| `NOT_EXPANDED` | 否 | 否 | coverage 没选出可靠扩写 |
| `PENDING` | 是 | 是 | 已有扩写，等待标准化 |
| `CODED` | 是 | 是 | 扩写和标准概念都成功 |
| `WITHHELD` | 是 | 是 | 扩写成功，只是标准概念 withheld |
| `ABSTAIN` | 可能有 | 否 | 最终放弃，不能再可见 |

这张表要记住。

它解释了为什么：

```text
expanded_text 不是只包含 CODED。
```

因为项目把两个问题拆开了：

```text
缩写能不能扩写？
扩写能不能绑定标准概念？
```

---

## 5. 用 ASA、CP、SOB 走一遍

原文：

```text
The patient took ASA for CP and denies SOB.
```

假设 04 章后得到 records：

```json
[
  {
    "abbreviation": "ASA",
    "expansion": "aspirin",
    "status": "PENDING"
  },
  {
    "abbreviation": "CP",
    "expansion": "chest pain",
    "status": "PENDING"
  },
  {
    "abbreviation": "SOB",
    "expansion": "shortness of breath",
    "status": "PENDING"
  }
]
```

`_visible(records)` 会返回这 3 条。

于是替换关系是：

| abbreviation | expansion |
|---|---|
| `ASA` | `aspirin` |
| `CP` | `chest pain` |
| `SOB` | `shortness of breath` |

最终：

```text
The patient took aspirin for chest pain and denies shortness of breath.
```

注意，这句话不是 LLM 写的。

它是代码把三个缩写在原文中的位置替换出来的。

---

## 6. token 边界为什么重要

替换代码里有一句：

```python
pattern = re.compile(rf"\b{re.escape(abbr)}\b")
```

这里的 `\b` 是 token 边界。

它的作用是：

```text
只替换独立出现的缩写，不替换别的单词里的一部分。
```

例子：

```text
Patient needs CPR after CP episode.
```

如果不用 token 边界，替换 `CP -> chest pain` 时可能误伤：

```text
CPR
```

变成很离谱的东西。

有 token 边界后：

```text
CPR 不会被替换。
独立的 CP 会被替换。
```

也就是说：

```text
CPR 保持 CPR
CP 变成 chest pain
```

面试说法：

> 替换时我用了 token boundary，避免把缩写作为其他词的一部分误替换。例如替换 CP 时不能误伤 CPR。

---

## 7. `re.escape(abbr)` 是干什么的

代码：

```python
re.escape(abbr)
```

它的作用是：

```text
把 abbreviation 里的正则特殊字符转义。
```

虽然当前医学缩写大多是字母，比如：

```text
ASA, CP, SOB
```

但如果未来出现带特殊符号的缩写，比如：

```text
C+
A/B
```

直接拼进正则可能会被解释成正则语法。

`re.escape` 可以让它们按普通文本匹配。

这属于防御式写法。

面试不用展开讲，但如果被问到正则细节，可以说：

> `re.escape` 是为了避免 abbreviation 中出现正则特殊字符时破坏匹配语义。

---

## 8. 为什么要从后往前替换

代码：

```python
spans.sort(key=lambda span: span[0], reverse=True)
```

这表示：

```text
按匹配起点从大到小排序。
```

也就是从后往前替换。

为什么？

因为替换会改变字符串长度。

例如：

```text
ASA CP SOB
```

如果先从前面替换：

```text
ASA → aspirin
```

文本长度变长，后面 `CP` 和 `SOB` 的原始位置就不准了。

从后往前替换则不会影响前面还没替换的 span：

```text
先替换 SOB
再替换 CP
最后替换 ASA
```

这是一种常见的字符串替换技巧。

面试说法：

> 我先收集所有匹配 span，再从后往前替换，避免前面的替换改变字符串长度后导致后续 offset 错位。

---

## 9. 为什么先收集 spans，而不是边找边替换

函数不是这样写的：

```python
for item in chosen:
    result = result.replace(abbr, expansion)
```

而是：

```text
先在原文里找出所有 abbreviation 的位置
再统一排序替换
```

原因有三个：

### 1. 避免误替换

`str.replace()` 不懂 token 边界。

例如：

```text
CPR
```

可能被误伤。

### 2. 避免替换顺序影响位置

统一收集 span 后，从后往前替换更稳定。

### 3. 保持替换来源清晰

每个 span 都来自某个 record 的：

```text
abbreviation → expansion
```

后续排查更容易。

---

## 10. expanded_text 在流程里会生成多次

主状态机里至少会生成三次 `current_expanded_text`。

### 第一次：records 初始化后

```python
current_expanded_text = self._build_expanded_text_deterministic(
    text,
    _visible(records)
)
```

这时它用于：

```text
给后面的标准化和 verifier 提供 expanded context。
```

比如 verifier 会拿到：

```text
original_text = The patient took ASA for CP and denies SOB.
expanded_text = The patient took aspirin for chest pain and denies shortness of breath.
```

这样 verifier 能对照原文和扩写后文本。

---

### 第二次：每轮校验/反思后

```python
current_expanded_text = self._build_expanded_text_deterministic(
    text,
    _visible(records)
)
```

为什么要重新生成？

因为某些 record 的状态可能在这轮发生变化：

```text
PENDING → CODED
PENDING → WITHHELD
WITHHELD → CODED
PENDING → ABSTAIN
```

重新生成可以保证：

```text
expanded_text 始终由最新 record 状态决定。
```

---

### 第三次：最终输出前

```python
current_expanded_text = self._build_expanded_text_deterministic(
    text,
    _visible(records)
)
```

最终 `final_result["expanded_text"]` 使用这个值。

所以：

```text
最终文本永远是从原始 text + 最终可见 records 重新构造出来的。
```

不是在前一次 expanded_text 上继续改。

这能减少累积错误。

---

## 11. 为什么每次都从原始 text 重建

这是一个很好的工程细节。

如果系统每次都在上一次 `expanded_text` 上继续替换，可能出现：

```text
重复替换
替换错位
状态撤销后文本还残留
```

V11 的方式是：

```text
原始 text 永远不变。
每次根据当前 records 重新生成 expanded_text。
```

这相当于：

```text
text 是事实源。
records 是决策状态。
expanded_text 是渲染结果。
```

这个理解非常重要。

你可以类比成前端：

```text
state 改了以后重新 render UI
而不是手工一点点修改旧 DOM
```

面试说法：

> 我把原始文本当作 immutable source，每次根据当前 record 状态重新 render expanded_text，而不是在上一轮 expanded_text 上继续修改。这样可以避免多轮重试带来的重复替换和状态残留。

---

## 12. `WITHHELD` 为什么仍然可见

前面说过：

```python
def _visible(recs):
    return [r for r in recs if r["expansion"] and r["status"] != "ABSTAIN"]
```

`WITHHELD` 满足：

```text
有 expansion
status 不是 ABSTAIN
```

所以它会进入 `expanded_text`。

这看起来有点奇怪，但其实很合理。

因为 `WITHHELD` 的语义是：

```text
扩写可信。
标准概念不敢绑定。
```

例如：

```json
{
  "abbreviation": "SOB",
  "expansion": "shortness of breath",
  "status": "WITHHELD",
  "std_concept": null
}
```

最终文本可以是：

```text
denies shortness of breath
```

但 `standardized_entities` 里不一定有 SOB 对应的 concept。

这体现了：

```text
扩写层和标准化层是解耦的。
```

---

## 13. `ABSTAIN` 为什么不可见

如果某条 record 最终变成：

```json
{
  "abbreviation": "XYZ",
  "expansion": "some expansion",
  "status": "ABSTAIN"
}
```

即使它有 expansion，也不会进入 `_visible(records)`。

原因是：

```text
ABSTAIN 表示系统最终放弃，不应该让它悄悄出现在文本里。
```

这是一条安全线：

```text
只要最终状态是 ABSTAIN，原文就保留。
```

面试说法：

> `ABSTAIN` 是最终放弃状态，所以即使 record 上曾经有 expansion，也不会参与 expanded_text 渲染，避免不可靠扩写出现在用户结果里。

---

## 14. NOT_EXPANDED、WITHHELD、ABSTAIN 的区别

这三个状态很容易混。

| 状态 | 有没有 expansion | 文本替换吗 | 标准概念绑定吗 | 核心含义 |
|---|---:|---:|---:|---|
| `NOT_EXPANDED` | 否 | 否 | 否 | coverage 阶段就不敢扩 |
| `WITHHELD` | 是 | 是 | 否 | 扩写可保留，concept 不敢选 |
| `ABSTAIN` | 可能有 | 否 | 否 | 多轮后最终放弃 |

一句话记：

```text
NOT_EXPANDED 是没过扩写闸门。
WITHHELD 是过了扩写闸门但没过标准化闸门。
ABSTAIN 是系统最终决定别让它可见。
```

---

## 15. 一个边界例子：CP 和 CPR

输入：

```text
Patient had CP but no CPR was performed.
```

假设：

```text
CP → chest pain
```

正确结果应该是：

```text
Patient had chest pain but no CPR was performed.
```

错误结果可能是：

```text
Patient had chest pain but no chest painR was performed.
```

V11 为什么不会这样？

因为它用：

```python
\bCP\b
```

只匹配独立 token `CP`，不匹配 `CPR` 里的 `CP`。

这就是 token 边界的价值。

---

## 16. 一个边界例子：重复缩写

输入：

```text
CP improved, but CP recurred.
```

如果 record 是：

```json
{
  "abbreviation": "CP",
  "expansion": "chest pain"
}
```

函数会找到两个 match：

```text
第一个 CP
第二个 CP
```

最终：

```text
chest pain improved, but chest pain recurred.
```

也就是说：

```text
同一个缩写在原文里多次出现，会全部替换。
```

这也符合当前函数行为。

如果未来需要“只替换某个位置的缩写”，那就要引入 offset-aware record，但当前 V11 还不是这个设计。

面试如果被问到可以诚实说：

> 当前实现是按 abbreviation 全文 token 边界替换，适合多数同义扩写场景；如果未来同一句里同一缩写出现多种含义，需要把 record 扩展为带 offset 的 mention-level 结构。

这句话很加分，因为它说明你知道当前设计边界。

---

## 17. 一个边界例子：大小写

当前替换正则没有显式加：

```python
re.IGNORECASE
```

也就是说：

```text
record.abbreviation = "SOB"
```

主要匹配原文里的：

```text
SOB
```

而不是一定匹配：

```text
sob
```

不过前面的 `_should_consider_abbreviation` 对已知缩写是允许大小写归一化进入候选召回的。

这里有一个细节：

```text
候选识别阶段可能把 sob 识别为 SOB。
但替换阶段拿的是 abbreviation = "SOB" 去原文匹配。
如果原文是小写 sob，当前替换可能匹配不到。
```

这属于一个潜在改进点。

面试时不必主动展开，但如果被追问“大小写怎么处理”，可以诚实说：

> 当前候选识别会把已知缩写归一化成大写，但替换阶段按 abbreviation 做大小写敏感匹配。如果要更严谨，可以在 record 里保留原始 mention 或 offset，用原文 span 替换，而不是只用大写缩写回查。

这也是后续清理和改进可以考虑的地方。

---

## 18. 这章和前后章节怎么连起来

前一章 04：

```text
候选召回 + coverage
  ↓
决定 record.expansion
```

本章 05：

```text
record.expansion + record.status
  ↓
生成 expanded_text
```

下一章应该讲：

```text
expanded_text + record.expansion
  ↓
去 SNOMED / RxNorm 查标准概念
```

所以主链路现在已经连成：

```text
候选选择
  → record.expansion
  → 确定性替换
  → expanded_text
  → 标准概念检索
```

---

## 19. 面试怎么讲这章

30 秒版本：

> V11 的 `expanded_text` 不是 LLM 直接生成的，而是由 `_build_expanded_text_deterministic` 从原始文本和当前 records 重新构造出来。只有有 expansion 且不是 `ABSTAIN` 的 record 会参与替换。替换时用 token boundary，避免把 `CP` 误替换到 `CPR` 里；同时先收集所有匹配 span，再从后往前替换，避免字符串长度变化导致 offset 错位。

2 分钟版本：

> 我的设计里，LLM 不直接改写临床文本。coverage 只负责选出每个缩写的 `best_expansion`，然后主状态机会把它写入 record。真正生成 `expanded_text` 时，系统调用 `_build_expanded_text_deterministic`，从原始 text 出发，根据当前可见 records 做替换。
>
> 这里有几个工程细节。第一，要分清“第一次替换”和“最终重渲染”。第一次进入标准化检索前，record 通常只有 `PENDING` / `NOT_EXPANDED`，所以真正会被替换的是已经拿到 expansion 的 `PENDING`；`NOT_EXPANDED` 没有 expansion，不会替换。后面经过 verifier / reflection 后，record 可能变成 `CODED`、`WITHHELD` 或 `ABSTAIN`，同一个替换函数还会再次从原文重建 `expanded_text`。这时 `CODED` 和 `WITHHELD` 仍然可见，因为它们表示扩写可信；`ABSTAIN` 不可见，因为它表示最终放弃。第二，替换时用 `\b...\b` token 边界，避免 `CP` 误伤 `CPR`。第三，函数先在原文中收集所有匹配 span，再从后往前替换，避免前面替换后改变字符串长度导致后面的 offset 错位。
>
> 另外，每一轮都会从原始 text 和最新 records 重新生成 `expanded_text`，而不是在上一轮结果上继续改。可以把它理解成：`text` 是不可变原始病历，`records` 是当前事实表，`expanded_text` 只是根据这张事实表临时渲染出来的展示结果。假设某个缩写第一轮是 `PENDING`，文本里被渲染成 expansion；后面 verifier / reflection 认为它应该 `ABSTAIN`，系统不会在“已经替换过的句子”里反向找 expansion 再改回去，而是直接拿原始 text 重新渲染一次。因为这个 record 现在不可见，最终文本自然保留原缩写。这样可以避免多轮 retry 后出现重复替换、旧 expansion 残留、或者 offset 错位。

---

## 20. 你要记住的 8 句话

1. `expanded_text` 不是 LLM 写的。
2. 它由 `_build_expanded_text_deterministic()` 从原文重建。
3. 能参与替换的是 `_visible(records)`。
4. `NOT_EXPANDED` 不替换。
5. `WITHHELD` 会替换，但不会产生标准概念。
6. `ABSTAIN` 不可见，避免不可靠扩写进入结果。
7. token 边界防止 `CP` 误伤 `CPR`。
8. 从后往前替换避免 offset 错位。

---

## 21. 下一章建议

下一章建议写：

```text
06_多源标准化_SNOMED与RxNorm到底怎么查.md
```

因为现在我们已经有了：

```text
record.expansion
expanded_text
domain
```

下一步就该讲：

```text
domain 怎么决定查 SNOMED 还是 RxNorm？
MedicalRetriever 怎么调用 StdService？
StdService 怎么用 embedding 和 Milvus 查两个 collection？
规则重排又解决什么问题？
```
