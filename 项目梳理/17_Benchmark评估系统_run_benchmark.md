# Benchmark 评估系统（用 50 道带答案的题给系统打分）

> 文件：`backend/evaluation/run_benchmark.py`（169 行）+ `abbr_benchmark_cases.py`（50 个 case）
> 入口：`run_benchmark()`；核心比较函数 `compare_mappings()` / `compare_text_contains()`
> 衔接：进入阶段六（评估与重构）。前面把系统建好了，但"它到底准不准、改了之后是变好还是变坏"——靠这套 benchmark 量化回答。**这是项目最大的亮点之一:有数据驱动的评估闭环,而不是凭感觉调 prompt。**

## 核心速记
> 1. **评估闭环**:开发→评测→分析→优化。没有 benchmark,"感觉变好了"不可靠。这是工程化思维的体现,面试重点突出。
> 2. **双重判定**:① mapping 集合精确相等 + ② 关键文本片段保留(`text_contains`)。两个都对才算对。
> 3. **分类统计**:50 例分 6 类各算准确率,精准定位最弱能力(low context 仅约 20%)。
> 次要(trivia):`normalize_text` 只 strip+lower、结果写 JSON 给 API summary 读(回扣第15篇)、失败 case 打印——扫一眼。

## 这一段在解决什么

大白话:**一个离线评分脚本。拿 50 道标好答案的题,让系统逐个做,自动对答案,算出总分、各类得分、列出做错的题。**

```text
50 个 benchmark case（带标准答案）
   ↓ 逐个跑 service.expand_verify_with_retry
   ↓ 自动对答案：mapping 对不对 + 关键片段在不在
→ 总准确率 + 6 类各自准确率 + 失败 case 清单 → benchmark_results.json
```

## 核心1 · 为什么要做 Benchmark（骨架,必背）

项目早期优化方式通常是:"改个 prompt → 跑两个例子 → 感觉好像好了"。问题:**随机、不可复现、不可量化**——你根本不知道改完是真变好,还是这个好了那个坏了。

benchmark 把它变成**数据驱动的闭环**:

```text
开发 → 跑 50 题评测 → 看哪类掉分 → 针对性优化 → 再跑评测对比
```

有了固定题库 + 自动评分,每次改动都能**量化对比**"分数涨了还是跌了、哪一类涨哪一类跌"。这是从"作坊"到"工程"的关键一步,**面试时这是项目最该吹的硬实力之一**。

## 核心2 · 怎么对答案:双重判定（实现 + 真实数据）

一个 case 算对,要**同时**满足两条:

**① mapping 集合精确相等(`compare_mappings`)**

```python
expected_set = {(normalize(abbr), normalize(exp)) for ... in expected_mappings}
predicted_set = {(normalize(abbr), normalize(exp)) for ... in predicted_mappings}
return expected_set == predicted_set        # 集合完全相等
```

- 把"标准答案"和"系统预测"都做成 `(缩写, 扩写)` 的**集合**,要求**完全相等**。
- 用**集合**:顺序无关(扩了 HTN、DM 还是 DM、HTN 都行);`normalize_text` 做 `strip().lower()`,大小写无关。
- 但**精确相等**:多扩一个、少扩一个、扩错一个,都算错(偏严,见局限)。

**② 关键文本片段保留(`compare_text_contains`)**

```python
correct = normalize(expected_text_contains) in normalize(final_text)   # 子串包含
```

- 检查最终扩写文本里**包不包含**指定片段。**专门测否定保持(negation preservation)**。
- 为什么需要它:mapping 可能对(`CP→chest pain`),但句子可能把 `denies` 改成了 `has`——光比 mapping 查不出这个错。所以额外查 `"denies chest pain"` 这个片段在不在最终文本里。
- 没有指定片段的 case → 跳过这项(`checked:False, correct:True`)。

**最终:`final_correct = mapping_correct AND text_check.correct`**——两个都过才算这题对。

## 核心3 · 分类统计:定位最弱能力（真实数据）

50 例分 **6 类**,每类单独算准确率:

```text
single_meaning      单义缩写(HTN→hypertension)
ambiguous           歧义缩写(MS→?)
multi_abbreviation  多缩写
coverage_failed     覆盖失败(ABC 这种不该扩的)
low_context         低上下文(LMN 该不该扩)
negation            否定保持(denies CP)
```

为什么分类:**总分掩盖问题,分类暴露短板**。文档记录的 V9 结果:

```text
总体: 约 46/50 = 92%（V9 Stable）
single_meaning      100%
ambiguous            90%
multi_abbreviation  100%
coverage_failed     100%
negation            100%
low_context          20%  ← 一眼看出最弱：低上下文过度扩写
```

正是这个分类表让你能说出"系统主要问题不是不会扩,而是**不知道什么时候不该扩**"——这是项目从"扩写问题"进化到"决策问题"的关键洞察(回扣文档)。

## 数据快照:一个 case 的判定

```text
case: {id:"negation_001", category:"negation", text:"The patient denies CP.",
       expected_mappings:[{CP, chest pain}],
       expected_text_contains:"denies chest pain"}

系统输出: mappings=[{CP, chest pain}], final_text="The patient denies chest pain."
  ① compare_mappings: {(cp,chest pain)} == {(cp,chest pain)} → True
  ② text_contains: "denies chest pain" in "...denies chest pain." → True
  → final_correct = True ✅
```

## 会被追问 / 诚实局限（★主动说）

- **评测集小(50)且自己造的**:可能不代表真实临床分布,统计意义有限。
  → 面试这么说:"50 例是手工构造的、覆盖六类典型场景,够定位能力短板,但样本小、是我自己标的,统计代表性有限。下一步应该扩大规模、用真实标注数据。"
- **精确集合相等偏严,没有部分分(partial credit)**:多缩写 case 里扩对 2 个错 1 个,直接算整题错。无法体现"对了一部分"。
  → "评分是 exact-match,偏严。可以补充 mapping 级的 precision/recall/F1,给部分分,更细粒度看能力。"
- **`text_contains` 只是子串包含,很粗**:`"denies chest pain"` 做子串匹配,措辞稍变就漏;反之系统多写点只要包含也算过,不够精确。
  → "否定测试用子串匹配是近似,可能漏报或误判,更严谨要做句法/语义级的否定范围检查。"
- **normalize 只 strip+lower**:不处理标点、复数、同义词。`"chest pain"` vs `"chest pains"` 会判不等。
- **只有 exact-match accuracy,没有标准 NLP 指标**(P/R/F1)。
- **ground truth 人工标,可能有错或偏见**;且每个 case 跑完整 pipeline(多次 LLM),50 例 benchmark **很慢很贵**(回扣第 14 篇多轮 LLM)。

## 面试怎么说

**合格版（30 秒）**：
> 我做了一个 50 例、6 类的 benchmark:逐个跑主流程,自动对答案——mapping 用集合精确相等比、再加一个关键片段包含检查(专测否定保持),两个都过才算对。按类别统计准确率,V9 整体约 92%,但 low_context 只有 20%,一眼定位最弱能力。结果写 JSON,API 能读 summary。

**优秀版（1 分钟）**：
> Benchmark 是我项目里很重要的一块,它把优化从"凭感觉调 prompt"变成数据驱动闭环。评分是双重判定:mapping 做成 (缩写,扩写) 集合精确相等,顺序和大小写无关;再加 text_contains 检查关键片段在不在,专门抓否定保持这种 mapping 查不出的错,比如 denies 被改成 has。我特别看重分类统计——总分会掩盖问题,分六类后立刻看出 low_context 只有 20%,这让我得出'系统的瓶颈不是不会扩,而是不知道何时不该扩'的结论,直接指导了后续的 MappingSupportVerifier 实验。诚实说局限:50 例小、我自己标的、exact-match 偏严没有部分分、text_contains 子串匹配偏粗。下一步是扩规模、上 P/R/F1。

## 易错点 / 面试问答

**Q：一个 case 怎么算对？** A：两条同时满足——mapping 集合和标准答案精确相等,且指定关键片段包含在最终文本里(测否定保持)。

**Q：为什么 mapping 用集合比较？** A：顺序无关,只要 (缩写,扩写) 的集合一致就行,配合 normalize 大小写无关。但要求完全相等,多扩少扩都算错。

**Q：text_contains 是干嘛的？** A：专测否定/语义保持。mapping 可能对但句子把 denies 改成 has,光比 mapping 查不出,所以查关键片段在不在最终文本。

**Q：为什么要分类统计？** A：总分掩盖短板。分六类后能精准定位最弱能力(low_context 20%),指导针对性优化。

**Q：这套评估有什么不足？** A：集小、自标、exact-match 偏严无部分分、text_contains 子串匹配偏粗、无 P/R/F1。改进是扩规模 + 上标准指标。

## 一句话总结

> Benchmark 把优化变成数据驱动闭环:50 例 6 类,逐个跑主流程,双重判定(mapping 集合精确相等 + 关键片段包含测否定保持),按类统计准确率(V9 约 92%,low_context 仅 20% 暴露最弱能力),结果写 JSON 供 API 读。亮点是分类定位短板、得出"瓶颈是何时不该扩"的洞察。局限是集小自标、exact-match 偏严无部分分、text_contains 偏粗、无 P/R/F1——可扩规模 + 上标准指标改进。
