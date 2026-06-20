# Benchmark 补强 · 新增 cases(攻评测盲区:fallback 该扩)

> **动机**:现有 50 例里**没有显式"fallback(非词典)缩写应该被扩写"的 case**。这导致评测天然偏向"砍 fallback 就涨分",是 batch3 失败背后更深的偏差。补上这类 case 后:若某改动**过度弃权**(把该扩的 fallback 也弃了),benchmark 会立刻抓到 → 防住"为弱 benchmark 过拟合"。
>
> **重要旁证**:现有 `ambiguous` 类里的 **RA / ASD 本就不在词典、靠 fallback 扩**,且 ambiguous=10/10。所以"砍 fallback"会当场打崩这 4 例——这是"别砍 fallback"的硬证据。本补强把这类隐藏的 fallback 依赖**显式化、并加纯净版**。

## 新增类别:`fallback_should_expand`(6 例)

非词典、但上下文强支持的真实临床缩写,**系统应该靠 fallback 扩出来**。这些是"过度弃权探测器":batch3-rev 的弃权门若误伤它们,这里会扣分。

**追加到 `backend/evaluation/abbr_benchmark_cases.py` 的 `ABBR_BENCHMARK_CASES` 列表末尾(最后一个 `}` 之前加逗号):**

```python
    # —— fallback 该扩:非词典缩写 + 强上下文 → 应扩(过度弃权探测器)——
    {
        "id": "fallback_expand_001",
        "category": "fallback_should_expand",
        "text": "The patient's BP was elevated at 160/95 mmHg.",
        "expected_mappings": [
            {"abbreviation": "BP", "expansion": "blood pressure"}
        ]
    },
    {
        "id": "fallback_expand_002",
        "category": "fallback_should_expand",
        "text": "The patient's HR was 110 beats per minute.",
        "expected_mappings": [
            {"abbreviation": "HR", "expansion": "heart rate"}
        ]
    },
    {
        "id": "fallback_expand_003",
        "category": "fallback_should_expand",
        "text": "The patient's RR was 24 breaths per minute.",
        "expected_mappings": [
            {"abbreviation": "RR", "expansion": "respiratory rate"}
        ]
    },
    {
        "id": "fallback_expand_004",
        "category": "fallback_should_expand",
        "text": "The ECG showed ST-segment elevation in the inferior leads.",
        "expected_mappings": [
            {"abbreviation": "ECG", "expansion": "electrocardiogram"}
        ]
    },
    {
        "id": "fallback_expand_005",
        "category": "fallback_should_expand",
        "text": "The ABG revealed respiratory acidosis with hypoxemia.",
        "expected_mappings": [
            {"abbreviation": "ABG", "expansion": "arterial blood gas"}
        ]
    },
    {
        "id": "fallback_expand_006",
        "category": "fallback_should_expand",
        "text": "The UA showed pyuria and bacteriuria.",
        "expected_mappings": [
            {"abbreviation": "UA", "expansion": "urinalysis"}
        ]
    },
```

**请你审一遍医学正确性**(我确信这 6 个是标准、无歧义的:BP=blood pressure、HR=heart rate、RR=respiratory rate、ECG=electrocardiogram、ABG=arterial blood gas、UA=urinalysis,均不在 `ABBR_CANDIDATES` 词典里)。

## 评测口径的已知局限(诚实记一笔)

`run_benchmark.compare_mappings` 要求 `(abbreviation, expansion)` **精确相等**(已小写归一)。所以若系统把 `ECG` 扩成 `electrocardiography` 而非 `electrocardiogram`,会判错——即使它**正确地扩写了**。这会把"没扩(过度弃权)"和"扩得用词不同"混为一谈。

- 本批先接受这个局限(这 6 个的标准式很稳,风险低)。
- 后续可选改进:给 `compare_mappings` 加一个"扩写命中即算对(不卡精确串)"的宽松档,或对这些 case 加 `expected_text_contains` 辅助判。**这是评测层的后续项,先不做。**

## 改完后必须做:重定基线

加了 case = 改了尺子。**当前代码状态(批次 2,提交 `573cad6`)要在新 benchmark 上重跑一次,作为新锚点**,后面 batch3-rev 跟这个新锚点比,不是跟旧的 0.94 比。

```bash
# 1. 确认在批次2、干净
git log --oneline -1     # 573cad6
git status               # clean
# 2. append 上面 6 个 case 到 abbr_benchmark_cases.py,保存
# 3. 重跑,记新基线(总体 + 每类,尤其新类 fallback_should_expand 几分)
python backend/evaluation/run_benchmark.py
# 4. 提交评测集变更
git add backend/evaluation/abbr_benchmark_cases.py 项目梳理/
git commit -m "benchmark: add fallback_should_expand category (anti-overfit probe)"
```

把新基线数字(56 例的总体 + 每类)贴回来,我更新对照表,然后再谈 batch3-rev。

## 后续可选(本轮先不做,记着)

- 每类再加几例,把总数从 56 拉到 ~80,降低"1 例=2pp"的噪声。
- 加几例"多义 fallback"(像 RA/ASD 那样需上下文消歧的非词典缩写),进一步压过拟合空间。
