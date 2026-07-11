# 批次 4 · 给 Codex 的指令(可整段复制)· domain 软约束(激活死参数)

## 背景

V11 批次 1/2/3-rev/5 已合入。本批做 **domain 软约束**:给每个 mapping 一个 SNOMED domain,在检索重排时给「domain 匹配的 SNOMED 概念」**软加分**,激活那个一直传 `None` 的死参数 `domain_filter`(改造为 `domain_boost`)。

**domain 的来源(两路对齐)**:
- **词典候选**:在 `ABBR_CANDIDATES` 里直接给每个扩写加 domain(可信源,人工标注)。
- **fallback 候选**:fallback 之后跑 **NER 产 label**,经 `NER标签→SNOMED domain` 映射得到 domain。

> **NER 这次只产 domain,不做任何过滤、不改 fallback 数量**(不带 batch3 的 is_medical 过滤、不带 top-k)。batch3 翻车是那两样造成的,纯产 domain 是安全的——它只挂元数据、不碰候选集、不影响 coverage。弃权的活已由 batch3-rev 的置信门接管。

## ★ 诚实预期(必读)

**benchmark 大概率持平**。因为 domain_boost 作用在「检索」——它改的是「已选定的扩写匹配到哪个 SNOMED 概念」,**不改 coverage 选了哪个扩写**,而 benchmark 判分看 `(缩写,扩写)`。本批价值在:① **激活死参数**(设计闭环);② 提升 `standardized_entities` 的**编码匹配质量**(benchmark 量不到)。**验收看「死参数被激活 + 不回退 + 某 case 的 SNOMED 概念变更对路」,不是看分数涨。**

## 铁律

1. **先 Read 现状**:`data/abbr_candidates.py`、`services/abbr_candidate_retriever.py`、`services/ner_service.py`、`services/medical_retriever.py`、`services/abbr_service.py`。行号是当前快照(medical-refactor),动手前核对。
2. **不删不改** batch1/2/3-rev/5 的成果(确定性替换、状态机、弃权门、standardized_entities 出口)。
3. **NER 不做过滤**:只产 domain,不丢任何候选,不改 fallback 候选数量。
4. **软加分,不硬过滤**:保留 `domain_filter` 原逻辑(继续传 None),新增 `domain_boost`。映射错顶多排序略偏,不弄丢答案。

---

## 改动 1 — `backend/services/ner_service.py` 重新加 `is_medical()`(只产 label)

在 `NERService` 类里加(复用现有 `self.ner_pipeline`,不新建模型;**只返回 label,调用方不拿它做过滤**):

```python
    def is_medical(self, text: str):
        """对孤立短语返回 (是否有医学实体, 主 label, 分数)。
        本批只用其 label 推断 domain,不做候选过滤。
        """
        if not text:
            return False, None, 0.0
        ents = self.extract_entities(text)
        if not ents:
            return False, None, 0.0
        top = max(ents, key=lambda e: e["score"])
        return True, top["label"], top["score"]
```

## 改动 2 — `backend/services/abbr_service.py` 顶部加 NER 标签→SNOMED domain 映射

文件顶部(import 之后、类定义之前)加常量。SNOMED 库实际 domain 取值见注释:

```python
# NER 实体标签 → SNOMED domain_id(库里实际取值:Condition/Observation/Measurement/
# Procedure/Drug/Spec Anatomic Site/Device 等)。映射不完美没关系——domain_boost 是软加分。
NER_LABEL_TO_DOMAIN = {
    "DISEASE_DISORDER": "Condition",
    "SIGN_SYMPTOM": "Condition",
    "BIOLOGICAL_STRUCTURE": "Spec Anatomic Site",
    "MEDICATION": "Drug",
    "DIAGNOSTIC_PROCEDURE": "Procedure",
    "THERAPEUTIC_PROCEDURE": "Procedure",
    "LAB_VALUE": "Measurement",
    "DETAILED_DESCRIPTION": "Observation",
}
```

并在 `__init__` 里 `self.standardizer = MedicalStandardizer()` 那行**下方**加(复用 NER 实例,不重复加载模型):
```python
        self.ner_service = self.standardizer.ner_service
```

## 改动 3 — `backend/data/abbr_candidates.py` 词典加 domain(结构改为 list-of-dict)

把 `ABBR_CANDIDATES` 的值从「字符串列表」改成「字典列表」,每个扩写带 `expansion` + `domain`。domain 取 SNOMED 库的值(疾病→`Condition`;化验/计数→`Measurement`;体征/观察→`Observation`;操作→`Procedure`;药物→`Drug`;解剖部位→`Spec Anatomic Site`)。示例:

```python
ABBR_CANDIDATES = {
    "SOB": [{"expansion": "shortness of breath", "domain": "Condition"}],
    "HTN": [{"expansion": "hypertension", "domain": "Condition"}],
    "DM": [
        {"expansion": "diabetes mellitus", "domain": "Condition"},
        {"expansion": "dermatomyositis", "domain": "Condition"},
    ],
    "CP": [
        {"expansion": "chest pain", "domain": "Condition"},
        {"expansion": "cerebral palsy", "domain": "Condition"},
        {"expansion": "chronic pancreatitis", "domain": "Condition"},
    ],
    "WBC": [
        {"expansion": "white blood cell count", "domain": "Measurement"},
        {"expansion": "white blood cells", "domain": "Measurement"},
    ],
    # ... 其余条目同样改造:逐条把字符串换成 {"expansion": ..., "domain": ...}
    "NA": [{"expansion": "sodium", "domain": "Measurement"}],
    "K": [{"expansion": "potassium", "domain": "Measurement"}],
}
```
**把现有全部条目逐条改造完**(疾病类绝大多数给 `Condition`;实验室项 WBC/RBC/HGB/PLT/NA/K 给 `Measurement`;拿不准的给 `Condition` 或留 `None` 都行,软加分不致命)。

## 改动 4 — `backend/services/abbr_candidate_retriever.py` 适配新结构

`retrieve`(6–17 行)现在按字符串读,改成按字典读、带出 domain:

```python
    def retrieve(self, abbreviation: str):
        abbr = abbreviation.upper().strip()
        candidates = ABBR_CANDIDATES.get(abbr, [])
        return [
            {"abbreviation": abbr, "expansion": c["expansion"], "domain": c.get("domain")}
            for c in candidates
        ]
```
> 这是把"直接给词典加属性"落地的关键一步——结构变了,读它的代码也要跟着变(只此一处读它当字符串)。

## 改动 5 — `backend/services/abbr_service.py · _get_abbreviation_candidates()`

**A. fallback 候选补 domain**(NER 只产 domain,不过滤):在 fallback 块拿到 `candidates`、`candidate_source = "fallback"` 之后插入:
```python
            if candidate_source == "fallback":
                for candidate in candidates:
                    _, label, _ = self.ner_service.is_medical(candidate.get("expansion"))
                    candidate["domain"] = NER_LABEL_TO_DOMAIN.get(label)
```
> 词典候选已自带 domain(改动4),fallback 候选在这里补上,两路对齐。**不丢任何候选。**

**B. 填 `chosen_domain`**:在批次3-rev 的弃权门**之后**(`best` 可能被置 None),取选中候选的 domain:
```python
            best = coverage.get("best_expansion")

            # batch3-rev 弃权门(已存在,保持不动)
            if candidate_source == "fallback":
                conf = coverage.get("confidence") or 0.0
                if (not coverage.get("coverage_ok")) or conf < 0.8:
                    best = None

            # batch4:取选中候选的 domain
            best_domain = None
            if best:
                for candidate in candidates:
                    if candidate.get("expansion") == best:
                        best_domain = candidate.get("domain")
                        break
```
并把 `found.append({...})` 里的 `"chosen_domain": None` 改成 `"chosen_domain": best_domain`。

## 改动 6 — 激活 domain_boost

**A. `backend/services/medical_retriever.py`**:
- `retrieve`(67 行)签名加参数 `domain_boost: str | None = None`,并把它传给 `_rerank_results`:`results = self._rerank_results(query, results, domain_boost)`。
- `_rerank_results`(25 行)签名加 `domain_boost: str | None = None`;在算 `bonus`(39 行起)的循环里,**domain 命中加分**:
  ```python
          if domain_boost is not None and item.get("domain_id") == domain_boost:
              bonus += 0.2     # 软加分,数值待调
  ```
- **保留** `domain_filter` 原过滤逻辑(82 行)不动,继续传 None。

**B. `backend/services/abbr_service.py` 状态机检索调用**(约 431–435):把 `domain_filter=None` 旁边加 `domain_boost`:
```python
                    docs = self.retriever.retrieve(
                        query=s["expansion"],
                        top_k=10,
                        domain_filter=None,
                        domain_boost=s.get("domain"),
                        score_threshold=0.6
                    )
```

**C. state 里带上 domain**:状态机建 state 的地方(约 368–378,有 `"label": info.get("chosen_label")` 那处)加一行:
```python
                "domain": info.get("chosen_domain"),
```

---

## 验收

1. **能编译**:`python -m compileall backend/services/*.py backend/data/abbr_candidates.py`;批次1单测仍 `OK`。
2. **死参数激活可观测**:对某含心血管缩写的 case,确认 `domain_boost` 被传入、且 domain 匹配的 SNOMED 概念排名上升(可临时打印 `_rerank_results` 的结果对比)。
3. **standardized_entities 质量**:起服务 curl 一个 case(如 CP),看返回的 `concept_id/concept_name` 是否比批次5时更对路(如 CP 更倾向 Condition 域的概念)。
4. **benchmark 不回退**:`python backend/evaluation/run_benchmark_parallel.py`,对比 0.9595。**持平即合格**(本批不指望涨分);若**掉了**(说明 domain_boost 把某些扩写的 SNOMED 匹配带偏、连累 verify)→ 调小加分(0.2→0.1)或回退。
5. **判定**:死参数激活 + 编译/单测过 + benchmark 不回退 → 合入。

## 提交

```bash
git add -A
git commit -m "V11 batch4: activate domain_boost (NER label->SNOMED domain for fallback, domain metadata for dict)"
```
