# Error Analysis 错误归因（把失败 case 自动贴标签、统计错因分布）

> 文件：`backend/evaluation/error_analysis_report.py`（180 行）
> 入口：`main()`；核心分类器 `classify_error_type()` / `classify_taxonomy()`
> 衔接：评估闭环的**下半环**。第 17 篇 benchmark 告诉你"错了多少",这一篇告诉你"**错的是什么类型、哪类最多**"——把模糊的"准确率低"变成可行动的"low_context 过度扩写占比最高,该优先治它"。

## 核心速记
> 1. **从"知道错了"到"知道为什么错"**：读 benchmark 结果,只看失败 case,自动归类、统计错因分布。这是数据驱动优化的最后一块拼图。
> 2. **两层归因**：`classify_error_type`(5 类粗分) + `classify_taxonomy`(major+sub 两级细分)。
> 3. **纯规则归因,不用 LLM**：靠对比 expected/predicted 的**集合差**判定,确定性、可解释、可复现。
> 次要(trivia):读 benchmark_results.json、写 error_analysis_report.json 供 API 读、setdefault 计数——扫一眼。

## 这一段在解决什么

大白话:**benchmark 跑完知道错了 4 道。这一篇把这 4 道挨个看:这道是"多扩了"、那道是"漏扩了"、另一道是"选错义项了"……再统计"多扩 2 道、漏扩 1 道、消歧错 1 道"。** 这样你就知道**该先修哪类**。

```text
benchmark_results.json（含每题对错）
   ↓ 只挑 correct==False 的失败 case
   ↓ 每个失败 case 自动贴两种标签（error_type + taxonomy）
   ↓ 统计各类错因数量
→ error_analysis_report.json（错因分布 + 失败详情）
```

## 核心1 · 为什么要错误归因（骨架,必背）

只有准确率(第 17 篇)还不够——**"92% 准确率"不告诉你那 8% 错在哪、该怎么修**。

错误归因把"错"**结构化**:

```text
没有归因：准确率 90%，剩下 10% 不知道咋回事 → 凭感觉乱改
有归因：  失败的里 60% 是低上下文过度扩写 → 明确该上"上下文支持判断"
```

这让优化**有的放矢、按错因分布排优先级**,而不是东改一下西改一下。**它和 benchmark 合起来,才构成完整的"开发→评测→归因→优化"闭环**——这是项目工程化的核心亮点。

## 核心2 · 两层分类器（实现 + 真实数据）

**① `classify_error_type`——5 类粗分**

```python
if category == "low_context_abbreviation":  return "low_context_over_expansion"  # 低上下文直接归这类
if expected and predicted:                   return "wrong_expansion"     # 都有值 → 扩错了
if expected and not predicted:               return "missing_expansion"   # 该扩没扩
if not expected and predicted:               return "over_expansion"      # 不该扩却扩了
return "unknown_error"
```

**② `classify_taxonomy`——major + sub 两级细分(更细,基于集合差)**

```python
extra_abbrs = predicted_abbrs - expected_abbrs    # 多扩的缩写
missing_abbrs = expected_abbrs - predicted_abbrs  # 漏扩的缩写

if extra_abbrs:    → "Over Expansion / Extra Abbreviation Expansion"   # 多扩了
if missing_abbrs:  → "Under Expansion / Missing Abbreviation Expansion" # 漏扩了
if 缩写集相同但扩写不同: → "Wrong Disambiguation / Wrong Expansion Selection" # 缩写对、义项选错
if text_check 失败:  → "Semantic Preservation Failure"                  # 映射对、句子改坏了（否定丢失）
else:              → "Unknown / Needs Manual Review"
```

**关键:用集合差判定,纯规则**——`predicted_abbrs - expected_abbrs` 算出"多扩了哪些缩写",`expected - predicted` 算"漏了哪些"。不用 LLM,所以**确定性、可解释、可复现**(回扣"确定性优先"的项目哲学)。这点和前面那些 LLM 判断形成对比——**评估归因刻意用规则,不引入 LLM 的不确定性**。

## 数据快照：一个失败 case 的归因

```text
失败 case: text="The patient has DM and QRS.", category="low_context_abbreviation"
  expected=[{DM, diabetes mellitus}]              # 只该扩 DM
  predicted=[{DM, diabetes mellitus}, {QRS, QRS complex}]  # 多扩了 QRS

classify_error_type: category=low_context → "low_context_over_expansion"
classify_taxonomy:   extra_abbrs={QRS} → "Over Expansion / Extra Abbreviation Expansion"
                     reason: "预测了标准答案中不存在的额外缩写,通常是低上下文误扩写"
```

汇总后报告会显示:`Over Expansion: N 个`,一眼看出过度扩写是主要错因(回扣文档:low_context 是最弱项)。

## 核心3 · 报告结构与闭环

输出 `error_analysis_report.json`:

```text
{ benchmark_summary: {total, correct, accuracy, category_stats},   # 总览
  failed_summary: {failed_count, error_type_summary, taxonomy_summary},  # 错因分布统计
  failed_cases: [每个失败 case 的详情 + 两种标签] }                 # 逐条详情
```

API 的 `/error-analysis/summary`(第 15 篇)读这个 JSON 返回 summary。**闭环:benchmark 写结果 → error analysis 归因 → 都写成 JSON → API 暴露 summary**。

## 会被追问 / 诚实局限（★主动说）

- **两套分类器(error_type + taxonomy)有重叠**:都在归类失败,维护两套有点冗余,口径还可能不一致。
  → 面试这么说:"我有两层归因——一个粗分一个细分,确实有重叠。早期想要不同粒度,但更干净的做法是统一成一套带层级的 taxonomy。"
- **`classify_error_type` 的低上下文分支只看 category 标签,不看实际错法**:任何失败的 low_context case 都直接归成 `over_expansion`,但它**理论上可能因别的原因失败**(虽然多数确实是过度扩写)。这是个偏粗的假设。
  → "低上下文直接归过度扩写是基于经验假设,严格说应该按实际 predicted/expected 差异判,不靠类别标签。"
- **taxonomy 检查有优先级顺序**:`extra_abbrs` 先于 `missing_abbrs` 判。如果一个 case **既多扩又漏扩**,只会报"Over Expansion",**掩盖了同时存在的漏扩**。
  → "归因是按优先级取第一个命中的,复合错误只报一种,可以改成多标签。"
- **纯规则 → 边界 case 落到 Unknown 需人工**:规则覆盖不到的归 `Needs Manual Review`。这是规则法的固有代价(换来确定性)。
- **依赖 benchmark 标注质量**:归因建立在 expected_mappings 标对的前提上,标注错了归因就错(garbage in)。
- **静态、离线**:得先跑完 benchmark 才能跑,不是实时监控。

## 面试怎么说

**合格版（30 秒）**：
> 错误归因读 benchmark 结果,只看失败 case,用纯规则给每个失败贴标签——比如对比 predicted 和 expected 的缩写集合差,多扩归 Over Expansion、漏扩归 Under Expansion、缩写对但义项错归 Wrong Disambiguation、句子改坏归 Semantic Preservation Failure。统计错因分布,指导优化优先级,结果写 JSON 供 API 读。

**优秀版（1 分钟）**：
> Benchmark 给准确率,Error Analysis 给错因,两个合起来才是完整的数据驱动闭环。归因我特意用纯规则、不用 LLM——靠 predicted 和 expected 的缩写集合差来判:多扩、漏扩、义项选错、语义保持失败、还是未知。这样确定性、可解释、可复现,和系统主链路那些 LLM 判断刻意区分开。它把"准确率 90%、剩下不知道咋回事"变成"失败里过度扩写占多数",直接指出低上下文是瓶颈,催生了 MappingSupportVerifier 实验。诚实说局限:两套分类器有重叠该统一;低上下文分支只看类别标签偏粗;归因按优先级只报一种错,复合错误会被掩盖;而且依赖 benchmark 标注质量。

## 易错点 / 面试问答

**Q：Error Analysis 和 Benchmark 什么关系？** A：benchmark 算"错了多少"(准确率),error analysis 读它的结果归因"错的是什么类型"。前者量化,后者定位,合起来是闭环。

**Q：怎么归类的,用 LLM 吗？** A：纯规则,不用 LLM。靠 predicted 和 expected 的缩写集合差(多扩/漏扩/义项错)+ text_check 是否失败来判。确定性可复现。

**Q：有哪几类错？** A：taxonomy 五类——Over Expansion(多扩)、Under Expansion(漏扩)、Wrong Disambiguation(义项选错)、Semantic Preservation Failure(语义/否定丢失)、Unknown(需人工)。

**Q：归因有什么不足？** A：两套分类器重叠该统一;按优先级只报一种错,复合错误被掩盖;边界 case 落 Unknown;依赖标注质量。

**Q：归因结果怎么用？** A：看错因分布排优化优先级——比如发现过度扩写占多数,就知道该上下文支持判断,而不是凭感觉乱改。

## 一句话总结

> Error Analysis 是评估闭环下半环:读 benchmark 失败 case,用**纯规则**(缩写集合差 + text_check)两层归因——error_type 粗分 5 类、taxonomy 细分 Over/Under Expansion、Wrong Disambiguation、Semantic Preservation Failure、Unknown,统计错因分布、写 JSON 供 API 读。亮点是确定性可复现、把"准确率低"变成可行动的错因优先级(指出低上下文是瓶颈)。局限是两套分类器重叠、低上下文分支偏粗、复合错误只报一种、依赖标注质量。
