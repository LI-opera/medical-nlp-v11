# ABBRCandidateFallbackRetriever（LLM 兜底召回：词典没货时让 LLM 补候选）

> 文件：`backend/services/abbr_candidate_fallback_retriever.py`（89 行）
> 入口：`retrieve(abbreviation, context_text)`
> 衔接：第 8 篇主召回（查词典）返回空时，这一层兜底——让 LLM 结合上下文**生成候选全称列表**。它和第 8 篇正好是"确定性 vs LLM"的对照：常见缩写走词典，长尾/未知缩写走这里。

## 核心速记
> 1. **职责死边界**：**只生成候选，绝不改写原句**。prompt 里反复强调（"You are NOT expanding the full sentence"）。这是本篇最该讲的设计点。
> 2. **两层召回**：词典覆盖常见、LLM 兜底长尾。覆盖率和可控性的平衡。
> 3. **一堆防幻觉护栏**：不是合理缩写就返回空、不要把首字母硬拼、不要发明罕见扩写。但护栏≠保证，产出仍要过 coverage + verification。
> 次要（trivia）：`temperature=0`、markdown 清洗、`parse_error` 兜底返回空——扫一眼。

## 这一段在解决什么

大白话：**词典里没有这个缩写时，问 LLM："结合这句话，它可能是什么全称？"** 但 LLM 只许给候选清单，不许动原句。

```text
"The patient has AKX after surgery."   （词典里没有 AKX）
   ↓ fallback LLM 看上下文生成候选
{ abbreviation:"AKX",
  candidates:[{expansion:"...", source:"fallback_llm", confidence:0.4}, ...],
  reason:"..." }
```

## 核心1 · 死死守住"只产候选，不改句"（骨架，必背）

prompt 里这点强调了至少三次：

```text
"You are NOT expanding the full clinical sentence.
 You are only generating candidate expansions for the abbreviation."
Rule 3: Do not rewrite the clinical text.
```

**为什么这条边界这么重要**：想象如果 fallback 直接改写句子——那它就**绕过了后面的 coverage 闸门和扩写 LLM**，一个 LLM 凭空想的全称会**直接进最终结果**，幻觉无人把关。

把它限制成"只往候选池里补充选项"，就保证了：**无论候选来自词典还是 LLM，都要走同一条后续流程**（coverage 裁决 → 扩写 LLM 在候选里选 → verification 校验）。**召回方式不同，但决策入口统一。** 这是整个架构能防幻觉的关键纪律。

> 对比第 8 篇：词典 retriever 返回 `{abbreviation, expansion}`，fallback 也返回同样结构的候选——**格式对齐**，所以下游不用关心候选是哪来的。

## 核心2 · 针对 LLM"硬编"倾向的防幻觉护栏（实现 + 真实数据）

LLM 最爱犯的错就是"看到缩写就硬给一个答案"。prompt 用规则一条条堵：

```text
Rule 6: 不是合理的医学缩写 → 返回空 candidates    （允许 LLM "不知道"）
Rule 7: 不要把恰好首字母相同的词硬拼成扩写        （防 AKX→"A Known X" 这种瞎拼）
Rule 8: 不要发明罕见、人造、无支撑的扩写
Rule 9: 只返回常用医学缩写、或被上下文强支持的
```

最关键的是 **Rule 6——允许 LLM 返回空**。这给了模型"我不知道"的出口，而不是逼它必须编一个。配合 `temperature=0`（要稳定可复现、不发散），尽量压低幻觉。

输出固定 JSON，带解析兜底：

```python
content = response.content.replace("```json","").replace("```","").strip()  # 清掉 markdown
try:
    parsed = json.loads(content)
except json.JSONDecodeError:
    return {"abbreviation":..., "candidates":[], "reason":"...did not return valid JSON.",
            "raw_output": content}   # 解析失败 → 返回空候选，不崩
return parsed
```

返回结构：

```text
{ "abbreviation":"AKX",
  "candidates":[{"abbreviation":"AKX","expansion":"...","source":"fallback_llm","confidence":0.4}],
  "reason":"brief explanation" }
```

注意 `source:"fallback_llm"` 标明来源——下游能区分这是 LLM 兜底来的（可信度低于词典）。

## 数据快照：词典 vs fallback 的分工

```text
retrieve 之前，ABBRService 的逻辑（第 14 篇细讲）：
   candidates = 主召回(查词典)
   if not candidates:                  ← 词典没货
       candidates = fallback.retrieve(abbr, 整句)   ← 才问 LLM
       source = "fallback"

所以 LLM 只在长尾缩写上被调用，常见缩写永远走零成本词典。
```

## 会被追问 / 诚实局限（★主动说）

- **fallback 本身就会幻觉**——这是它最大的风险，也是它存在的代价。prompt 加了 Rule 6-9 一堆护栏，但**LLM 不保证遵守**。
  → 面试这么说："fallback 用 LLM 补候选，本身有幻觉风险。我的应对是双重的：prompt 里给护栏（允许返回空、禁止硬拼/编造），更重要的是**它的产出绝不直接用，必须再过 coverage 和 verification**——召回可以激进，把关交给后面。" 这句"召回激进、把关在后"是核心。
- **`confidence` 是 LLM 自报的，不可靠**：LLM 对自己置信度的估计本来就不准，这个分数仅供参考，不能当真概率用。
  → "下游主要靠 coverage 重新判断，不依赖这个自报 confidence。"
- **每次调用花 token + 有延迟**（对比第 8 篇词典的零成本）。所以设计上**只在词典没货时才调**，控制调用频率。
- **没有缓存**：同一个未知缩写每次请求都重新问 LLM。高频长尾缩写可以缓存。
- **JSON 解析靠字符串 replace + `json.loads`**，比较脆弱。有 `parse_error` 兜底（返回空候选）不会崩，但格式漂移时这次召回就废了。`temperature=0` 降低了漂移概率但不为零。
- 【细节】prompt 里 `Clinical text:` 后面多了个反引号 `` ` ``，是个小笔误，不影响功能，但说明没逐字 review。

## 面试怎么说

**合格版（30 秒）**：
> 这是召回的兜底层：词典查不到时，让 LLM 结合上下文生成候选全称。它只产候选、不改原句，输出和词典对齐的 `{abbreviation, expansion}` 结构。prompt 里加了护栏——允许返回空、禁止硬拼和编造，temperature=0 求稳。

**优秀版（1 分钟）**：
> 我做了两层召回：常见缩写走零成本词典，词典没货才用 LLM fallback 兜底长尾。fallback 最关键的设计是职责边界——只许往候选池里补选项，绝不许改写句子。因为一旦它改句，就绕过了后面的 coverage 和扩写 LLM，幻觉直接进结果；限制成只产候选，就保证无论候选来自词典还是 LLM，都走同一条 coverage→选择→verification 流程，决策入口统一。fallback 本身会幻觉，我的应对是 prompt 护栏加上'产出绝不直接用、必须过后续把关'——召回可以激进，把关交给后面。诚实说它的 confidence 是 LLM 自报的不可靠，也没缓存，JSON 解析偏脆但有兜底。

## 易错点 / 面试问答

**Q：为什么要 LLM 兜底，不全用词典？** A：词典覆盖常见缩写但有长尾盲区。fallback 用 LLM 补未知缩写，提升覆盖率；代价是有幻觉风险和成本，所以只在词典没货时调。

**Q：为什么 fallback 只产候选、不改句？** A：保证决策入口统一。一旦它改句就绕过了 coverage 和扩写校验，幻觉直接进结果。限制成只补候选池，所有候选都走同一条把关流程。

**Q：fallback 幻觉怎么办？** A：双重应对——prompt 护栏（允许返回空、禁止硬拼/编造）+ 产出必须再过 coverage 和 verification，绝不直接用。召回激进、把关在后。

**Q：那个 confidence 能信吗？** A：不能太当真，是 LLM 自报的，估计本就不准。真正的把关靠下游 coverage 重新判断。

**Q：为什么 temperature=0？** A：求稳定可复现、压低发散和幻觉。召回不需要创造性。

## 一句话总结

> ABBRCandidateFallbackRetriever 是召回兜底层：词典没货时让 LLM 结合上下文生成候选，**只产候选、不改句**（保证决策入口统一、不绕过把关），输出与词典对齐并标 `source:"fallback_llm"`。靠 prompt 护栏（允许返回空、禁硬拼编造）+ temperature=0 压幻觉。它和第 8 篇组成"确定性词典 + LLM 兜底"两层召回。局限是 LLM 仍会幻觉（故产出必过 coverage/verification）、confidence 不可靠、无缓存、解析偏脆——核心纪律是"召回激进、把关在后"。
