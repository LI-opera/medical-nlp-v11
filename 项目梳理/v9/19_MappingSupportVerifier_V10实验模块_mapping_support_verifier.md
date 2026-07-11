# MappingSupportVerifier（V10 实验模块：专治低上下文过度扩写，但被 over-abstention 反噬）

> 文件：`backend/services/mapping_support_verifier.py`（119 行）
> 入口：`verify(text, abbreviation, expansion) -> MappingSupportResult`
> 衔接：这是为解决 benchmark 暴露的 **low_context 仅 20%**（第 17 篇）而做的 V10 实验模块。**但它在 V9 Stable 主链路被注释禁用了**（第 14 篇）——因为它带来了新问题。这一篇讲的是一个"实验失败但有价值"的故事。

## 核心速记
> 1. **专攻一件事**：判"当前这句话**有没有足够上下文**支持这个 `缩写→扩写`"。不是判医学上存不存在,而是判"这句话撑不撑得起"。
> 2. **核心策略 "be conservative"**：上下文不足就判 `supported=false`——专治"看到候选就扩"的低上下文过度扩写。
> 3. **实验结局**：太保守 → **over-abstention**(把 `CP→chest pain` 这种本该扩的也拒了),net 准确率没提升,所以**回退 V9、保留为实验分支**。这个取舍是本篇的灵魂。
> 次要(trivia):唯一用 Pydantic 输出模型(`MappingSupportResult`)、temperature=0、parse_error→supported=False——扫一眼。

## 这一段在解决什么

大白话:**它只问一个问题——"就这句话给的信息,够不够支持把这个缩写扩成这个全称?"不够就拒。**

```text
"The patient was evaluated for LMN."   LMN→lower motor neuron?
   ↓ verify
{ supported: false, confidence: 0.3,
  reason: "上下文只说'evaluated for LMN',不足以支撑 lower motor neuron 这个扩写" }
```

它专门盯**低上下文过度扩写**:LMN、QRS 这种,候选库里有、医学上也成立,但**这句话根本没给足线索**,不该硬扩。

## 核心1 · 它和前面的校验有什么不一样（骨架）

前面已经有 coverage(第 10 篇)和 verifier(第 12 篇)了,为什么还要它?因为它**专攻一个被忽略的维度:上下文支持度**。

```text
coverage:  候选集里有没有"上下文说得通"的 → 但它倾向于"常见义就放行"(Rule 4)
verifier:  扩写后保意吗、SNOMED 支持吗 → 偏重"扩写本身合不合理"
本模块:    这句话的上下文，到底够不够撑起这个扩写 → 专门、激进地查这一件事
```

它的 system prompt 反复强调两点:
- **"Your task is NOT to decide whether an expansion is medically valid in general"**——不管医学上成不成立。
- **"You must be conservative"**——上下文不足,哪怕这扩写很常见,也判 false。

**设计意图**:给系统装上"**上下文不够就别扩**"的刹车,补上 coverage/verifier 都没专门管的那个洞(低上下文)。

## 核心2 · 实验结局:治好了一个病，引发了另一个病（故事,必讲）

这是面试最该讲的部分——一个**有数据、有取舍的实验故事**:

```text
V9（不带它）：    low_context 20%（过度扩写多）   其他类基本满分   总体~92%
V10（加上它）：   low_context 改善（LMN/QRS 能拒了）
                 但新问题：over-abstention —— CP→chest pain 这种本该扩的也被拒
                 → 正常 case 掉分，net 准确率没涨甚至降
结论：回退 V9 Stable，本模块保留为 Experimental Branch
```

**为什么会 over-abstention**:它被设计得"过于保守"——`be conservative` 没有程度调节,结果"宁可错杀"。低上下文是压住了,但把一批**上下文其实够**的正常扩写也误判成"不支持"。

**这个故事的价值(面试金句)**:
> "我做了一个实验模块想解决低上下文过度扩写,它确实能识别 LMN 这类该拒的,但引入了 over-abstention,把 CP 这种该扩的也拒了。基于 benchmark 对比,net 准确率没有提升,所以我没把它上主链路,而是保留为实验分支。**这说明不是功能越多越好——加一个模块要看它对整体指标的净影响,不能只看它解决的那个问题。**"

这比"我加了个上下文校验功能"高一个层次——体现**用数据做取舍、知道何时不上线**的工程判断力。

## 核心3 · 实现细节（真实数据）

```python
class MappingSupportResult(BaseModel):       # 唯一用 Pydantic 结构化输出的服务
    supported: bool
    confidence: float
    reason: str

def verify(self, text, abbreviation, expansion):
    # prompt = system(be conservative) + text + abbr + expansion
    # 问：这句话的上下文够不够支持这个映射？
    response = self.llm.invoke(prompt)
    ... 解析 JSON → MappingSupportResult
    except: return MappingSupportResult(supported=False, ...)  # 解析失败也判 false（保守）
```

它在 `ABBRService._filter_mappings_by_context_support` 里被调用——**单候选缩写直接通过,多候选才调它**(回扣第 10 篇"单候选跳过"的思路)。但那个过滤方法在 `expand_verify_with_retry` 里整段被注释(第 14 篇),所以**当前不跑**。

## 数据快照：治好的 vs 误伤的

```text
✅ 治好（该拒的拒了）:
   "evaluated for LMN" → LMN→lower motor neuron → supported=false（上下文不足）

❌ 误伤（over-abstention，该扩的也拒了）:
   "The patient denies CP." → CP→chest pain → supported=false（其实上下文够，被错杀）
```

## 会被追问 / 诚实局限（★主动说）

- **over-abstention 是它的致命伤,也是被禁用的直接原因**:过于保守,把上下文其实足够的正常扩写也拒了。
  → 面试这么说:"它最大的问题是 over-abstention——保守过头。低上下文是压住了,但误伤了正常 case,net 指标没赢,所以我基于 benchmark 决定不上线。"
- **保守程度不可控**:`be conservative` 是 prompt 软约束,没有 confidence 阈值之类的旋钮去调"多保守"。
  → "改进方向是给它配 confidence 阈值 + 候选先验,让'拒不拒'可调,而不是一刀切保守。"(回扣文档 V10 改进方向)
- **又一次 LLM 调用 + 职责部分重叠**:它和 coverage、verifier 都在判"上下文支持",三个 LLM 判断有冗余,成本又叠加。
  → "三个校验维度有重叠,理想是合并成一个统一的、带可调保守度的校验,而不是各调一次 LLM。"
- **还是 LLM 判断**:同样有同源盲区、confidence 自报等老问题。
- **当前是禁用的死代码状态**:但这是**有意保留**为实验分支(供未来 LangGraph 上下文研究),不是忘了删——这点要讲清,否则像烂尾。

## 面试怎么说

**合格版（30 秒）**：
> MappingSupportVerifier 是我为解决低上下文过度扩写做的实验模块,专门判"这句话的上下文够不够支持这个扩写",设计上很保守、不够就拒。它确实能识别 LMN 这类该拒的,但引入了 over-abstention——把 CP 这种该扩的也拒了。基于 benchmark,net 准确率没提升,所以回退 V9、保留为实验分支。

**优秀版（1 分钟）**：
> Benchmark 暴露低上下文只有 20%——系统倾向于"看到候选就扩"。我做了 MappingSupportVerifier 想补这个洞:它专攻一个维度,就是"当前文本的上下文够不够支撑这个映射",prompt 明确要它保守、不管医学上成不成立、上下文不足就拒。实验证明它能识别 LMN、QRS 这类低上下文误扩。但它过于保守,引发 over-abstention,把 CP→chest pain 这种本该扩的也拒了,net 准确率没赢。所以我没上主链路,保留为实验分支。这件事让我体会到——加一个模块不能只看它解决的问题,要看对整体指标的净影响;下一步应该给它配可调的 confidence 阈值和候选先验,而不是一刀切保守。

## 易错点 / 面试问答

**Q：它和 coverage、verifier 有什么不同？** A：它专攻"上下文支持度"这一个维度,且刻意保守。coverage 偏"候选够不够"、verifier 偏"扩写合不合理/保意",它专门查"这句话撑不撑得起这个扩写"。

**Q：它为什么没用在主链路？** A：over-abstention——太保守,低上下文是压住了,但把正常该扩的也拒了,benchmark 净准确率没提升,所以回退 V9、保留为实验分支。

**Q：over-abstention 是什么？** A：过度弃权——本该扩写的也判"不支持"而拒掉。是把刹车踩太狠的副作用。

**Q：怎么改进它？** A：给"保守程度"装旋钮——用 confidence 阈值 + 候选先验联合决策,而不是一刀切保守;长远可与 coverage/verifier 合并成统一校验。

**Q：留着不删是烂尾吗？** A：不是。有意保留为实验分支,供未来上下文支持研究(如 LangGraph 版本),并记录了 over-abstention 这个负面结果——失败的实验也是有价值的资产。

## 一句话总结

> MappingSupportVerifier 是 V10 实验模块:专判"当前文本上下文够不够支持某个缩写扩写",刻意保守、不够就拒,为治低上下文过度扩写(LMN/QRS)而生。实验证明能识别该拒的,但引发 over-abstention(误伤 CP 这种该扩的),net 准确率没提升,故**回退 V9、保留为实验分支**。它的价值在于体现"用 benchmark 做取舍、知道何时不上线"的判断力。局限是保守不可控、与 coverage/verifier 职责重叠、仍是 LLM 判断——改进方向是可调阈值 + 候选先验。
