# 批次 11A · 给 Codex 的指令(可整段复制)· 状态机数据流统一(纯行为中性重构)

## 背景与范围

当前 `expand_verify_with_retry` 里同一个缩写有**两种形状**:召回阶段 `candidate_infos`(含 best=None 的没扩项)与状态机阶段 `states`(只含扩了的),且"没扩的"不进 states。抓状态/错误得两头捞,零散易错。

本批把它**统一成一条 record 走到底**,带显式生命周期 `status` 和 `failure` 字段:
```
status: "NOT_EXPANDED" | "PENDING" | "CODED" | "WITHHELD" | "ABSTAIN"
failure: None | {type, stage, reason, evidence}
```
之后错误遥测、出口、留痕都从这一条 record 读。

> **这是纯行为中性重构**:只换内部数据形状,**不改任何对外行为**。硬约束:
> - 主 benchmark **必须仍 71/74 = 0.9595**,且失败仍是 `coverage_003/005/006` 这三例(逐例一致)。
> - API `/expand/simple` 出口形状不变:`success / expanded_text / mappings / standardized_entities` 照常。
> - 已核对:API 只读 `final_result.{expanded_text, mappings, mapping_standardizations[].{abbreviation,expansion,chosen_concept}}` + `result.success`;benchmark 只读 `final_result.{mappings, expanded_text}` + `result.success`。**这些字段一字不许变**;`mapping_states`/内部 status 字符串无人消费,可改。
> 任一约束没守住 → 回退。

工作在 `medical-refactor`(HEAD 飘了先 `git switch -f medical-refactor`)。

## 铁律

1. 先 Read `backend/services/abbr_service.py` 的 `expand_verify_with_retry`(约 160-387)整段核对。
2. **只整段替换 `expand_verify_with_retry` 一个方法**(从 `def expand_verify_with_retry` 到它最后的 `return {...}`)。**不动** `_get_abbreviation_candidates`、`_reflect_refine_standardization`、`_build_expanded_text_deterministic`、`_should_consider_abbreviation`、`__init__`、verifier、检索、API、benchmark。
3. 用下面给出的**完整新方法**整体替换,不要逐行手术。

---

## 替换:`expand_verify_with_retry` 整个方法 → 下面这版

```python
    def expand_verify_with_retry(self, text: str, max_retries: int = 2):
        """缩写扩写 + 标准化 + 校验。统一数据流:每个缩写从召回到出口是同一条 record,
        带显式 status 生命周期(NOT_EXPANDED/PENDING/CODED/WITHHELD/ABSTAIN)与 failure 字段。
        对外出口形状(mappings / mapping_standardizations.chosen_concept / expanded_text / success)与旧版一致。"""
        attempts = []
        candidate_infos = self._get_abbreviation_candidates(text)
        current_abbreviation_candidates = candidate_infos
        mapping_support_results = []
        standardization_result = None

        # —— 统一 record:一种形状走到底 ——
        records = []
        for info in candidate_infos:
            best = info.get("best_expansion")
            rec = {
                "abbreviation": info.get("abbreviation"),
                "source": info.get("candidate_source"),
                "candidates": info.get("candidates") or [],
                "coverage": info.get("coverage") or {},
                "expansion": best if best else None,
                "label": info.get("chosen_label"),
                "domain": info.get("chosen_domain"),
                "std_cache": None,
                "std_concept": None,
                "status": "PENDING" if best else "NOT_EXPANDED",
                "failure": None,
            }
            if rec["status"] == "NOT_EXPANDED":
                cov = rec["coverage"]
                rec["failure"] = {
                    "type": "ABBR_NOT_EXPANDED",
                    "stage": "coverage",
                    "reason": "coverage withheld expansion (not confident enough)",
                    "evidence": {
                        "coverage_confidence": cov.get("confidence"),
                        "coverage_ok": cov.get("coverage_ok"),
                        "candidates_seen": [c.get("expansion") for c in rec["candidates"]],
                    },
                }
            records.append(rec)

        def _expanded(recs):
            return [r for r in recs if r["expansion"]]

        def _visible(recs):
            # 进入文本/检索的:有扩写且未弃权(PENDING/CODED/WITHHELD)
            return [r for r in recs if r["expansion"] and r["status"] != "ABSTAIN"]

        current_expanded_text = self._build_expanded_text_deterministic(text, _visible(records))

        # —— 早停:没有任何缩写产出扩写(coverage_failed)——
        if not _expanded(records):
            attempt_result = {
                "attempt": 1,
                "expanded_text": current_expanded_text,
                "abbreviation_candidates": current_abbreviation_candidates,
                "mappings": [],
                "standardization": None,
                "mapping_standardizations": [],
                "verification": {
                    "sentence_validity": {
                        "is_valid": True,
                        "confidence": 1.0,
                        "reason": "No valid abbreviation expansion was produced; the text was left unchanged.",
                        "issues": []
                    },
                    "mapping_validations": [],
                    "overall_valid": False
                },
                "stop_reason": "coverage_failed_no_valid_expansion",
                "mapping_support_results": mapping_support_results,
                "mapping_states": [
                    {"abbreviation": r["abbreviation"], "expansion": r["expansion"],
                     "status": r["status"], "failure": r["failure"]}
                    for r in records
                ],
            }
            attempts.append(attempt_result)
            return {
                "original_text": text,
                "final_expanded_text": current_expanded_text,
                "success": False,
                "attempts": attempts,
                "final_result": attempt_result,
                "reason": "No valid abbreviation expansion found. Candidate coverage failed.",
            }

        # —— 重试循环:per-mapping 失败隔离 ——
        for attempt_index in range(max_retries + 1):
            pending = [r for r in records if r["status"] == "PENDING"]
            if not pending:
                break

            # 每个 PENDING 检索 SNOMED 候选
            for r in pending:
                docs = self.retriever.retrieve(
                    query=r["expansion"], top_k=10, domain_filter=None,
                    domain_boost=r.get("domain"), score_threshold=0.6,
                )
                r["std_cache"] = [
                    {
                        "concept_id": d["metadata"]["concept_id"],
                        "concept_name": d["metadata"]["concept_name"],
                        "domain_id": d["metadata"]["domain_id"],
                        "concept_code": d["metadata"]["concept_code"],
                        "score": d["metadata"]["score"],
                        "rerank_score": d["metadata"].get("rerank_score"),
                    }
                    for d in docs[:10]
                ]

            mapping_standardizations = [
                {"abbreviation": r["abbreviation"], "expansion": r["expansion"], "candidates": r["std_cache"]}
                for r in pending
            ]
            verification = self.verifier.verify_mappings(
                original_text=text, expanded_text=current_expanded_text,
                mapping_standardizations=mapping_standardizations,
            )
            validations = verification.get("mapping_validations", [])

            def _find_validation(rec):
                for v in validations:
                    if v.get("abbreviation") == rec["abbreviation"] and v.get("expansion") == rec["expansion"]:
                        return v
                return None

            # 扩写由 coverage 决定;verify 只选忠实 SNOMED 概念或弃码
            for r in pending:
                v = _find_validation(r)
                chosen_index = v.get("chosen_index") if v else None
                faithful = bool(v and v.get("standardization_faithful") is True)
                valid_index = (
                    faithful and isinstance(chosen_index, int) and not isinstance(chosen_index, bool)
                    and 0 <= chosen_index < len(r["std_cache"])
                )
                r["std_concept"] = r["std_cache"][chosen_index] if valid_index else None
                if r["std_concept"]:
                    r["status"] = "CODED"
                    r["failure"] = None
                else:
                    r["status"] = "WITHHELD"
                    r["failure"] = {
                        "type": "CODE_WITHHELD", "stage": "standardization",
                        "reason": (v.get("reason") if v else None) or "no faithful SNOMED concept among retrieved candidates",
                        "evidence": {"retrieved_top": [c.get("concept_name") for c in (r["std_cache"] or [])[:5]]},
                    }

            # batch10 标准化反思精炼;反思可能把 WITHHELD 救成 CODED
            for r in pending:
                self._reflect_refine_standardization(r, text, current_expanded_text)
                if r.get("std_concept") and r["status"] == "WITHHELD":
                    r["status"] = "CODED"
                    r["failure"] = None

            for item in mapping_standardizations:
                rec = next(
                    r for r in pending
                    if r["abbreviation"] == item["abbreviation"] and r["expansion"] == item["expansion"]
                )
                item["chosen_concept"] = rec["std_concept"]

            current_expanded_text = self._build_expanded_text_deterministic(text, _visible(records))

            attempts.append({
                "attempt": attempt_index + 1,
                "expanded_text": current_expanded_text,
                "abbreviation_candidates": current_abbreviation_candidates,
                "mappings": [
                    {"abbreviation": r["abbreviation"], "expansion": r["expansion"],
                     "label": r["label"], "source": r["source"], "status": r["status"]}
                    for r in records
                ],
                "standardization": standardization_result,
                "mapping_standardizations": mapping_standardizations,
                "verification": verification,
                "mapping_support_results": mapping_support_results,
            })

        # —— 循环结束:仍 PENDING 的 → 安全弃权 ——
        for r in records:
            if r["status"] == "PENDING":
                r["status"] = "ABSTAIN"
                r["failure"] = {
                    "type": "EXPANSION_ABSTAIN", "stage": "coverage",
                    "reason": "expansion candidates exhausted without a lock", "evidence": {},
                }

        # —— 终态出口(形状与旧版逐字段一致)——
        current_expanded_text = self._build_expanded_text_deterministic(text, _visible(records))
        resolved = [r for r in records if r["status"] in ("CODED", "WITHHELD")]
        final_mappings = [
            {"abbreviation": r["abbreviation"], "expansion": r["expansion"],
             "label": r["label"], "source": r["source"]}
            for r in resolved
        ]
        success = len(_expanded(records)) > 0 and all(
            r["status"] in ("CODED", "WITHHELD") for r in _expanded(records)
        )

        final_result = {
            "attempt": len(attempts),
            "expanded_text": current_expanded_text,
            "abbreviation_candidates": current_abbreviation_candidates,
            "mappings": final_mappings,
            "standardization": standardization_result,
            "mapping_standardizations": [
                {"abbreviation": r["abbreviation"], "expansion": r["expansion"],
                 "candidates": r["std_cache"], "chosen_concept": r["std_concept"]}
                for r in resolved
            ],
            "verification": attempts[-1]["verification"] if attempts else None,
            "mapping_support_results": mapping_support_results,
            "mapping_states": [
                {"abbreviation": r["abbreviation"], "expansion": r["expansion"],
                 "status": r["status"], "failure": r["failure"]}
                for r in records
            ],
        }

        return {
            "original_text": text,
            "final_expanded_text": current_expanded_text,
            "success": success,
            "attempts": attempts,
            "final_result": final_result,
        }
```

> 字段对齐说明(给你核对,不必照抄):旧 `LOCKED_OK`(扩了且锁定)= 新 `CODED`(给码)+ `WITHHELD`(弃码);旧 `final_mappings`/`mapping_standardizations` 取自 `LOCKED_OK` = 新取自 `CODED+WITHHELD`(=`resolved`),字段与旧版一致;`chosen_concept` 仅 `CODED` 非空,故 API 的 `standardized_entities` 不变;`_visible`(进文本的)= 有扩写且非 ABSTAIN,与旧 `status != LOCKED_ABSTAIN` 等价。

---

## 验收(强校验:重构=行为不变)

1. **编译+import**:`python -m compileall backend/services` 通过;`ABBRService` 干净 import。
2. **主 benchmark 逐例一致**:`python backend/evaluation/run_benchmark.py`
   - **必须 71/74 = 0.9595**,各分类与之前一致,失败仍恰为 `coverage_003/005/006`。**任何一例判分变化 = 重构改了行为,回退。**
3. **concept benchmark 不变**:`python backend/evaluation/run_concept_benchmark.py` → 仍 PASS 11/11、canonical 10/11(SOB=Dyspnea、CAD=Disorder of coronary artery)。(它直接调 retriever/verifier/反思,不走本方法,应天然不变;作为旁证。)
4. **API 冒烟**:起 uvicorn,`POST /expand/simple` 发 `{"text":"The patient has SOB and CP."}`,确认 `success/expanded_text/mappings/standardized_entities` 都正常返回(SOB、CP 仍出编码)。
5. **判定**:1-4 全过 → 合入;主 benchmark 任何逐例变化或 API 形状变化 → 回退。

## 提交

```bash
git add backend/services/abbr_service.py
git commit -m "V11 batch11A: unify state-machine data flow into a single per-mapping record (status lifecycle NOT_EXPANDED/PENDING/CODED/WITHHELD/ABSTAIN + failure field). Pure behavior-neutral refactor; main benchmark identical 71/74=0.9595, API contract unchanged."
```
> 这是纯重构,不该有任何判分变化。统一后,错误遥测/出口/留痕都从同一条 record 读;下一批(错误分析系统)只需读 `final_result.mapping_states[*].failure`,几行即可,不必再两头捞。
