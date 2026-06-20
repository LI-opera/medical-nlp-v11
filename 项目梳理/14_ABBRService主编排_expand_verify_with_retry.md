# ABBRService 主编排（装配图：把所有零件串成一条主轴）

> 文件：`backend/services/abbr_service.py`
> 入口：`expand_verify_with_retry(text, max_retries=2)`（313–512）+ `__init__`（31–61）
> 衔接：**这是整个项目的"主轴/装配图"**。前面 1~13 篇都是零件，这一篇把它们按真实运行顺序串起来：扩写 → 标准化 → SNOMED 检索 → 校验 → 反思 → 重试。读完这篇，前面所有零件各归各位。

## 核心速记
> 1. **它是装配图**：本身几乎不写新逻辑，只负责"按顺序调度所有子服务"。理解它就理解了整条主流程。
> 2. **Verify→Reflect→Retry 循环**：扩写一次 → 进循环{ 标准化+检索 → 校验 → 不过则反思 → 再来 }，最多 1 正常 + 2 反思 = 3 轮。
> 3. **两个关键设计**：① coverage 全失败时**早停**（不空转重试）；② 每轮结果全存进 `attempts`（全程留痕，便于调试/评估）。
> 次要（trivia）：`__init__` 复用所有子服务、V9 把 MappingSupportVerifier 过滤注释掉了——扫一眼。

## 这一段在解决什么

大白话：**一句临床文本进来，这里指挥所有零件按顺序干活，最后吐出"扩写好没有 + 扩成了啥"。**

它是你之前一直觉得"连不起来"的那根线——零件你都见过了，这里告诉你它们**谁先谁后、谁喂给谁**。

## 核心1 · `__init__`：开工前把所有零件备齐复用（回扣懒加载）

```python
def __init__(self):
    self.llm = ChatDeepSeek(temperature=0, ...)        # 扩写用的 LLM
    self.standardizer = MedicalStandardizer()           # 第7篇（内含 NER+检索）
    self.retriever = MedicalRetriever()                 # 第5篇
    self.verifier = ABBVerifier()                       # 第12篇
    self.reflector = ABBRReflectionService()            # 第13篇
    self.candidate_retriever = ABBRCandidateRetriever() # 第8篇
    self.fallback_retriever = ABBRCandidateFallbackRetriever()  # 第9篇
    self.coverage_evaluator = ABBRCandidateCoverageEvaluator()  # 第10篇
    self.mapping_support_verifier = MappingSupportVerifier()    # 第19篇（V9 禁用）
```

所有子服务在 `__init__` 建一次、整个生命周期复用（回扣第 15 篇懒加载、第 4 篇对象级复用）。**这一个 `__init__` 就把全项目的零件清单列全了**——你可以拿它当目录。

## 核心2 · `expand_verify_with_retry`：完整主轴顺序（骨架，必背）

这就是那张装配图。**对着这个顺序，前面所有零件归位**：

```text
1. current = simple_llm_expansion(text)        ← 第11篇：gate→候选→fallback→coverage→LLM扩写
   拿到：expanded_text + mappings + abbreviation_candidates
   （V9 Stable：这里本可以再过 MappingSupportVerifier 过滤，但代码注释掉了）

2. for attempt in range(max_retries+1):          ← 循环最多 3 轮（1 正常 + 2 反思）

   a. valid_mappings = 只保留有 expansion 的 mapping
   b. ★ 早停：valid_mappings 为空 → stop_reason="coverage_failed_no_valid_expansion"
              直接失败返回，不进循环空转          ← 关键设计
   c. standardize(expanded_text)                 ← 第7篇：整句 NER+检索（存档，不喂 verifier）
   d. 对每个 valid_mapping：
        retriever.retrieve(expansion, top_k=10, score≥0.6) → 取前3   ← 第5篇 SNOMED 检索
        攒成 mapping_standardizations
   e. verification = verifier.verify_mappings(原句, expanded_text, mapping_standardizations)  ← 第12篇
   f. attempts.append(本轮所有中间结果)          ← 全程留痕
   g. overall_valid==True  → 成功返回 ✅
   h. attempt >= max_retries → 失败返回（次数用完）
   i. reflection = reflector.reflect(...)        ← 第13篇：带反馈重写
        current_expanded_text = revised_expanded_text
        current_mappings = revised_mappings
        → 回到 2，下一轮重新 c→d→e
```

**这就是你之前缺的那根主轴。** 注意几个你之前困惑的点在这里都对上了：
- "SNOMED 检索在哪做的"→ 步骤 d，对每个 expansion 直接检索（不靠 NER）。
- "verify 的候选哪来的"→ 步骤 d 攒的 `mapping_standardizations`。
- "整句 standardize 算了没用"→ 步骤 c 算了、存档，但步骤 e 的 verify 用的是 d，不是 c。

## 核心3 · 两个关键设计（面试加分点）

**① coverage 全失败 → 早停，不空转**

```python
if not valid_mappings:
    return {... "stop_reason": "coverage_failed_no_valid_expansion", "success": False}
```

如果一个有效扩写都没有（所有缩写都被 coverage 否了），**反思也没候选可修**——再重试纯属空转浪费 LLM。所以直接失败返回。这是"知道什么时候放弃"的工程判断。

**② `attempts` 全程留痕（traceability）**

每一轮的 `expanded_text`、候选、标准化、校验结果都存进 `attempts` 列表。好处：能完整复盘"第一次扩成啥→为什么失败→反思改了啥→第二次又如何"。这对调试和后面的 Benchmark/Error Analysis（第 17/18 篇）至关重要——**失败了能定位是哪一轮、哪一步出的问题**。

## 数据快照：一个需要反思的完整请求

```text
输入: "The patient has MS with a diastolic murmur."  max_retries=2

① 扩写: MS→multiple sclerosis（错了），expanded="...multiple sclerosis..."
② 轮1: 检索 multiple sclerosis 的 SNOMED → verify
       → overall_valid=false（issues: ambiguous_abbreviation, 杂音提示心脏病）
       → reflect: 改成 MS→mitral stenosis
③ 轮2: expanded="...mitral stenosis..." → 检索 → verify
       → overall_valid=true ✅ → 成功返回
返回: { success:true, final_expanded_text:"...mitral stenosis...",
        attempts:[轮1记录, 轮2记录], final_result:轮2 }
```

## 会被追问 / 诚实局限（★主动说）

- **多轮 = LLM 调用叠加，慢且贵**：一次请求里，扩写阶段就有 coverage（可能还有 fallback）+ 扩写；之后每轮再 verify + reflect。最坏 3 轮下来好几次 LLM 调用。
  → 面试这么说："这是用延迟和成本换可靠性。优化方向：单义缩写跳过 coverage、按 mapping 粒度局部重试而不是整句重来、缓存高频结果。"
- **检索+取前3 的代码与 MedicalStandardizer 重复**（回扣第 7 篇 DRY）：步骤 d 和 standardizer 内部几乎一字不差，该抽公共函数。
- **整句 standardize（步骤 c）算了但没喂 verifier**（回扣第 7 篇）：冗余计算，verify 实际用的是步骤 d。
- **整句重来、粒度粗**（回扣第 12/13 篇）：reflect 重写整句，本来对的映射可能被改坏；overall_valid 用 all 偏严，一个错就整轮重做。
- **V9 把 MappingSupportVerifier 过滤注释掉了**：`__init__` 里初始化了，但 `expand_verify_with_retry` 里的过滤调用是注释状态（第 348–360 行）。所以低上下文过度扩写问题在 V9 没解决（回扣文档 V9/V10）。
  → "我有意回退到 V9 Stable——MappingSupportVerifier 实验版会 over-abstention，把对的也拒了，所以主链路禁用、保留为实验分支。这是基于 benchmark 的取舍。"
- **max_retries 默认 2、写死调用层**：调用方改不了（回扣第 15 篇）。

## 面试怎么说

**合格版（30 秒）**：
> ABBRService 是主编排：`__init__` 把所有子服务建好复用，`expand_verify_with_retry` 串起主流程——先扩写，然后进循环：标准化+对每个 expansion 检索 SNOMED → 校验 → 不通过就反思重写 → 再来一轮，最多 1 正常加 2 反思。coverage 全失败就早停不空转，每轮结果全留痕便于复盘。

**优秀版（1 分钟，这其实就是整个项目的架构级回答）**：
> 主轴是 expand_verify_with_retry。请求进来先做受约束扩写（gate→候选→fallback→coverage→LLM）；然后进重试循环：对每个扩写词检索 SNOMED 攒证据，交给 verifier 做双层校验，通过就返回，不通过且没超次就调 reflect 带着错误报告重写，再回到检索校验。最多 1 正常加 2 反思。我做了两个工程判断：一是 coverage 全失败时早停，因为反思也没候选可修，空转是浪费；二是把每一轮的扩写、检索、校验都存进 attempts 全程留痕，这对调试和后面的 benchmark、错误归因特别关键。当前是 V9 Stable——我把实验性的 MappingSupportVerifier 过滤注释掉了，因为它会 over-abstention。诚实说局限：多轮 LLM 调用偏慢偏贵、整句重写粒度粗、检索逻辑和标准化器有重复——都是我清楚的优化方向。

## 易错点 / 面试问答

**Q：整个主流程顺序是什么？** A：扩写一次 → 循环{ 标准化+逐个 expansion 检索 SNOMED → 校验 → 不过则反思重写 } → 通过或超次退出。最多 1 正常 + 2 反思 = 3 轮。

**Q：SNOMED 检索在主流程哪一步？** A：循环里，对每个有效 expansion 直接 retrieve（不经 NER），攒成 mapping_standardizations 喂给 verifier。

**Q：为什么 coverage 全失败要早停？** A：没有任何有效扩写时，反思也没候选可修，重试纯空转浪费 LLM。直接失败返回是"知道何时放弃"。

**Q：attempts 留痕有什么用？** A：完整记录每一轮的扩写/检索/校验，能复盘失败发生在哪一轮哪一步，对调试和 benchmark/错误分析至关重要。

**Q：max_retries=2 意味着几轮？** A：1 次正常 + 2 次反思 = 最多 3 轮。`range(max_retries+1)`。

**Q：为什么 V9 禁用了 MappingSupportVerifier？** A：实验版会 over-abstention（把该扩的也拒了，如 CP）。基于 benchmark 取舍，回退到不带它的 V9 Stable，保留为实验分支。

## 一句话总结

> `expand_verify_with_retry` 是项目主轴/装配图：`__init__` 备齐复用所有子服务；主流程先受约束扩写，再进 Verify→Reflect→Retry 循环（标准化+逐 expansion 检索 SNOMED → 校验 → 不过则带反馈反思重写 → 再来，最多 1 正常+2 反思）。两个关键设计：coverage 全失败早停（不空转）、attempts 全程留痕（可复盘）。当前 V9 Stable 禁用了 MappingSupportVerifier。局限是多轮 LLM 慢且贵、整句重写粒度粗、检索代码与标准化器重复——都是清晰的优化方向。这一篇把前 1~13 篇全部串起来了。





## 我跟claude聊的拓展

### 1. verify 到底能看到哪些信息

看函数签名就知道,它收到**三样**:

python

```python
verify_mappings(original_text, expanded_text, mapping_standardizations)
```

text

```text
① original_text        原句          "The patient denies CP."
② expanded_text        扩写后整句    "The patient denies chest pain."
③ mapping_standardizations  每个缩写 + 它的真实 SNOMED 检索结果：
     [{abbreviation:"CP", expansion:"chest pain",
       candidates:[{concept_name:"Chest pain", code:29857009, score:0.98},
                   {concept_name:"Chest wall pain", score:0.86}, ...]}]
```

对比一下 coverage 当时看到的(回扣第 10 篇):

text

```text
coverage 看到: 原句 + 候选词（纯文本 {abbr, expansion}）   ← 没有扩写句、没有 SNOMED
verify   看到: 原句 + 扩写句 + 真实 SNOMED 检索结果         ← 多了两样
```

**所以 verify 比 coverage 多两份情报:**

1. **扩写后的整句**(coverage 时句子还没扩写,根本不存在)→ 才能查"否定有没有丢、措辞有没有改坏"。
2. **真实 SNOMED 检索结果**(coverage 时还没去 Milvus 检索)→ 才能查"这个扩写到底有没有标准概念支撑"。

这就是为什么 verify 失败"带来新情报"——它掌握了 coverage 阶段根本不存在的信息。

### 2. 候选一样,循环靠什么新变量改变结果?

你的直觉"候选没变 = 没有新变量 = 原地打转"——**漏了一个关键的新变量:verify 的错误报告。**

对比两次"生成"的输入:

text

```text
第一次扩写的输入:  原文 + 候选
反思的输入:        原文 + 候选 + 上次扩错的结果 + ★verify 的错误报告★
```

**那份错误报告就是新变量。** 第一次扩写时,LLM **不知道**自己会把否定丢了、不知道选的那个候选 SNOMED 不支持;反思时,它**拿到了诊断**——"你上次把 denies 改成了 has""你选的 multiple sclerosis 没有 SNOMED 支撑"。

带着这份诊断,**即使候选完全一样**,LLM 也能产出不同结果:

**例 1(候选没变,改句子):**

text

```text
候选: chest pain（唯一，没变）
轮0: "has chest pain"          verify: negation_changed
轮1(知道"否定丢了"): "denies chest pain"   ✅ 候选一样，句子改对了
新变量 = "你把否定丢了"这条反馈
```

**例 2(候选集没变,换选择):**

text

```text
候选集: [multiple sclerosis, mitral stenosis]（没变）
轮0: 选 multiple sclerosis     verify: snomed_unsupported
轮1(知道"MS→multiple sclerosis 不被支持"): 改选 mitral stenosis   ✅
新变量 = "这个选择 SNOMED 不支持"这条反馈
```

所以**不是原地打转**——每一圈都比上一圈多了"上次错在哪"的信息,这是个真实的、会改变结果的新变量。这也呼应第 13 篇:**反思 ≠ 盲目重试,而是带着批改意见重做**。

### 3. 但你的直觉在一种情况下完全正确:确实会空转

如果满足:**只有唯一候选 + 失败的根因就是这个候选本身**(不是句子问题、也没有别的候选可换)——那么:

text

```text
轮0: 唯一候选 X，verify 说 X 不被支持
轮1: 反思拿到"X 不被支持"，但…只有 X 可选，改不出新东西
     → 要么撤回不扩，要么又交一个 X → verify 又说不支持
轮2: 同上 → 空转到次数耗尽
```

**这种情况下循环确实在原地打转**,最多只能"撤回扩写"。这正是你敏锐发现的局限,也是项目低上下文场景(LMN 单候选)反复失败的根源。`max_retries` 上限就是给这种空转兜底的——**承认有时救不回来,但用次数上限止损,不无限打转**。
