# 批次 2 · 给 Codex 的指令(可整段复制)

---

## 背景(给你 Codex 的上下文)

接批次 1(已合入:coverage 选唯一 + 确定性 token 边界替换)。本批次(V11 批次 2)把 `expand_verify_with_retry` 的工作单位**从「整句」降到「单个 mapping」**:每个 mapping 走自己的状态链 `PENDING → 检索 → verify → LOCKED_OK / LOCKED_ABSTAIN`;失败只隔离重修它自己,锁定的冻结复用(增量重算);reflect 从「LLM 整句重写」改为「从候选池取下一个未试候选」(确定性,不调 LLM)。

工作在分支 `medical-refactor`,上一批是提交 `1871873`。

## 铁律

1. **先 Read 现状再改**:下面行号是批次 1 合入后(2026-06-20)的快照,动手前先 Read `abbr_service.py` 核对。
2. **只重写 `expand_verify_with_retry` 这一个方法**(从 `attempts = []` 到方法末尾的 return,即当前约 352–545 行,下一个方法 `_get_abbreviation_candidates` 之前)。其它方法一律不碰。
3. **不删不动**:`simple_llm_expansion`、`_rebuild_expanded_text`、`_build_expanded_text_deterministic`、`reflect`(旧整句重写,保留作 mode B)、`MappingSupportVerifier` 注释段、`_get_abbreviation_candidates`、`_should_consider_abbreviation`。
4. **不动**:verifier 内部、检索逻辑、Milvus/embedding、`.env`。
5. **保留 `attempts` 每轮留痕**(调试 + benchmark 归因要用)。

## ⚠️ 设计要点(防止把 why 做歪)

- **失败隔离**:每轮只处理 `status == PENDING` 的 mapping;`LOCKED_OK` 的**冻结**,不再检索、不再改写。
- **增量检索**:只对「本轮 expansion 变过(`changed=True`)」的 mapping 重新 `retriever.retrieve`;没变的复用 `std_cache`。
- **选择型 reflect = 取池里下一个未试候选**(确定性),**不调 LLM**。候选池来自召回阶段、固定不变;变的是"选池里哪个"。
- **弃权(LOCKED_ABSTAIN)= 安全失败**:某 mapping 的未试候选用尽仍不过 verify → 不扩它,**回退成原缩写**(不进最终 mappings)。医疗场景宁可不扩也不乱扩。
- **继续条件**靠"还有没有 PENDING",不是纯轮次;`max_retries` 只作防死循环的兜底上限。
- **终态出口**:最终 `mappings` 只含 `LOCKED_OK`;`expanded_text` 只替换未弃权的 mapping,弃权的保留原缩写。

---

## 改动 — 用下面整段替换 `expand_verify_with_retry` 的方法体

保留方法签名 `def expand_verify_with_retry(self, text: str, max_retries: int = 2):` 和上面的 docstring 不变;**把 docstring 之后、到本方法 return 结束的全部代码**替换为:

```python
        attempts = []

        candidate_infos = self._get_abbreviation_candidates(text)

        # —— 建 per-mapping 状态机条目 ——
        states = []
        for info in candidate_infos:
            best = info.get("best_expansion")
            if not best:
                continue
            # 候选池(确定性 reflect 的换候选空间);保证 best 排最前
            pool = [c.get("expansion") for c in info.get("candidates", []) if c.get("expansion")]
            if best in pool:
                pool = [best] + [e for e in pool if e != best]
            else:
                pool = [best] + pool
            states.append({
                "abbreviation": info["abbreviation"],
                "expansion": best,
                "label": info.get("chosen_label"),
                "source": info.get("candidate_source"),
                "status": "PENDING",
                "pool": pool,
                "tried": {best},
                "std_cache": None,
                "changed": True,
            })

        current_abbreviation_candidates = candidate_infos
        mapping_support_results = []
        standardization_result = None

        def _visible(state_list):
            # 进入句子/检索的 mapping:未弃权的(LOCKED_OK + PENDING)
            return [s for s in state_list if s["status"] != "LOCKED_ABSTAIN"]

        current_expanded_text = self._build_expanded_text_deterministic(text, _visible(states))

        # —— 早停:召回阶段没选出任何扩写 ——
        if not states:
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
                "mapping_support_results": mapping_support_results
            }
            attempts.append(attempt_result)
            return {
                "original_text": text,
                "final_expanded_text": current_expanded_text,
                "success": False,
                "attempts": attempts,
                "final_result": attempt_result,
                "reason": "No valid abbreviation expansion found. Candidate coverage failed."
            }

        # —— 重试循环:per-mapping 失败隔离 + 增量重算 ——
        for attempt_index in range(max_retries + 1):
            pending = [s for s in states if s["status"] == "PENDING"]
            if not pending:
                break

            # 增量检索:只对本轮 expansion 变过的 PENDING 重检索
            for s in pending:
                if s["changed"]:
                    docs = self.retriever.retrieve(
                        query=s["expansion"],
                        top_k=10,
                        domain_filter=None,
                        score_threshold=0.6
                    )
                    cand = []
                    for doc in docs[:3]:
                        md = doc["metadata"]
                        cand.append({
                            "concept_id": md["concept_id"],
                            "concept_name": md["concept_name"],
                            "domain_id": md["domain_id"],
                            "concept_code": md["concept_code"],
                            "score": md["score"],
                            "rerank_score": md.get("rerank_score"),
                        })
                    s["std_cache"] = cand
                    s["changed"] = False

            # 整句标准化(沿用 V9:存档留痕,不喂 verify)
            standardization_result = self.standardizer.standardize(current_expanded_text)

            # 只对 PENDING 做 verify(LOCKED_OK 冻结不复验)
            mapping_standardizations = [
                {
                    "abbreviation": s["abbreviation"],
                    "expansion": s["expansion"],
                    "candidates": s["std_cache"],
                }
                for s in pending
            ]
            verification = self.verifier.verify_mappings(
                original_text=text,
                expanded_text=current_expanded_text,
                mapping_standardizations=mapping_standardizations,
            )
            validations = verification.get("mapping_validations", [])

            def _find_validation(abbr):
                for v in validations:
                    if v.get("abbreviation") == abbr:
                        return v
                return None

            # 逐个 PENDING 判定:通过→LOCKED_OK;不过→换未试候选 or 弃权
            for s in pending:
                v = _find_validation(s["abbreviation"])
                passed = bool(v and v.get("is_valid") is True)
                if passed:
                    s["status"] = "LOCKED_OK"
                else:
                    untried = [e for e in s["pool"] if e not in s["tried"]]
                    if untried:
                        # 选择型 reflect:取池里下一个未试候选(确定性,不调 LLM)
                        s["expansion"] = untried[0]
                        s["tried"].add(untried[0])
                        s["changed"] = True
                    else:
                        s["status"] = "LOCKED_ABSTAIN"

            # 用未弃权的 mapping 重新确定性拼句
            current_expanded_text = self._build_expanded_text_deterministic(text, _visible(states))

            # 本轮留痕
            attempts.append({
                "attempt": attempt_index + 1,
                "expanded_text": current_expanded_text,
                "abbreviation_candidates": current_abbreviation_candidates,
                "mappings": [
                    {
                        "abbreviation": s["abbreviation"],
                        "expansion": s["expansion"],
                        "label": s["label"],
                        "source": s["source"],
                        "status": s["status"],
                    }
                    for s in states
                ],
                "standardization": standardization_result,
                "mapping_standardizations": mapping_standardizations,
                "verification": verification,
                "mapping_support_results": mapping_support_results,
            })

        # —— 循环结束:到达兜底次数仍 PENDING 的 → 安全弃权 ——
        for s in states:
            if s["status"] == "PENDING":
                s["status"] = "LOCKED_ABSTAIN"

        # —— 终态出口 ——
        current_expanded_text = self._build_expanded_text_deterministic(text, _visible(states))
        locked_ok = [s for s in states if s["status"] == "LOCKED_OK"]
        final_mappings = [
            {
                "abbreviation": s["abbreviation"],
                "expansion": s["expansion"],
                "label": s["label"],
                "source": s["source"],
            }
            for s in locked_ok
        ]
        success = len(states) > 0 and all(s["status"] == "LOCKED_OK" for s in states)

        final_result = {
            "attempt": len(attempts),
            "expanded_text": current_expanded_text,
            "abbreviation_candidates": current_abbreviation_candidates,
            "mappings": final_mappings,
            "standardization": standardization_result,
            "mapping_standardizations": [
                {
                    "abbreviation": s["abbreviation"],
                    "expansion": s["expansion"],
                    "candidates": s["std_cache"],
                }
                for s in locked_ok
            ],
            "verification": attempts[-1]["verification"] if attempts else None,
            "mapping_support_results": mapping_support_results,
            "mapping_states": [
                {"abbreviation": s["abbreviation"], "expansion": s["expansion"], "status": s["status"]}
                for s in states
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

> 说明给 Codex:`final_result["mappings"]` 只含 `LOCKED_OK`,弃权的 mapping 不进输出、其缩写在 `expanded_text` 里保留原样——benchmark 读的就是 `final_result.mappings`,这是本批行为变化的关键。

---

## 验收(改完做这些)

1. **能跑**:`python -m compileall backend/services/abbr_service.py` 通过;批次 1 的单测 `python backend/test_v11_deterministic.py` 仍 `OK`(本批没动那个纯函数)。
2. **失败隔离可观测**:对 `"Patient has CP and MS"` 跑一次,打印/检查 `attempts`:
   - CP 在第 1 轮 `LOCKED_OK` 后,第 2 轮起 **不在 pending、不再被检索**(看 `std_cache` 不再变、status 冻结)。
   - 只有失败的那个在换候选。
3. **benchmark**:`python backend/evaluation/run_benchmark.py`,逐类对比批次 1(总体 0.9400)。
   - **net accuracy ≥ 0.9400**。
   - **四个满分类(single/multi/negation/coverage_failed)+ ambiguous(批次1已 1.00)不许掉。**
   - low_context 能升最好(QRS/NOP 若 verify 拒 + 候选用尽 → 弃权掉出 → 案例可能转对)。
4. **成本**:多缩写用例的检索次数应**下降**(增量重算;数一下 attempts 里 retrieve 调用)。
5. **判定**:net ≥ 批次1 且满分类没掉 → 合入;否则 `git revert`,记原因。

## ⚠️ 诚实预期 + 主要风险(必读)

本批引入**弃权(over-abstention)**——这正是 V10 `MappingSupportVerifier` 回退的同款风险:verify 偶有误拒,一旦某 mapping 被误判 + 候选用尽 → 它被弃权、掉出输出 → **本来对的也可能丢**。所以:

- 重点盯**原本满分的类有没有因为弃权而掉**(尤其 single_meaning / multi_abbreviation:它们多是单候选,verify 一误拒就直接弃权,无候选可换)。
- 若 net 掉,**先别急着否定整个状态机**——大概率是「弃权太狠」。可作为回退后的下一步微调:对**单候选**的 mapping,verify 不过时**不直接弃权,保留扩写**(把弃权限定在"多候选试遍仍不过"),更贴近"该弃才弃"。但**这是 net 掉之后才动的旋钮**,先按上面原样跑一次拿到干净数字。

## 提交

```bash
git add -A
git commit -m "V11 batch2: per-mapping state machine + failure isolation + incremental retrieval"
```
