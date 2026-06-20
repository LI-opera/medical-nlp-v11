# ABBVerifier（双层校验：让 LLM 当裁判，查"保意 + 映射对不对"）

> 文件：`backend/services/abbr_verifier.py`（232 行）
> 入口：`verify_mappings(original_text, expanded_text, mapping_standardizations)`（89–209，主路用的就是它）
> 衔接：第 11 篇扩写产出 `expanded_text + mappings`，标准化产出每个 expansion 的 SNOMED 候选。Verifier 接住这些，判一个 `overall_valid`——通过就返回，不通过就交给第 13 篇反思重试。这是 Agent 的"自检"环节。

### 先把两层彻底分开



```text
第一层：LLM 当裁判，输出一堆"小判断"          ← 这是"判断角度"
   ├─ 句子级：整句保意吗？           → sentence_validity.is_valid
   └─ 映射级：每个缩写各自判（逐个）
        ├─ context_supported   上下文支持吗？
        ├─ snomed_supported    SNOMED 支持吗？
        └─ is_valid            这个 mapping 综合算对吗？

第二层：代码用一个公式，把上面的小判断汇总成 overall_valid   ← 这是"汇总规则"，不是判断
   overall_valid = 句子有效 AND 有mapping AND 所有mapping都有效
```

#### 第一层:LLM 到底判了哪几样(判断角度)

真正"判对错"的只有**两个维度**(不是三个):

1. **句子级——保意**:LLM 对比 `原句` 和 `扩写句`,看有没有改变意思(尤其否定)。
2. **映射级——每个缩写两问**:`context_supported`(上下文支持吗)+ `snomed_supported`(SNOMED 支持吗),综合出这个 mapping 的 `is_valid`。

#### 第二层:代码怎么汇总成 overall_valid

LLM 给完上面那堆 True/False,代码用一个公式收口:

python

```python
overall_valid = (
    句子.is_valid          # 整句保意了吗
    and len(mappings) > 0  # 有没有扩出至少一个（防"啥也没扩"）
    and all(每个 mapping.is_valid)   # 是不是每个缩写都扩对了
)
```

- "有 mapping"=防空转(一个都没扩不算成功)。
- "每个都对"=医疗零容忍,一个扩错就整体重做。

**这两条是"怎么数票"的规则,不是"判断角度"。** LLM 负责给每张票(每个 is_valid),代码负责数票得出最终结论。



## 核心速记
> 1. **LLM-as-judge**：生成用 LLM，校验**也**用 LLM，但是**独立的一次调用、独立 prompt**。核心理念"不要直接相信 LLM 的生成结果，加一道独立审查"。本篇骨架。
> 2. **双层校验**：① 句子级（扩写后保不保原意，尤其否定）；② 映射级（每个缩写→扩写对不对、SNOMED 支不支持）。prompt 明确要求"两个判断分开、不许合并"。
> 3. **`overall_valid` = 三个与条件**：句子有效 AND 有 mapping（非空）AND 每个 mapping 都有效。任一不满足就失败 → 触发重试。
> 次要（trivia）：还有个旧 `verify()` 方法已不用、markdown 清洗、`parse_error` 兜底 `overall_valid=False`——扫一眼。

## 这一段在解决什么

大白话：**扩写做完了，找"另一个 LLM 裁判"从两个角度挑错：整句有没有被改变原意？每个缩写到底扩对了没？**

```text
原句:     "The patient denies CP."
扩写后:   "The patient denies chest pain."
mappings: [CP→chest pain] + 各自的 SNOMED 候选
   ↓ verify_mappings
{ sentence_validity:{is_valid:true, ...},           # 否定保住了 ✅
  mapping_validations:[{CP→chest pain, is_valid:true, ...}],
  overall_valid: true }                              # 整体通过
```

## 核心1 · LLM-as-judge：为什么生成完还要再用一次 LLM（骨架，必背）

直觉上会问：扩写已经是 LLM 做的，再用 LLM 检查不是"自己批改自己作业"吗？

关键在于**这是一次独立的调用、独立的 prompt、独立的任务**：
- 生成时，LLM 的任务是"把缩写扩开"，注意力在"造出通顺结果"。
- 校验时，LLM 的任务变成"挑错"——**专门找"是不是改了原意、SNOMED 支不支持"**，是一种对抗性的重新审视。

把"生成"和"判断"拆成两次不同任务，能 catch 掉生成时的疏忽。这就是整个项目的总纲——**"不要直接相信 LLM 的输出，加一道验证"**（Retrieval + Verification + Reflection 里的 V）。

> 当然它有个根本局限：裁判也是 LLM，还可能是**同一个模型**，存在同源盲区（见诚实局限）。但"加一道独立审查"在工程上确实能挡掉相当一部分错误。

## 核心2 · 双层校验：句子级 ⊥ 映射级（设计点，必讲）

prompt 反复强调："**Evaluate sentence_validity separately from mapping_validations. Do not merge the two judgments.**" 为什么要拆成两个正交维度：

**① 句子级（sentence_validity）——保意检查**
- 扩写后是不是**只**扩了缩写，没加/删/改医学含义？
- 重点：**否定、不确定、严重程度、时间**有没有被保住？
- 经典反例：`denies CP` → `denies chest pain`（对）vs `has chest pain`（错，否定丢了）。

**② 映射级（mapping_validations）——逐个缩写检查**
对每个 `abbreviation→expansion` 单独判：
- `context_supported`：上下文支不支持这个意思？
- `snomed_supported`：SNOMED 候选支不支持？（注意 prompt 说"SNOMED candidates are supporting evidence, not final truth"——是参考不是铁证）
- 综合给 `is_valid`。

**为什么分开**：两个维度互相独立——
- 句子可能整体保意，但某个 mapping 存疑；
- 某个 mapping 本身合理，但句子级把别处措辞改坏了。
合在一起判会互相污染，分开判更精确，也方便定位错在哪一层。

## 核心3 · overall_valid 的三个与条件（实现 + 真实数据）

```python
overall_valid = (
    sentence_validity.get("is_valid") is True          # ① 整句保意
    and len(mapping_validations) > 0                   # ② 至少有一个 mapping（不能空）
    and all(item.get("is_valid") is True               # ③ 每个 mapping 都有效
            for item in mapping_validations)
)
```

三个条件缺一不可，任一不满足 → `overall_valid=False` → 触发反思重试（第 13 篇）。

- 条件 ② `len > 0` 很妙：**防止"什么都没扩还判通过"**——空 mapping 不算成功。
- 条件 ③ `all(...)`：**只要一个 mapping 错，整体就失败**（偏严，见局限）。

返回结构：

```text
{ sentence_validity: {is_valid, confidence, reason, issues:[...]},
  mapping_validations: [{abbreviation, expansion, context_supported, snomed_supported,
                         is_valid, confidence, reason, issues:[...]}],
  overall_valid: bool }
```

issue 标签很细：`negation_changed`、`added_information`、`unsupported_by_snomed`、`ambiguous_abbreviation` 等——方便后面错误分析归类（回扣评估系统）。

## 数据快照：一个失败案例

```text
原句:   "The patient was evaluated for LMN."   （低上下文）
扩写后: "The patient was evaluated for lower motor neuron."
   ↓ verify_mappings
{ sentence_validity:{is_valid:false, reason:"上下文不足以支持该扩写",
                     issues:["changed_meaning"]},
  mapping_validations:[{LMN→lower motor neuron, context_supported:false,
                        is_valid:false, issues:["ambiguous_abbreviation"]}],
  overall_valid:false }   → 触发反思重试
```

## 会被追问 / 诚实局限（★主动说）

- **裁判也是 LLM，且可能是同一个模型 → 同源盲区**：生成和校验都用 deepseek-chat，**同一个模型的盲区在生成和校验时往往一致**——生成时想错的地方，校验时可能照样判对。
  → 面试这么说："LLM-as-judge 有同源偏差风险，理想做法是用**不同的模型**当裁判（cross-model verification），或加入确定性规则校验作为补充，降低'自己批自己作业'的盲区。" 这条很能体现你懂 LLM 评判的局限。
- **`overall_valid` 用 `all(...)` 偏严**：一个 mapping 出问题就整体失败、触发重试。对多缩写句子，可能因为一个小瑕疵反复重试、甚至本来对的也被拖下水。
  → "可以改成按 mapping 粒度只重试出问题的那个，而不是整句推倒重来。"
- **`mapping_validations` 数量等于输入"靠 LLM 自觉**：prompt 要求数量一致，但**没有代码校验**。如果 LLM 少返回一个，`all(...)` 会在不完整的列表上判断，可能误判通过。
  → "应该在代码层断言返回数量等于输入数量，不一致直接判失败或重试。"
- **`snomed_supported` 也是 LLM 主观看候选列表判的**，没有硬匹配（比如概念 ID 比对），candidates 只是"参考证据"。
- **旧 `verify()` 方法是死代码**：文件里还有个早期的单句校验 `verify()`（1–87 行），主路已不用，留着是冗余。
- **成本**：又一次 LLM 调用，且**每轮重试都要再调一次**校验。`confidence` 同样自报、参考为主。

## 面试怎么说

**合格版（30 秒）**：
> 扩写完用 ABBVerifier 做 LLM-as-judge 校验，双层：句子级查扩写后有没有改变原意（尤其否定），映射级查每个缩写扩得对不对、SNOMED 支不支持。综合成 overall_valid——句子有效、有 mapping、每个 mapping 都有效，三条都满足才算通过，否则触发反思重试。

**优秀版（1 分钟）**：
> 这是 Agent 的自检环节，体现"不要直接相信 LLM 生成"——我用一次独立调用、独立 prompt 让 LLM 当裁判挑错，从生成的'造结果'切换成'找错'。校验我刻意拆成两个正交维度：句子级保意（重点是否定、不确定这些不能丢）和映射级逐个缩写的上下文/SNOMED 支持，prompt 明确要求两者分开判，因为句子整体可能对但某个映射存疑，反之亦然。overall_valid 是三个与条件，其中'至少有一个 mapping'能防止空扩写蒙混通过。诚实说几个局限：裁判和生成是同一个模型，有同源盲区，理想是 cross-model 校验或加规则兜底；overall_valid 用 all 偏严，一个错就整句重来；还有 mapping 数量一致只靠 prompt、没代码校验。这些都是我清楚的改进点。

## 易错点 / 面试问答

**Q：扩写是 LLM，校验又是 LLM，不是自己批自己？** A：是独立的一次调用、独立 prompt、对抗性任务——从"造结果"切到"挑错"，能 catch 生成时的疏忽。但确实有同源盲区，理想是换个模型当裁判。

**Q：为什么校验要分句子级和映射级？** A：两个维度正交——句子整体可能保意但某 mapping 存疑，某 mapping 合理但句子措辞被改坏。分开判更精确，也方便定位错在哪层。

**Q：overall_valid 怎么算？** A：句子有效 AND 至少一个 mapping AND 每个 mapping 都有效。三条与。`len>0` 防止空扩写蒙混，`all` 保证全部映射都过。

**Q：SNOMED 在校验里起什么作用？** A：作为"支持证据"参考，prompt 明确说不是最终真理。snomed_supported 也是 LLM 看候选主观判，没有硬比对概念 ID。

**Q：这套校验最大风险是什么？** A：裁判也是 LLM、还是同一个模型，存在同源盲区——生成时的错误校验时可能照样放过。降低办法是 cross-model 校验或加确定性规则。

## 一句话总结

> ABBVerifier 是 Agent 的自检环节，用 LLM-as-judge 做双层校验：句子级查保意（尤其否定），映射级逐个查缩写的上下文与 SNOMED 支持，综合成 `overall_valid`（句子有效 AND 有 mapping AND 全部 mapping 有效，三条与），不通过即触发反思重试。体现"不要直接相信 LLM、加独立审查"。局限是同源盲区（裁判=生成同模型）、all 判定偏严、mapping 数量不做代码校验、旧 verify 死代码——可用 cross-model 校验/规则兜底/粒度化重试改进。
