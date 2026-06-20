# ABBRReflectionService（反思修正：把失败原因回灌，让 LLM 重做一版）

> 文件：`backend/services/abbr_reflection_service.py`（86 行）
> 入口：`reflect(original_text, previous_expanded_text, verification, abbreviation_candidates)`
> 衔接：第 12 篇 verify 判 `overall_valid=false` 时，不是直接报错结束，而是调这里——把**失败原因**喂回 LLM，让它针对错误重新生成一版扩写。修正版再回到标准化+校验（这条循环主轴在第 14 篇）。这是把 pipeline 变成 Agent 的关键一环。

## 核心速记
> 1. **Agent 的灵魂**：普通 pipeline 出错就结束；这里"发现错误 → 分析错误 → 重新生成"形成闭环。这是 Retrieval+Verification+**Reflection** 里的 R，本篇骨架。
> 2. **不是"重猜一次"，是带着反馈重做**：把 verification 的错误报告原样喂回 LLM，告诉它"哪错了、为什么错"，再让它改。
> 3. **Candidate-Constrained Reflection**：反思也受候选约束（从候选里选、有候选别发明），防止它修一个错又冒一个新幻觉。
> 次要（trivia）：`temperature=0`、markdown 清洗、`parse_error` 兜底返回上次扩写——扫一眼。

## 这一段在解决什么

大白话：**校验说"这次扩写不行"，反思就拿着"哪不行"的报告，重写一版。**

```text
verify 判失败：{LMN→lower motor neuron, is_valid:false, reason:"上下文不足"}
   ↓ reflect（把上面这份报告 + 原句 + 候选 喂回 LLM）
{ revised_expanded_text:"The patient was evaluated for LMN.",   ← 撤回扩写
  revised_mappings:[], reason:"上下文不足以支持 LMN 扩写，保留原文" }
```

## 核心1 · 为什么这一步让项目"从 pipeline 变成 Agent"（骨架，必背）

对比两种系统：

```text
普通 NLP pipeline：  输入 → LLM → 输出   （错了就错了，结束）
本项目：             输入 → 生成 → 校验 → 错了→反思→重做→再校验  （闭环自纠错）
```

**关键在于"闭环"**：系统不只产出结果，还能**评估自己的结果、发现错误、再修正**。这正好对应 Agent 的基本循环：

```text
Action(扩写) → Observation(校验结果) → Reflection(反思) → Action(重做) → ...
```

文档里专门列了这个对应关系——**Verify→Reflect→Retry 就是一个轻量级 Agent Workflow 的雏形**。面试 Agent 岗位，这是你项目里最该突出的一环：**它不是"调一次 LLM 拿答案"，而是有"自我评估—自我修正"的 agentic 循环。**

## 核心2 · 带反馈重做 ≠ 盲目重试（设计点，必讲）

最朴素的"重试"是：失败了，把同样的输入再喂一次 LLM，期待它这次蒙对。**这没用**——同样输入大概率同样输出。

reflect 的做法是把 **verification 的错误报告**也喂进去：

```python
def reflect(self, original_text, previous_expanded_text, verification, abbreviation_candidates):
    prompt = f"""
       Original clinical text: {original_text}              # 原句
       Previous expanded clinical text: {previous_expanded_text}  # 上次扩错的结果
       Verification feedback: {json.dumps(verification)}    # ★ 哪错了、为什么错
       Available abbreviation candidates: {json.dumps(abbreviation_candidates)}  # 能选的候选
       ...修正后返回 revised_expanded_text / revised_mappings / reason
    """
```

**核心是那份 `verification feedback`**——它带着上一篇 verifier 产出的 `issues`（如 `negation_changed`、`ambiguous_abbreviation`）和 `reason`。LLM 看着"你上次错在把否定丢了"去改，是**有的放矢的修正**，不是重猜。

> 一句话：reflect 让 LLM **看着自己的错题和批改意见重做**，而不是重新做一张白卷。

## 核心3 · Candidate-Constrained Reflection：修错别又冒新错（防幻觉）

反思有个风险：让 LLM"重新想"，它可能**修掉旧错、又幻觉出新错**（比如把 `MS` 改成根本不存在的 `muscular syndrome`）。prompt 用规则堵：

```text
Rule 7: 修正 mapping 时，尽量从 available candidates 里选。
Rule 8: 如果某缩写已有候选，不要发明新的 expansion。
Rule 3: 保留否定、不确定、严重程度、时间。
```

**意思**：反思不是放飞自由生成，而是**仍然约束在候选集里**（回扣第 11 篇的"受约束生成"）。这样反思只在"已知候选"里换个更合理的选择，不会越界乱编。

## 数据快照：一轮反思

```text
【入】
  original_text:          "The patient has MS with a diastolic murmur."
  previous_expanded_text: "...multiple sclerosis..."          ← 上次扩错了
  verification:           {issues:["ambiguous_abbreviation"], reason:"杂音提示心脏病"}
  candidates:             [MS→multiple sclerosis, MS→mitral stenosis]

【出】
  { revised_expanded_text: "...mitral stenosis...",           ← 改对了
    revised_mappings: [{MS→mitral stenosis}],
    reason: "diastolic murmur 指向心脏疾病，应为 mitral stenosis" }
```

修正版再回到第 14 篇主轴：重新标准化 → 重新 verify。

## 会被追问 / 诚实局限（★主动说）

- **反思也是 LLM，也会失败/再幻觉**：所以反思后**绝不无脑相信**，要再过一遍 verify。reflect → verify → 还不行 → 再 reflect，靠重试上限兜底（第 14 篇）。
  → 面试这么说："反思不是终点——它的产出还要再校验，形成 reflect→verify 的循环，最多重试有限次。我不假设反思一定改对。"
- **错误会"传染"**：reflect 吃的是 verification 的报告，但 verification 本身也是 LLM、可能判错（同源盲区，回扣第 12 篇）。如果 verifier 判错了原因，reflect 就被带偏，越改越歪。
  → "校验和反思共享同一个模型的盲区，verifier 误判会污染 reflect。理想是 cross-model，或给 reflect 也加确定性约束。"
- **整句重写，可能误伤对的部分**：reflect 重写**整个** expanded_text，不是只改出错的那个缩写。多缩写句子里，本来对的可能被一起改坏（回扣第 12 篇 all 偏严 + 整句重来）。
  → "更好的是按 mapping 粒度只修出错的那个，锁定已通过的。"
- **`parse_error` 兜底返回上次扩写**：JSON 解析失败时，原样返回 `previous_expanded_text`——这一轮反思**白做**，下一轮 verify 还是同样结果，可能空转到次数耗尽。
  → "解析失败的兜底是'不改'，安全但浪费一轮，可以加结构化输出降低解析失败。"
- **Candidate-Constrained 仍是 prompt 软约束**（rule 7/8），LLM 不保证遵守（又一个该硬约束的点）。
- **没有跨 case 学习**：每次反思独立，不积累"这类错误以前怎么修好的"经验。成本上每轮重试都多一次 reflect+verify 的 LLM 调用。

## 面试怎么说

**合格版（30 秒）**：
> 校验不通过时调反思服务：把原句、上次扩错的结果、verification 的错误报告、候选集一起喂回 LLM，让它针对错误重写一版。关键是带着反馈重做、不是盲目重试，而且反思仍约束在候选里防止再幻觉。修正版再回去重新校验，形成闭环。

**优秀版（1 分钟）**：
> 这是项目从 pipeline 进化成 Agent 的关键——普通系统出错就结束，我这里有"生成→校验→反思→重做→再校验"的自纠错闭环，对应 Action-Observation-Reflection 的 agentic 循环。反思的核心设计有两点：一是带反馈重做，把 verifier 的 issues 和 reason 喂回去，让 LLM 看着错题和批改意见改，而不是重猜；二是 candidate-constrained，反思仍约束在候选集里，防止它修一个错又冒一个新幻觉。诚实说几个局限：反思也是 LLM，产出还得再校验、不能无脑信；它吃的是 verifier 的报告，跟 verifier 共享同源盲区，会被误判带偏；而且是整句重写，可能误伤本来对的映射，更好是按 mapping 粒度修。这些是我清楚的改进方向。

## 易错点 / 面试问答

**Q：反思和"重试"有什么区别？** A：重试是同样输入再喂一次，大概率同样结果。反思是把"哪错了、为什么错"的校验报告也喂回去，让 LLM 有的放矢地改——带反馈重做。

**Q：为什么说这一步让项目像 Agent？** A：因为它形成了"生成→自我评估→自我修正→再生成"的闭环，对应 Agent 的 Action-Observation-Reflection 循环，而不是一次性问答。

**Q：反思会不会修一个错冒一个新错？** A：会，所以加了 candidate-constrained——反思仍要从候选里选、有候选别发明；而且反思产出还要再过 verify，不无脑相信。

**Q：反思一定能改对吗？** A：不一定。它也是 LLM、也会错，还可能被 verifier 的误判带偏。所以靠 reflect→verify 循环 + 有限重试次数兜底（第 14 篇）。

**Q：反思失败（JSON 解析不了）怎么办？** A：兜底原样返回上次扩写，这轮等于白做，安全但浪费一轮。可用结构化输出降低解析失败。

## 一句话总结

> ABBRReflectionService 是把 pipeline 变 Agent 的关键：verify 失败时，把原句+上次扩写+**校验错误报告**+候选集喂回 LLM，让它带着反馈、约束在候选里重写一版（不是盲目重猜、不放飞幻觉）。修正版再回去重新校验，形成 Verify→Reflect→Retry 闭环（Agent 雏形）。局限是反思也是 LLM 会再错、与 verifier 同源盲区会被带偏、整句重写可能误伤对的映射、解析失败白做一轮——可用 cross-model/粒度化修正/硬约束/结构化输出改进。
