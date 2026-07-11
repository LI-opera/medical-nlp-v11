# 批次 10 · 给 Codex 的指令(可整段复制)· 标准化反思精炼(reflect → 换同义词重检索 → 重选)

## 背景与范围

concept benchmark 现状:PASS 11/11=1.0、canonical 9/11=0.818。两个非 canonical:
- **SOB**:选到 'Difficulty breathing'(忠实但口语),最规范是 'Dyspnea'。**探针已证**:用同义词 "dyspnea" 重检索把 'Dyspnea' 搜进池后,verify 会选它 → canonical。**这是本批目标。**
- **CAD**:verify 故意留通用父概念 'Disorder of coronary artery',拒绝加"动脉硬化"机理 → 这是**正确**行为(符合 batch9"不加未声明限定词"),**本批不追 CAD**。

本批加一个**标准化反思步骤(真正的闭环,带新证据非橡皮图章)**:当 verify 选中的概念**不是扩写的精确同名**(或弃码)时,反思让 LLM 提同义/规范检索词 → 换词重检索 → 并入候选池 → verify 重选。只升级不强降(原候选仍在池中,verify 可回退)。

> 目标:concept bench **SOB 升到 canonical(9/11→10/11)**;**PASS 仍 11/11、其余一个都不许回归**;**主 benchmark 持平 0.9595**。

工作在 `medical-refactor`(HEAD 飘了先 `git switch -f medical-refactor`)。

## 铁律

1. 先 Read `backend/services/abbr_verifier.py`、`backend/services/abbr_service.py`、`backend/evaluation/run_concept_benchmark.py` 核对再改。
2. 不改 coverage、不改检索/rerank 核心、不改 verify_mappings 的判定标准(batch9 那段)、不改状态机其它逻辑。本批只**新增**:verifier 一个反思方法 + abbr_service 一个精炼方法及其调用 + bench 跑这步。
3. 反思 LLM(propose_requeries)**只产检索词,绝不产/选概念**;选概念仍只由 verify_mappings 做。
4. 三道验收门(见下)全过才合入;任何回归或主 bench 掉分 → 回退。

---

## A · `backend/services/abbr_verifier.py`:新增反思方法 `propose_requeries`

在 `ABBVerifier` 类里(`verify_mappings` 方法之后)新增:

```python
    def propose_requeries(self, expansion: str, current_concept, seen_concepts):
        """标准化反思:为 expansion 提出最多 2 个【同义/规范检索词】,
        以图检回比 current_concept 更标准的 SNOMED 概念。
        只产检索词,绝不产/选概念。"""
        prompt = f"""
        You are refining a SNOMED standardization by REFORMULATING the search query.

        Clinical term (expansion): {expansion}
        Current best SNOMED concept: {current_concept if current_concept else "none yet"}
        Already-retrieved concepts (avoid repeating): {json.dumps(list(seen_concepts), ensure_ascii=False)}

        Propose up to 2 alternative SEARCH phrasings for "{expansion}" - exact clinical
        synonyms or the single standard medical term - likely to retrieve a MORE STANDARD
        / more canonical SNOMED concept than the current one.
        - Output SEARCH WORDS only. Never invent or output a SNOMED concept.
        - Each phrasing must mean EXACTLY the same clinical thing as the expansion; do not
          add a subtype, cause, stage, acuity, site, or mechanism.
        - If you cannot think of a faithful alternative, return an empty list.
        - Return raw valid JSON only, no markdown: {{"requeries": ["phrase one", "phrase two"]}}
        """
        try:
            response = self.llm.invoke(prompt)
            content = response.content.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(content)
            out = []
            for q in data.get("requeries", []):
                if isinstance(q, str) and q.strip() and q.strip().lower() != expansion.strip().lower():
                    out.append(q.strip())
            return out[:2]
        except Exception:
            return []
```
> `json` 已在文件顶部 import,无需新增。

---

## B · `backend/services/abbr_service.py`:新增精炼方法 + 在状态机调用

**B1. 新增方法**(加在 `ABBRService` 类内,例如 `_build_expanded_text_deterministic` 之后):

```python
    def _reflect_refine_standardization(self, s, original_text, expanded_text):
        """batch10 标准化反思:选中概念若非扩写精确同名(或弃码),反思换同义词重检索一次,
        让 verify 在更全候选里重选。只升级不强降(原候选仍在池中,verify 可回退原选)。"""
        expansion = s["expansion"]
        chosen = s.get("std_concept")
        chosen_name = chosen.get("concept_name") if chosen else None
        # 已是精确同名 → 无需反思
        if chosen_name and chosen_name.strip().lower() == expansion.strip().lower():
            return
        seen = [c["concept_name"] for c in s["std_cache"]]
        requeries = self.verifier.propose_requeries(expansion, chosen_name, seen)
        if not requeries:
            return
        # 换同义词重检索,并入候选池去重
        pool = {c["concept_id"]: c for c in s["std_cache"]}
        for rq in requeries:
            docs = self.retriever.retrieve(
                query=rq, top_k=10, domain_filter=None,
                domain_boost=s.get("domain"), score_threshold=0.6,
            )
            for doc in docs:
                md = doc["metadata"]
                if md["concept_id"] not in pool:
                    pool[md["concept_id"]] = {
                        "concept_id": md["concept_id"],
                        "concept_name": md["concept_name"],
                        "domain_id": md["domain_id"],
                        "concept_code": md["concept_code"],
                        "score": md["score"],
                        "rerank_score": md.get("rerank_score"),
                    }
        new_cands = sorted(pool.values(), key=lambda c: float(c.get("score") or 0), reverse=True)[:15]
        if len(new_cands) <= len(s["std_cache"]):
            return  # 没带回新候选
        verification = self.verifier.verify_mappings(
            original_text=original_text,
            expanded_text=expanded_text,
            mapping_standardizations=[{
                "abbreviation": s["abbreviation"],
                "expansion": expansion,
                "candidates": new_cands,
            }],
        )
        vs = verification.get("mapping_validations", [])
        v = vs[0] if vs else None
        ci = v.get("chosen_index") if v else None
        faithful = bool(v and v.get("standardization_faithful") is True)
        if faithful and isinstance(ci, int) and not isinstance(ci, bool) and 0 <= ci < len(new_cands):
            s["std_cache"] = new_cands
            s["std_concept"] = new_cands[ci]
```

**B2. 在状态机调用**:在 per-pending 判定循环(以 `s["status"] = "LOCKED_OK"` 结尾那段)**之后**、`for item in mapping_standardizations:` 写回 chosen_concept **之前**,插入:

```python
            # batch10: 标准化反思精炼(只对本轮 pending;非精确同名/弃码才触发)
            for s in pending:
                self._reflect_refine_standardization(s, text, current_expanded_text)
```
> 这样精炼后的 `s["std_concept"]` 会被随后的 `item["chosen_concept"] = state["std_concept"]` 正常写回与留痕。`status` 仍 LOCKED_OK。

---

## C · `backend/evaluation/run_concept_benchmark.py`:让 bench 量到反思

当前 bench 直接 retrieve+verify、不走状态机,会量不到反思。改成:初始 retrieve+verify 选概念后,**用与状态机相同的字段构造一个临时 state dict,调用同一个 `_reflect_refine_standardization`**,再读精炼后的概念。

- 顶部新增 `from services.abbr_service import ABBRService`;`main()` 里实例化一次 `svc = ABBRService()`,用 `svc.retriever`、`svc.verifier`、`svc._reflect_refine_standardization`(替换原来单独的 MedicalRetriever/ABBVerifier 实例)。
- 把"对一个 case 取概念"的流程改为:
  ```python
  cands = [d["metadata"] for d in svc.retriever.retrieve(
      query=case["expansion"], top_k=10, domain_filter=None, score_threshold=0.6)]
  # 初始 verify 选概念
  res = svc.verifier.verify_mappings(
      original_text=f"The patient has {case['expansion']}.",
      expanded_text=f"The patient has {case['expansion']}.",
      mapping_standardizations=[{"abbreviation": case["label"],
                                 "expansion": case["expansion"], "candidates": cands}])
  mv = (res.get("mapping_validations") or [{}])[0]
  ci = mv.get("chosen_index")
  init = cands[ci] if (isinstance(ci, int) and not isinstance(ci, bool) and 0 <= ci < len(cands)) else None
  # 构造 state 调同一个反思方法(domain=None:bench 给的是正确扩写,不依赖 domain_boost)
  s = {"abbreviation": case["label"], "expansion": case["expansion"],
       "std_cache": cands, "std_concept": init, "domain": None}
  svc._reflect_refine_standardization(s, f"The patient has {case['expansion']}.",
                                      f"The patient has {case['expansion']}.")
  chosen = s["std_concept"]["concept_name"] if s.get("std_concept") else None
  ```
- 其余(judge / canonical 统计 / 打印)不变。
> 说明:bench 复用了状态机同一个 `_reflect_refine_standardization`(反思 LLM 与编排都走真代码),所以量的就是上线行为,不是另写一套。

---

## 验收(强校验)

1. **编译+import**:`python -m compileall backend/services backend/evaluation` 通过;`ABBRService`、`ABBVerifier` 干净 import。
2. **concept benchmark**:`python backend/evaluation/run_concept_benchmark.py`
   - **SOB 升到 canonical**(选中 'Dyspnea')。
   - **PASS 仍 11/11**;canonical **9→10**;**其余 case 一个都不许从 PASS 掉**(尤其 CAD 仍 PASS=选 'Disorder of coronary artery';CP/DM/MI/PNA/CHF/HTN/ASTHMA/AFIB/RA 仍 canonical)。
3. **主 benchmark**:`python backend/evaluation/run_benchmark.py` → **必须 ~0.9595 持平**(反思在标准化层,碰不到扩写判分;掉分=有外溢,回退)。
4. **判定**:1-3 全过、SOB 升 canonical 且零回归 → 合入;任何回归或主 bench 掉 → 回退。

## 提交

```bash
git add backend/services/abbr_verifier.py backend/services/abbr_service.py backend/evaluation/run_concept_benchmark.py
git commit -m "V11 batch10: standardization reflection (reflect -> synonym re-query -> re-verify) lifts faithful-but-non-canonical picks (SOB -> Dyspnea); concept canonical 9/11->10/11, PASS 11/11 held, main benchmark flat 0.9595. CAD intentionally left at faithful parent."
```
> 面试叙事:这是项目里**唯一带 LLM 在环的反思闭环**,且**只在选到将就概念时触发、靠"换同义词重检索"带来新证据**(非同源复判),还有 concept bench 量它的真实收益——区别于 V9 那个被实测为橡皮图章的整句反思。
