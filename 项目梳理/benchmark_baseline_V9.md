# V9 Stable · Benchmark 基线(批次 0 锚点)

> 跑于 2026-06-20,`medical-refactor` 分支起点(= V9 逻辑,未改)。
> 这是后面批次 1–5 比净收益的**唯一锚点**。每批次跑完都和这张表逐类对比。
> 运行环境补丁(不影响逻辑/准确率,只为能跑起来):① `embedding_factory.py` device `auto→cuda/cpu`;② `.env` 的 `MILVUS_URI` 宿主机直跑改 `localhost`。

## 总体

| 指标 | 值 |
|---|---|
| Total | 50 |
| Correct | 46 |
| **Expansion Accuracy** | **0.9200** |

> ⚠️ 小样本提醒:50 例,**1 例 = 2 个百分点**。"net ≥ 基线"是粗尺子——单看总体分容易被 1 例噪声带偏。**判净收益时必须看「具体哪几例翻了」+ 每类**,不能只看总分。

## 每类

| 类别 | 正确/总 | Accuracy | 备注 |
|---|---|---|---|
| single_meaning | 10/10 | 1.0000 | 满分,别让它掉 |
| ambiguous | 9/10 | 0.9000 | 1 例消歧错(MS) |
| multi_abbreviation | 10/10 | 1.0000 | 满分,确定性替换别串位 |
| coverage_failed | 5/5 | 1.0000 | 满分,该弃权的都弃了 |
| **low_context_abbreviation** | **2/5** | **0.4000** | ★主弱项,3 例过度扩写 |
| negation_preservation | 10/10 | 1.0000 | 满分,确定性替换要守住 |

## 4 个失败案例 + V11 归因

| # | id | 类别 | 输入 | 期望 | V9 实际 | 失败模式 | V11 谁来治 |
|---|---|---|---|---|---|---|---|
| 1 | ambiguous_004 | ambiguous | "MS with a diastolic murmur" | mitral stenosis | multiple sclerosis | **消歧错**:有 "diastolic murmur"(心脏线索)却选了神经病 | **批次 4**(domain 软约束:murmur→心脏 domain 加分 mitral stenosis);批次 2(reflect 换候选)兜底 |
| 2 | coverage_005 | low_context | "evaluated for LMN" | [](不扩) | lower motor neuron | **过度扩写**:上下文不足仍扩了已知词典缩写 | **批次 1**(coverage 选唯一,选不出→不进 mappings)+ 弃权语义 |
| 3 | coverage_006 | low_context | "DM and QRS" | 只扩 DM | DM + **QRS complex** | **过度扩写**:QRS(非词典,fallback 生成)被硬扩 | **批次 1 + 批次 3**(NER is_medical 杀垃圾候选 / coverage 更严) |
| 4 | coverage_008 | low_context | "COPD and NOP" | 只扩 COPD | COPD + **no operation** | **过度扩写 + 烂候选**:NOP→"no operation" 是 fallback 幻觉 | **批次 3**(NER 校验杀掉 "no operation" 这种非医学候选)+ 批次 1 |

## 给 V11 的读法

- **headroom 几乎全在 low_context**(2/5)。4 个失败里 **3 个是「过度扩写」**(LMN/QRS/NOP 不该扩或扩了烂词)。这正是 22 篇说的「不该扩就不扩」——批次 1(coverage 选唯一 + 选不出不进列表)和批次 3(NER 杀非医学候选)是主攻手。
- 唯一的「消歧错」(MS→应 mitral stenosis)是批次 4(domain 软约束)的靶子。
- **要守住的满分类**:single_meaning、multi_abbreviation、negation_preservation、coverage_failed。任何批次让这些掉,即使 low_context 涨了,也要看净收益——这就是 V10 over-abstention 回退的教训。
- ⚠️ 注意失败案例 2/3/4 的 `Text Check` 都是 `checked:False`(这些类没 expected_text_contains),所以它们**只靠 mappings 集合判对错**——这是合理的(low_context 判的是"该不该扩",不是语序)。

## 净收益对比模板(每批次填)

| 批次 | 总体 Acc | low_context | ambiguous | single | multi | neg | cov_failed | 翻对的例 | 翻错的例 | 结论(合入/回退) |
|---|---|---|---|---|---|---|---|---|---|---|
| **V9 基线** | **0.9200** | 0.40 | 0.90 | 1.00 | 1.00 | 1.00 | 1.00 | — | — | 锚点 |
| 批次 1 | **0.9400** | 0.40 | **1.00** | 1.00 | 1.00 | 1.00 | 1.00 | ambiguous_004 (MS→mitral stenosis) | 无 | **合入** ✅ net +1,满分类全守,消歧错被治好 |
| 批次 2 | | | | | | | | | | |
| 批次 3 | | | | | | | | | | |
| 批次 4 | | | | | | | | | | |
| 批次 5 | | | | | | | | | | |
