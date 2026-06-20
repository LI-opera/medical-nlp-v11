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
| 批次 2 | 0.9400 | 0.40 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 无 | 无 | **合入** ✅ net 持平、无回归;价值在架构(失败隔离+增量+弃权基础设施);QRS/NOP verify 接受未触发弃权→留批次3 |
| 批次 3(原版) | 0.9000 | — | 0.90 | — | — | — | 0.80 | 无 | MNO新增误扩、NOP换更像医学的假词、ambiguous/cov_failed各掉1 | **回退** ❌ top-k 制造假扩写、NER 拦不住同源幻觉,方向搞反 |

> 上表是 **50 例旧 benchmark**。之后评测集换成 **74 例(+CASI 真实数据)**,锚点重置,见下。

---

## ★ 74 例新基线(CASI 补强后,批次 2 代码,2026-06-20)

评测集从 50 → 74 例(加了 24 个 CASI 真实缩写 case:18 多义消歧 + 6 单义 fallback)。**这是 batch3-rev 起的新锚点,旧的 0.92/0.94 不再直接可比。**

| 指标 | 值 |
|---|---|
| Total | 74 |
| Correct | 69 |
| **Accuracy** | **0.9324** |

| 类别 | 正确/总 | 备注 |
|---|---|---|
| single_meaning | 10/10 | |
| ambiguous | 9/10 | ambiguous_004(MS)**又翻错**→ LLM temp=0 仍有抖动,此 case 是噪声源 |
| multi_abbreviation | 10/10 | |
| coverage_failed | 5/5 | |
| low_context_abbreviation | 2/5 | ★LMN/QRS/NOP 仍过度扩写(真目标) |
| negation_preservation | 10/10 | |
| **casi_ambiguous** | **17/18** | 真实 fallback 消歧基本全对;唯一失败 casi_pcp 是"Primary Care Provider≠physician"的**精确串口径**问题,非真错 |
| **fallback_should_expand** | **6/6** | BP/HR/RR/ECG/ABG/UA 全扩对 → 过度弃权探测器基线干净 |

**关键解读**:
- 系统对**真实 fallback 缩写消歧很强**(23/24),证明 fallback 是真能力,**砍掉它是错的**。
- `casi_ambiguous` + `fallback_should_expand` 现在是 **batch3-rev 的护栏**:弃权门若过度弃权,这两类会立刻塌——过拟合被堵死。
- `ambiguous_004` 翻错是 **LLM 噪声**(MS 是 primary/词典,弃权门碰不到它);batch3-rev 跑出来若它又翻,别算门的账。
- `casi_pcp` 暴露**精确串匹配局限**:语义对、用词不同就判错。后续可改 SNOMED concept_id 比对。

### 74 例对照表(batch3-rev 起)

| 批次 | 总体 Acc | low_ctx | casi_ambig | fb_expand | ambiguous | single/multi/neg/cov | 翻对 | 翻错 | 结论 |
|---|---|---|---|---|---|---|---|---|---|
| **批次2(新锚点)** | **0.9324** | 0.40 | 17/18 | 6/6 | 0.90 | 10/10·10/10·10/10·5/5 | — | — | 锚点 |
| batch3-rev | | | | | | | | | |
| 批次 4 | | | | | | | | | |
| 批次 5 | | | | | | | | | |
