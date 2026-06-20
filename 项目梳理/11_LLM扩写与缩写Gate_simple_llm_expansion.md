# LLM 扩写与缩写 Gate（前三阶段汇合：LLM 真正动手把缩写扩成全称）

> 文件：`backend/services/abbr_service.py`
> 涉及方法：`_should_consider_abbreviation()`（gate，597–628）、`_get_abbreviation_candidates()`（召回编排，515–595）、`simple_llm_expansion()`（LLM 扩写，64–134）
> 衔接：进入**阶段四（核心智能）**。前面 8/9/10 篇分别做了主召回、fallback、coverage，但都是零件。这一篇是它们的**汇合点**——gate 决定哪些 token 进流程，召回编排把三个零件串起来产出候选，最后 LLM 在候选里挑、把缩写扩成全称。产出 `expanded_text + mappings`，交给后面校验。

## 核心速记
> 1. **三步走**：① gate 过滤 token（哪些值得查）→ ② 召回编排（词典→fallback→coverage 串起来）→ ③ LLM 在候选里扩写。
> 2. **gate 的作用**：把 `the/patient/has` 这种噪声词挡在召回之外，避免对每个普通词都查库/问 LLM。
> 3. **受约束生成**：prompt 要求 LLM "有候选时必须从候选里选"，不许自由发挥——防幻觉的核心。
> 次要（trivia）：JSON markdown 清洗、`parse_error` 兜底、`source` 字段——扫一眼。

## 这一段在解决什么

大白话：**把"一句原始临床文本"变成"扩写后的文本 + 每个缩写扩成了什么"。**

```text
"Patient has SOB and CP."
   ↓ ① gate：SOB/CP 值得查，has/and 跳过
   ↓ ② 召回编排：每个缩写拿到候选 + coverage 结果
   ↓ ③ LLM 在候选里扩写
{ expanded_text: "Patient has shortness of breath and chest pain.",
  mappings: [{SOB→shortness of breath}, {CP→chest pain}] }
```

## 核心1 · Gate：哪些 token 才值得进召回（骨架）

`_should_consider_abbreviation` 是召回前的一道**过滤闸**。不是句子里每个词都去查词典/问 LLM——那既慢又容易误判。规则（按代码顺序）：

```python
if not token: return False                    # 空 → 跳过
upper_token = token.upper()
if not upper_token.isalpha(): return False     # 含数字/符号 → 跳过
if upper_token in known_abbrs: return True     # ① 已知缩写（大小写都行）→ 放行
if len(upper_token) < 2: return False          # 单字符 → 跳过
if token == upper_token and len(upper_token) <= 8: return True  # ② 全大写≤8字符 → 放行走 fallback
return False                                   # 其余（小写未知词）→ 跳过
```

翻译这套策略（三类）：
- **已知缩写**（在词典里）：`SOB`/`sob`/`HTN` 大小写都放行。
- **未知但"长得像缩写"**：原文**全大写**且 ≤8 字符（如 `AKX`、`XYZ`）→ 放行，去走 fallback（第 9 篇）。
- **小写未知词**（the、patient、chest）：跳过。不是不可能是缩写，而是**证据不足**，不值得为它花一次检索/LLM。

**为什么需要 gate**：没有它，`the`、`patient`、`and` 都会进召回流程，每个都查词典甚至问 LLM——又慢又会把普通词误当缩写。gate 是**用极廉价的规则先把噪声挡住**，只让"像缩写的"进入后面昂贵的流程。

> 注意 gate 的职责边界：它只管"**值不值得查**"，不管"**该不该扩**"。后者是 coverage 的事（回扣第 10 篇）。gate 让 `LMN` 通过去查，但 `LMN` 在低上下文该不该扩，是 coverage 决定的。

## 核心2 · 召回编排：把 8/9/10 三个零件串起来（实现 + 真实数据）

`_get_abbreviation_candidates` 是把前三阶段拼成一条流水线的地方：

```python
for word in words:                                   # 切 token
    if not self._should_consider_abbreviation(...): continue   # gate
    abbr = raw_token.upper()

    candidates = self.candidate_retriever.retrieve(abbr)        # ① 主召回（第8篇）
    candidate_source = "primary"
    if not candidates:                                          # 词典没货
        fallback_result = self.fallback_retriever.retrieve(abbr, text)  # ② fallback（第9篇）
        candidates = fallback_result.get("candidates", [])
        candidate_source = "fallback"
    if not candidates:                                          # 两层都没 → 标记 coverage 失败
        found.append({... "coverage_ok": False ... "candidate_source":"none"}); continue

    coverage = self.coverage_evaluator.evaluate(text, abbr, candidates)  # ③ coverage（第10篇）
    plausible = coverage.get("plausible_candidates", [])
    filtered_candidates = [c for c in candidates if c["expansion"] in plausible]  # 过滤
    found.append({abbreviation, candidates, filtered_candidates, coverage, candidate_source})
```

这就是**三层召回 + 闸门**的完整骨架：

```text
gate → 主召回(词典) → [空则] fallback(LLM) → coverage 裁决 → filtered_candidates
```

每个缩写最终带着：原始候选、过滤后候选、coverage 结果、来源（primary/fallback/none）。

## 核心3 · LLM 扩写：受约束生成（防幻觉的关键）

`simple_llm_expansion` 把候选喂给 LLM，让它**在候选里选**，而不是自由生成：

```python
abbreviation_candidates = self._get_abbreviation_candidates(text)   # 拿到上面那一坨
prompt = f"""... You must choose expansions from the provided abbreviation candidates when available.
   Clinical text: {text}
   Abbreviation candidates after coverage filtering: {json.dumps(abbreviation_candidates)}
   Rules:
     4. Use filtered_candidates as the primary candidate set.
     5. If filtered_candidates is empty because coverage_ok is false, do not force an expansion.
     6. If filtered_candidates is empty but coverage_ok is true, use original candidates with low confidence.
     7. Preserve negation, uncertainty, severity, timing, and clinical meaning.
   Return only valid JSON ..."""
response = self.llm.invoke(prompt)
```

**两个关键设计**：
- **受约束生成（constrained generation）**：核心规则是"**有候选时必须从候选里选**"。这把 LLM 从"自由发挥"约束成"在给定选项里挑"，是整条链防幻觉的最后一道、也是最重要的约束。
- **规则 5 给了"不扩"的出口**：filtered 为空且 coverage_ok=false 时，**别硬扩**——这是"什么时候不该扩写"的能力落点（回扣低上下文问题）。规则 7 要求保留否定/不确定（`denies CP` → `denies chest pain`，不能变成 `has`）。

解析与兜底：

```python
content = response.content.replace("```json","").replace("```","").strip()
try:
    parsed = json.loads(content)
except json.JSONDecodeError:
    return {"expanded_text": content, "mappings": [], "parse_error": True, ...}  # 降级
return {"original_text":text, "expanded_text": parsed.get("expanded_text", text),
        "mappings": parsed.get("mappings", []), "abbreviation_candidates":..., "parse_error":False}
```

## 数据快照

```text
【入】 "The patient denies CP."

gate：CP 放行；the/patient/denies 跳过
召回编排：CP →候选[chest pain, cerebral palsy, chronic pancreatitis]
          coverage→plausible[chest pain]，filtered=[chest pain]
LLM 扩写（约束在 filtered 里）：

【出】 { expanded_text:"The patient denies chest pain.",   ← 否定被保留
        mappings:[{abbreviation:"CP", expansion:"chest pain", source:"candidate"}] }
```

## 会被追问 / 诚实局限（★主动说）

- **过滤是"软约束"，不是代码硬截断**：注意 `simple_llm_expansion` 把**整个结构**（candidates + filtered_candidates + coverage）都 dump 进 prompt，靠**规则文字**让 LLM "优先用 filtered"。代码并没有只把 filtered 传进去。所以"只在支持的候选里选"是**靠 LLM 听话**，不是强制的。
  → 面试这么说："候选过滤目前是 prompt 软约束——我把完整候选和 filtered 都给 LLM，靠规则让它优先用 filtered。更稳的是代码层只传 filtered_candidates，做成硬约束，LLM 想越界都没得选。"
- **gate 是启发式，两头都有漏**：① 全大写≤8 字符的规则会放过一些恰好全大写的普通词（缩写误判）；② 小写写的缩写（`htn` 在词典里能命中，但词典外的小写缩写会被跳过）。阈值 8 也是拍的。
  → "gate 是廉价的预过滤，覆盖常见情况；边界 case（小写长尾缩写、全大写普通词）会漏，可以用更强的缩写检测模型替代。"
- **扩写质量完全依赖候选质量**：garbage in → garbage out。候选错了/漏了，LLM 再听话也扩不对。这把压力前移到召回和 coverage。
- **`parse_error` 降级很粗**：JSON 解析失败时，直接把 LLM 原始输出当 `expanded_text`、mappings 给空。这种情况下结果基本不可用，只是不崩。
  → "解析失败是兜底不是修复，可以加重试或更强的结构化输出（如 function calling / JSON mode）。"
- **规则 5'不强扩'靠 LLM 自觉**：和软约束同理，模型未必每次遵守，这也是低上下文仍会过度扩写的原因之一。

## 面试怎么说

**合格版（30 秒）**：
> 这步把原文变成扩写文本。先用一个轻量 gate 过滤 token——已知缩写和全大写短词才进流程，普通词跳过；然后串起三层召回（词典→fallback→coverage）拿到候选；最后让 LLM 在候选里选着扩写，要求保留否定等语义。核心是受约束生成，防止 LLM 自由幻觉。

**优秀版（1 分钟）**：
> 这是前三阶段的汇合点，分三步：gate 用廉价规则把噪声词挡在召回外，只让像缩写的进入昂贵流程；召回编排把词典、fallback、coverage 串成一条流水线，每个缩写带着过滤后候选和 coverage 结果；最后 simple_llm_expansion 做受约束生成——要求 LLM 有候选时必须从候选里选，不许自由发挥，这是整条链防幻觉的关键约束，配合规则给出"不该扩就不扩"的出口和"保留否定语义"的要求。诚实说几个点：候选过滤目前是 prompt 软约束，我把完整候选都给了 LLM 靠规则让它优先用 filtered，更稳应该代码层只传 filtered 做硬约束；gate 是启发式，全大写规则和小写长尾两头都有漏；解析失败的降级很粗。这些都是明确的改进项。

## 易错点 / 面试问答

**Q：gate 是干嘛的，为什么需要？** A：召回前的廉价过滤——已知缩写和全大写短词才进流程，the/patient 这种噪声词跳过。避免对每个词都查库/问 LLM，又快又减少误判。

**Q：gate 和 coverage 区别？** A：gate 管"值不值得查"（进不进召回），coverage 管"该不该扩"（上下文支不支持）。gate 让 LMN 通过去查，扩不扩由 coverage 定。

**Q：怎么防止 LLM 乱扩写？** A：受约束生成——prompt 要求有候选时必须从候选里选，不许自由发挥；并给"coverage 失败就不扩"的出口。把不确定性挡在候选召回和 coverage 之前。

**Q：候选过滤是强制的吗？** A：目前是软约束——代码把完整候选和 filtered 都给 LLM，靠规则让它优先用 filtered。更稳的是代码层只传 filtered，做成硬约束。

**Q：JSON 解析失败会怎样？** A：兜底把 LLM 原始输出当 expanded_text、mappings 给空，不崩但结果基本不可用。可以加重试或用 JSON mode。

## 一句话总结

> 这一步是前三阶段的汇合：gate（`_should_consider_abbreviation`）用廉价规则过滤 token、只放已知缩写和全大写短词进流程；召回编排（`_get_abbreviation_candidates`）把词典→fallback→coverage 串成流水线产出 filtered_candidates；`simple_llm_expansion` 做受约束生成，让 LLM 在候选里选着扩、保留否定语义、coverage 失败就不扩。产出 expanded_text + mappings。局限是过滤为 prompt 软约束（应改硬约束）、gate 启发式两头有漏、解析失败降级粗、不强扩靠 LLM 自觉——都是明确改进项。
