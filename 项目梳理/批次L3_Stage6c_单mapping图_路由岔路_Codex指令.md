# 批次 L3 Stage-6c:LangGraph 改为单 mapping 粒度(路由岔路 + 反思环都显式)

## 目的
把可视化图的处理单位从"一次请求"降到"**单个缩写 mapping**",让两件事在图上都可见:
① L3 路由岔路(`route ┄Drug┄→ retrieve_rxnorm / ┄else┄→ retrieve_snomed`);
② 反思自纠环(`propose_requery→re_retrieve→re_verify` 回边)。
这是 agentic RAG 的标准画法(单 query 之旅)。外层"一句话多个 mapping"的编排留在 run() 包装里。

## 诚实口径(重要,写进日志)
- 整句图能严格 parity,是因为它照搬生产的"verify 批量判一次请求的多个 mapping"。
- 单 mapping 图把 verify 改成**逐个判** → 与生产**调用方式不同**(批量 vs 逐词),
  因此**不再是构造上逐字节等价**,而是**结果级一致**(temp=0 下通常仍一致,但非数学保证)。
- 口径:生产 = 批量优化版;LangGraph = 逐词参考模型;两者在 eval 上结果一致。
- 仍跑 parity 测试,但允许把它理解为"结果一致性检查"而非"等价证明";若多 mapping 句出现个别差异,
  贴出来一起判断(很可能是 verify 批量/逐词的 LLM 噪声,不是逻辑错)。

## 修改文件
- `backend/graph/standardization_graph.py`(整文件替换,见下)
- `backend/graph/render_graph.py`(parity 改为走 graph.run 的整句包装,见下小改)
- `项目梳理/L3_pipeline.mmd`(render 重新生成)
- `项目梳理/后续改进/codex对项目的改动日志.md`

## 整文件替换:`backend/graph/standardization_graph.py`
```python
"""
L3 Stage-6c: LangGraph 单 mapping 粒度可视化(路由岔路 + 反思环都显式)。

图建模"单个缩写 mapping 的 agentic 标准化之旅":
  route ─Drug→ retrieve_rxnorm / ─else→ retrieve_snomed → verify
       → (需反思?) propose_requery → re_retrieve → re_verify ⇄ propose_requery → finalize
外层"一句话里多个 mapping"的编排放在 run() 里(逐 mapping 跑图后拼回整句结果)。
节点只调 svc 现有方法;leaf 逻辑复刻 expand_verify_with_retry + _reflect_refine_standardization。
不进生产热路径。注:verify 逐 mapping 调用,与生产批量调用方式不同 → 结果级一致(非逐字节等价)。
"""
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from services.abbr_service import ABBRService


class MappingState(TypedDict, total=False):
    text: str
    expanded_text: str
    record: dict
    reflect_iter: int
    result: dict


def _is_exact(rec):
    sc = rec.get("std_concept")
    cn = sc.get("concept_name") if sc else None
    exp = rec.get("expansion")
    return bool(cn and exp and cn.strip().lower() == exp.strip().lower())


def _reflectable(rec):
    return rec.get("status") in ("CODED", "WITHHELD") and not _is_exact(rec)


class StandardizationGraph:
    def __init__(self, svc: Optional[ABBRService] = None, max_reflect_iter: int = 1):
        self.svc = svc or ABBRService()
        self.max_reflect_iter = max_reflect_iter
        self.app = self._build()

    # ---- 路由 + 双检索 ----
    def n_route(self, state):
        # 显式决策节点:把选中的源标到 record 上(供图阅读 / 调试);真正分流在条件边。
        r = state["record"]
        r["source"] = self.svc._route_source(r.get("domain"))
        return {"record": r}

    def _retrieve(self, r, source):
        docs = self.svc.retriever.retrieve(
            query=r["expansion"], top_k=10, domain_filter=None,
            domain_boost=r.get("domain"), score_threshold=0.6, source=source,
        )
        r["std_cache"] = [
            {"concept_id": d["metadata"]["concept_id"],
             "concept_name": d["metadata"]["concept_name"],
             "domain_id": d["metadata"]["domain_id"],
             "concept_code": d["metadata"]["concept_code"],
             "score": d["metadata"]["score"],
             "rerank_score": d["metadata"].get("rerank_score")}
            for d in docs[:10]
        ]

    def n_retrieve_snomed(self, state):
        self._retrieve(state["record"], "snomed")
        return {"record": state["record"]}

    def n_retrieve_rxnorm(self, state):
        self._retrieve(state["record"], "rxnorm")
        return {"record": state["record"]}

    def n_verify(self, state):
        svc, text, expanded, r = self.svc, state["text"], state["expanded_text"], state["record"]
        verification = svc.verifier.verify_mappings(
            original_text=text, expanded_text=expanded,
            mapping_standardizations=[{
                "abbreviation": r["abbreviation"], "expansion": r["expansion"],
                "candidates": r["std_cache"],
            }])
        vs = verification.get("mapping_validations", [])
        v = vs[0] if vs else None
        ci = v.get("chosen_index") if v else None
        faithful = bool(v and v.get("standardization_faithful") is True)
        valid = (faithful and isinstance(ci, int) and not isinstance(ci, bool)
                 and 0 <= ci < len(r["std_cache"]))
        r["std_concept"] = r["std_cache"][ci] if valid else None
        if r["std_concept"]:
            r["status"], r["failure"] = "CODED", None
        else:
            r["status"] = "WITHHELD"
            r["failure"] = {"type": "CODE_WITHHELD", "stage": "standardization",
                "reason": (v.get("reason") if v else None) or "no faithful SNOMED concept among retrieved candidates",
                "evidence": {"retrieved_top": [c.get("concept_name") for c in (r["std_cache"] or [])[:5]]}}
        return {"record": r}

    # ---- 反思环(复刻 _reflect_refine_standardization,逐 mapping)----
    def n_propose_requery(self, state):
        svc, r = self.svc, state["record"]
        r.pop("_requeries", None); r.pop("_new_cands", None)
        sc = r.get("std_concept")
        chosen_name = sc.get("concept_name") if sc else None
        seen = [c["concept_name"] for c in r["std_cache"]]
        r["_requeries"] = svc.verifier.propose_requeries(r["expansion"], chosen_name, seen) or []
        return {"record": r, "reflect_iter": state.get("reflect_iter", 0) + 1}

    def n_re_retrieve(self, state):
        svc, r = self.svc, state["record"]
        requeries = r.get("_requeries") or []
        if requeries:
            pool = {c["concept_id"]: c for c in r["std_cache"]}
            for rq in requeries:
                docs = svc.retriever.retrieve(
                    query=rq, top_k=10, domain_filter=None,
                    domain_boost=r.get("domain"), score_threshold=0.6,
                    source=svc._route_source(r.get("domain")),
                )
                for doc in docs:
                    md = doc["metadata"]
                    if md["concept_id"] not in pool:
                        pool[md["concept_id"]] = {
                            "concept_id": md["concept_id"], "concept_name": md["concept_name"],
                            "domain_id": md["domain_id"], "concept_code": md["concept_code"],
                            "score": md["score"], "rerank_score": md.get("rerank_score")}
            new_cands = sorted(pool.values(), key=lambda c: float(c.get("score") or 0), reverse=True)[:15]
            r["_new_cands"] = new_cands if len(new_cands) > len(r["std_cache"]) else None
        return {"record": r}

    def n_re_verify(self, state):
        svc, text, expanded, r = self.svc, state["text"], state["expanded_text"], state["record"]
        new_cands = r.get("_new_cands")
        requeries = r.get("_requeries") or []
        r.pop("_requeries", None); r.pop("_new_cands", None)
        if new_cands:
            verification = svc.verifier.verify_mappings(
                original_text=text, expanded_text=expanded,
                mapping_standardizations=[{
                    "abbreviation": r["abbreviation"], "expansion": r["expansion"],
                    "candidates": new_cands}])
            vs = verification.get("mapping_validations", [])
            v = vs[0] if vs else None
            ci = v.get("chosen_index") if v else None
            faithful = bool(v and v.get("standardization_faithful") is True)
            if faithful and isinstance(ci, int) and not isinstance(ci, bool) and 0 <= ci < len(new_cands):
                refined = new_cands[ci]
                requery_names = {q.strip().lower() for q in requeries}
                if refined.get("concept_name", "").strip().lower() in requery_names:
                    r["std_cache"] = new_cands
                    r["std_concept"] = refined
                    if r["status"] == "WITHHELD":
                        r["status"], r["failure"] = "CODED", None
        return {"record": r}

    def n_finalize(self, state):
        return {"result": state["record"]}

    def _enter_reflect(self, state):
        if state.get("reflect_iter", 0) >= self.max_reflect_iter:
            return "finalize"
        return "propose_requery" if _reflectable(state["record"]) else "finalize"

    def _build(self):
        g = StateGraph(MappingState)
        g.add_node("route", self.n_route)
        g.add_node("retrieve_snomed", self.n_retrieve_snomed)
        g.add_node("retrieve_rxnorm", self.n_retrieve_rxnorm)
        g.add_node("verify", self.n_verify)
        g.add_node("propose_requery", self.n_propose_requery)
        g.add_node("re_retrieve", self.n_re_retrieve)
        g.add_node("re_verify", self.n_re_verify)
        g.add_node("finalize", self.n_finalize)

        g.add_edge(START, "route")
        # L3 路由岔路:Drug → RxNorm,其它 → SNOMED
        g.add_conditional_edges("route",
            lambda s: "retrieve_rxnorm" if s["record"].get("domain") == "Drug" else "retrieve_snomed",
            {"retrieve_rxnorm": "retrieve_rxnorm", "retrieve_snomed": "retrieve_snomed"})
        g.add_edge("retrieve_snomed", "verify")
        g.add_edge("retrieve_rxnorm", "verify")
        g.add_conditional_edges("verify", self._enter_reflect,
            {"propose_requery": "propose_requery", "finalize": "finalize"})
        g.add_edge("propose_requery", "re_retrieve")
        g.add_edge("re_retrieve", "re_verify")
        g.add_conditional_edges("re_verify", self._enter_reflect,
            {"propose_requery": "propose_requery", "finalize": "finalize"})
        g.add_edge("finalize", END)
        return g.compile()

    # ---- 外层编排:逐 mapping 跑图,拼回整句结果(形状对齐生产 expand_verify_with_retry)----
    def run(self, text: str):
        svc = self.svc
        records = []
        for info in svc._get_abbreviation_candidates(text):
            best = info.get("best_expansion")
            records.append({
                "abbreviation": info.get("abbreviation"),
                "source": info.get("candidate_source"),
                "candidates": info.get("candidates") or [],
                "coverage": info.get("coverage") or {},
                "expansion": best if best else None,
                "label": info.get("chosen_label"),
                "domain": info.get("chosen_domain"),
                "std_cache": None, "std_concept": None,
                "status": "PENDING" if best else "NOT_EXPANDED", "failure": None,
            })
        visible = [r for r in records if r["expansion"] and r["status"] != "ABSTAIN"]
        expanded = svc._build_expanded_text_deterministic(text, visible)

        for r in records:
            if r["status"] == "PENDING":
                self.app.invoke({"text": text, "expanded_text": expanded, "record": r, "reflect_iter": 0})

        for r in records:
            if r["status"] == "PENDING":
                r["status"] = "ABSTAIN"
                r["failure"] = {"type": "EXPANSION_ABSTAIN", "stage": "coverage",
                                "reason": "expansion candidates exhausted without a lock", "evidence": {}}
        visible = [r for r in records if r["expansion"] and r["status"] != "ABSTAIN"]
        expanded = svc._build_expanded_text_deterministic(text, visible)
        resolved = [r for r in records if r["status"] in ("CODED", "WITHHELD")]
        expanded_records = [r for r in records if r["expansion"]]
        success = len(expanded_records) > 0 and all(
            r["status"] in ("CODED", "WITHHELD") for r in expanded_records)
        final_result = {
            "expanded_text": expanded,
            "mappings": [{"abbreviation": r["abbreviation"], "expansion": r["expansion"],
                          "label": r["label"], "source": r["source"]} for r in resolved],
            "mapping_standardizations": [{"abbreviation": r["abbreviation"], "expansion": r["expansion"],
                          "candidates": r["std_cache"], "chosen_concept": r["std_concept"]} for r in resolved],
            "mapping_states": [{"abbreviation": r["abbreviation"], "expansion": r["expansion"],
                          "status": r["status"], "failure": r["failure"]} for r in records],
        }
        return {"original_text": text, "final_expanded_text": expanded,
                "success": success, "final_result": final_result}

    def mermaid(self) -> str:
        return self.app.get_graph().draw_mermaid()
```

## 小改:`render_graph.py`
`run()` 现在是整句包装,签名/调用不变(仍 `g.run(text)`);**无需改 render_graph 的 parity 逻辑**。
确认 `g.run(text)` 仍返回 `{final_expanded_text, success, final_result:{...}}` 即可。

## 验收
1. `python -m compileall backend/graph` 通过。
2. `python backend/graph/render_graph.py`:
   - 重写 `项目梳理/L3_pipeline.mmd`;
   - **图里应出现路由岔路**:`route -.-> retrieve_rxnorm`、`route -.-> retrieve_snomed`;
     **以及反思环**:`verify -.-> propose_requery`、`re_verify -.-> propose_requery`(回边);
   - **parity**:理想 ALL PASS;`'The patient took ASA for chest pain.'` 应在图里走 retrieve_rxnorm 命中 aspirin,
     `'Patient reports SOB.'` 仍出 Dyspnea。若多 mapping 句(`CP and DM`)出现差异,贴 prod/graph 两行,
     大概率是 verify 批量 vs 逐词的 LLM 噪声(口径已说明),一起判断是否接受。
3. 贴回:mermaid 文本 + parity 结果。

## 合入 / 回滚
- 通过则提交 standardization_graph.py + L3_pipeline.mmd + 日志。
- 回滚:退回 Stage-6b 的整句图(parity 严格)。两版可二选一保留,看你要"严格 parity"还是"路由可见"。

## 面试讲法
- "我用 LangGraph 给**单个缩写的标准化**建了 agentic 图:先按 NER domain 路由到 RxNorm 或 SNOMED,
  检索→verify 判忠实度,不够规范就改写检索词重检索重判(自纠环,带最大迭代旋钮)。一句话里多个缩写,
  外层就是对每个 mapping 各跑一遍这张图、失败隔离。"
- "诚实点:生产为效率把 verify 批量判,这张逐词图是同逻辑的参考模型,在 eval 上结果一致——
  我把'路由可见、环路可见'看得比'逐字节等价'更重要,因为这张图的职责是讲清架构。"
