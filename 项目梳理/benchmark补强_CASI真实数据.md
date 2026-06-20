# Benchmark 补强 · 基于 CASI 真实医疗数据

## 数据来源(真实、权威)

**CASI — Clinical Abbreviation Sense Inventory**
Moon S, Pakhomov S, Liu N, Ryan JO, Melton GB. *A sense inventory for clinical abbreviations and acronyms created using clinical notes and medical dictionary resources.* JAMIA 2014;21(2):299-307. PMID 23813539.

- 取自美国**明尼苏达大学 Fairview Health Services 四家医院的 352,267 份真实临床病历**。
- 每个缩写的义项经人工标注,并与 **UMLS / ADAM / Stedman's Medical Dictionary** 核对。
- 是临床缩写消歧的**公开标准基准**;NLP 文献普遍以 RA / MS / MI / PA / PCP 等作高歧义难例。

## 做了什么

新增文件 `backend/evaluation/abbr_benchmark_cases_casi.py`,定义 `CASI_BENCHMARK_CASES`(24 例):

- **18 例 `casi_ambiguous`**:CASI 里真实存在、且**不在本项目词典**的多义缩写(RA/PA/PCP/DC/IM/BAL/BM/ET),每个义项配一句符合临床书写习惯的消歧语境。这些缩写**全走 fallback**,直接压测真实世界最难、本项目此前缺失的维度:fallback 消歧。
- **6 例 `fallback_should_expand`**:真实单义、非词典缩写(BP/HR/RR/ECG/ABG/UA),应被扩出——**过度弃权探测器**:batch3-rev 的弃权门若误伤它们,这里立刻扣分。

缩写与义项 100% 来自 CASi/标准释义;句子语境为合规构造句(真实 CASI snippet 含 PHI、有使用限制,故用等价临床语境句替代)。14 个缩写**经核对全部不在 `ABBR_CANDIDATES` 词典**,确保真走 fallback。

## 为什么这正面回应"别为弱 benchmark 过拟合"

- 旧 50 例几乎只考词典缩写 + 假缩写弃权,天然偏向"砍 fallback 就涨分"。
- 这 24 例把**真实的 fallback 消歧**(RA=room air/rheumatoid/right atrium 等)显式纳入考核。**若某改动过度弃权或砍 fallback,这里会塌方**——过拟合被堵死。
- 难度真实:这些是 CASI 公认难例,**基线大概率不会满分**,这正是"真实世界没那么好做"的诚实信号,不是 bug。

## 怎么接进去 + 重定基线

**1. 在 `backend/evaluation/abbr_benchmark_cases.py` 末尾(列表 `]` 之后)追加两行:**

```python

from evaluation.abbr_benchmark_cases_casi import CASI_BENCHMARK_CASES
ABBR_BENCHMARK_CASES = ABBR_BENCHMARK_CASES + CASI_BENCHMARK_CASES
```

**2. 确认在批次 2、干净,然后重跑(50 → 74 例),记新基线:**

```bash
git log --oneline -1     # 573cad6
git status               # clean
python backend/evaluation/run_benchmark.py
```

**3. 提交评测集变更:**

```bash
git add backend/evaluation/abbr_benchmark_cases.py backend/evaluation/abbr_benchmark_cases_casi.py 项目梳理/
git commit -m "benchmark: add CASI-grounded real-data cases (fallback disambiguation + anti-overfit probe)"
```

把新基线(74 例总体 + 每类,尤其 `casi_ambiguous` 和 `fallback_should_expand` 各几分)贴回来,我更新对照表。**之后 batch3-rev 跟这个新基线比。**

## 诚实局限(记一笔,面试也用得上)

- **评测口径**:`compare_mappings` 要求 `(abbr, expansion)` 精确相等(已小写归一)。若系统把 `ECG` 扩成 `electrocardiography`、`RA` 扩成 `right atria` 而非 `right atrium`,会判错——即使语义对。这会把"没扩/弃权"和"扩得用词略不同"混在一起。本轮先接受;后续可给 `compare_mappings` 加"同义命中即算对"的宽松档,或用 SNOMED concept_id 比对(更严谨)。
- **语境是构造句**:缩写+义项来自 CASI 真实数据,句子是合规等价构造(规避 PHI/许可)。要 100% 真实 snippet 需走 CASI 数据使用协议下载原始集。
- **仍是 50→74 例**:比原来强,但要做严肃评测,真实方向是接 CASI/MeDAL 全量子集(几百~上千例)。这是"评测可信度"的后续大项。

## Sources

- [Moon et al., A sense inventory for clinical abbreviations and acronyms (CASI), JAMIA 2014 — PubMed](https://pubmed.ncbi.nlm.nih.gov/23813539/)
- [CASI dataset overview (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC3932450/)
- [Agrawal et al., Large Language Models are Few-Shot Clinical Information Extractors (uses CASI subset), arXiv 2205.12689](https://arxiv.org/pdf/2205.12689)
