# 批次 3 · 给 Codex 的指令(可整段复制)

---

## 背景(给你 Codex 的上下文)

接批次 2(已合入:per-mapping 状态机 + 失败隔离)。本批次(V11 批次 3)做三件事:
1. **NER 重新安置**:把本地 NER 模型从「整句标准化(算了不用)」挪到 **fallback 候选校验**——对 fallback(LLM 生成)的候选跑 `is_medical`,**杀掉明显非医学的烂候选**(如 NOP→"no operation"),并给候选打**类型 label**。
2. **fallback 一次产 top-k(≥3)**:给批次 2 的"换候选"留空间。
3. **召回路一致字段**:词典候选和 fallback 候选**都带 label**;把选中候选的 label 填进 `chosen_label`(批次 4 的 domain 软约束要用)。

核心理念:NER 是本地模型、和 deepseek 不同源 → **跨模型第二意见**,缓解同源盲区。

工作在分支 `medical-refactor`,上一批是提交 `573cad6`。

## 铁律

1. **先 Read 现状再改**:下面行号是批次 2 合入后(2026-06-20)快照,动手前先 Read 核对。
2. **不删不动**:批次 1/2 的成果(`_build_expanded_text_deterministic`、状态机、`simple_llm_expansion`、`_rebuild_expanded_text`、MappingSupportVerifier 注释)。
3. **NER 只过滤 fallback 候选,不过滤词典候选**——词典是人工策展的可信源,**绝不能因 is_medical 误判被丢**(否则 "lower motor neuron" 这类会被误杀)。词典候选只打 label、不删。
4. **不动** verifier / 状态机循环 / Milvus / embedding / `.env`。

---

## 改动 1 — `backend/services/ner_service.py` 加 `is_medical()`

在 `NERService` 类里加方法(复用现有 `self.ner_pipeline`,不新建模型):

```python
    def is_medical(self, text: str):
        """对孤立短语判是否医学实体 + 返回主 label。
        返回 (is_medical: bool, label: str|None, score: float)
        诚实局限:NER 对孤立短语可能误判,故此处只作【输入侧筛选的低置信信号】,
        且只用于过滤 fallback(LLM 生成)候选,不碰词典候选。
        """
        if not text:
            return False, None, 0.0
        ents = self.extract_entities(text)
        if not ents:
            return False, None, 0.0
        top = max(ents, key=lambda e: e["score"])
        return True, top["label"], top["score"]
```

## 改动 2 — `backend/services/abbr_service.py · __init__` 复用 NER 实例

在 `__init__` 里 `self.standardizer = MedicalStandardizer()` 那行**下方**加一行(复用,不重复加载模型):

```python
        self.ner_service = self.standardizer.ner_service
```

## 改动 3 — `backend/services/abbr_candidate_fallback_retriever.py` 保证 top-k(≥3)

在 `retrieve()` 的 prompt 的 `Rules` 列表末尾**追加一条**(当前最后一条是 11):

```
12. When the abbreviation plausibly has several medical meanings, return at least 3 candidate expansions, ranked by likelihood (most likely first).
```

解析处已返回 list、不截断,无需改结构。

## 改动 4 — `backend/services/abbr_service.py · _get_abbreviation_candidates()`

当前(批次2后)结构:primary 召回(约 595)→ 空则 fallback(约 599–605)→ `if not candidates` 早返回(约 607–626)→ coverage(约 628)→ `best`(约 641)→ `found.append`(约 644–653)。

**A. 插入 NER 校验 + 打 label**:在 fallback 块结束后、`#如果primary和fallback都没有候选` 那个 `if not candidates` 判断**之前**(约第 606 行,605 与 607 之间)插入:

```python
            # NER 校验 + 打 label:跨模型第二意见
            # - fallback 候选:is_medical=False → 丢弃(杀 LLM 生成的烂候选,如 no operation)
            # - 词典候选(primary):只打 label,绝不丢弃(可信源)
            labeled = []
            for candidate in candidates:
                expansion = candidate.get("expansion")
                ok, label, _ = self.ner_service.is_medical(expansion)
                candidate["label"] = label
                if candidate_source == "fallback" and not ok:
                    continue
                labeled.append(candidate)
            candidates = labeled
```

> 这样放的好处:NER 杀空 fallback 后,`candidates` 变空,正好被紧跟其后的现有 `if not candidates` 早返回分支接住(无需新加判断)。词典候选恒被保留、只多了 label 字段。

**B. 填 `chosen_label`**:把 `best = coverage.get("best_expansion")`(约 641)那一处,改为同时取出选中候选的 label:

```python
            best = coverage.get("best_expansion")
            best_label = None
            if best:
                for candidate in candidates:
                    if candidate.get("expansion") == best:
                        best_label = candidate.get("label")
                        break
```

并把 `found.append({...})`(约 644–653)里的 `"chosen_label":None` 改成 `"chosen_label":best_label`。`"chosen_domain":None` 暂留(批次 4 填)。

---

## 验收

1. **能编译**:`python -m compileall backend/services/abbr_service.py backend/services/ner_service.py`;批次1单测仍 `OK`。
2. **NER 杀烂候选可观测**:对 `"The patient has COPD and NOP."` 跑一次,看 attempts/候选:NOP 的 fallback 候选(如 "no operation")应被 NER 丢弃 → NOP 不进 mappings → `coverage_008` 有望转对。
3. **label 流起来**:跑任一含词典缩写的用例,检查 mappings 里 `label` 非空(词典候选也有 label)。
4. **benchmark**:`python backend/evaluation/run_benchmark.py`,对比批次 2(0.9400)。
   - **net ≥ 0.9400**;**五个满分类(single/multi/negation/coverage_failed/ambiguous)不许掉**。
   - low_context 能升最好(NOP 类有望转对)。
5. **判定**:net ≥ 批次2 且满分类没掉 → 合入;否则 `git revert`,记原因。

## ⚠️ 诚实预期 + 风险

- **能治的**:NOP→"no operation" 这类 fallback 幻觉,NER 大概率判非医学 → 丢弃 → `coverage_008` 转对。
- **未必治**:`QRS`→"QRS complex"(NER 可能识别为 ECG finding、判医学 → 留下);`LMN`(是**词典**缩写,不走 fallback、不被 NER 过滤 → 仍在,需后续 coverage 严格化,不在本批范围)。**别指望 low_context 一步满分。**
- **主要风险**:NER 误判把**好的 fallback 候选**判成非医学 → 丢了正确答案 → 回归。重点盯 `coverage_failed`(5/5)和任何依赖 fallback 的用例有没有掉。若掉,可把过滤放宽成"只在 is_medical=False **且** NER 分数高于阈值才丢",或回退本批。

## 提交

```bash
git add -A
git commit -m "V11 batch3: relocate NER to fallback candidate gate (is_medical) + labels + fallback top-k"
```
