"""V11 生产标准化状态机的 LangGraph 参考实现。

该图用于流程展示和 parity 对照，不进入 FastAPI 生产热路径。图以单个
mapping 为执行粒度，外层 ``run`` 负责把多个 mapping 拼回一句话的结果。
生产链路仍由 ``ABBRService.expand_verify_with_retry`` 负责；本文件只跟随
生产状态、失败证据、反思停止条件和最终结果语义。

注意：Graph 的 verifier 是逐 mapping 调用，而生产服务会批量验证 pending
records。因此 parity 比较的是最终文本、状态和 concept_id，不宣称逐字节等价。
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
    def __init__(self, svc: Optional[ABBRService] = None, max_reflect_iter: int = 2):
        self.svc = svc or ABBRService()
        self.max_reflect_iter = max_reflect_iter
        self.app = self._build()

    # ---- 路由 + 双检索 ----
    def n_route(self, state):
        # 显式决策节点：把选中的源标到 record 上（供图阅读 / 调试）；真正分流在条件边。
        r = state["record"]
        r["source"] = self.svc._route_source(r.get("domain"))
        r.setdefault("_tried", {r["expansion"].strip().lower()})
        r["_reflect_stop"] = False
        return {"record": r}

    def _retrieve(self, r, source):
        docs = self.svc.retriever.retrieve(
            query=r["expansion"],
            top_k=10,
            domain_filter=None,
            domain_boost=r.get("domain"),
            score_threshold=0.6,
            source=source,
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

    @staticmethod
    def _withheld_failure(record, validation=None):
        """按生产 API 的语义记录标准化拒绝及其候选证据。"""
        validation = validation or {}
        return {
            "type": "CODE_WITHHELD",
            "stage": "standardization",
            "reason": validation.get("reason")
            or "no faithful clinical concept among retrieved candidates",
            "evidence": {
                "retrieved_top": [
                    c.get("concept_name")
                    for c in (record.get("std_cache") or [])[:5]
                ],
                "candidate_count": len(record.get("std_cache") or []),
                "source": record.get("source"),
                "domain": record.get("domain"),
            },
        }

    def n_retrieve_snomed(self, state):
        self._retrieve(state["record"], "snomed")
        return {"record": state["record"]}

    def n_retrieve_rxnorm(self, state):
        self._retrieve(state["record"], "rxnorm")
        return {"record": state["record"]}

    def n_verify(self, state):
        svc, text, expanded, r = (
            self.svc,
            state["text"],
            state["expanded_text"],
            state["record"],
        )
        verification = svc.verifier.verify_mappings(
            original_text=text,
            expanded_text=expanded,
            mapping_standardizations=[{
                "abbreviation": r["abbreviation"],
                "expansion": r["expansion"],
                "candidates": r["std_cache"],
            }],
        )
        vs = verification.get("mapping_validations", [])
        v = vs[0] if vs else None
        ci = v.get("chosen_index") if v else None
        faithful = bool(v and v.get("standardization_faithful") is True)
        valid = (
            faithful
            and isinstance(ci, int)
            and not isinstance(ci, bool)
            and 0 <= ci < len(r["std_cache"])
        )
        r["std_concept"] = r["std_cache"][ci] if valid else None
        if r["std_concept"]:
            r["status"], r["failure"] = "CODED", None
        else:
            r["status"] = "WITHHELD"
            r["failure"] = self._withheld_failure(r, v)
        return {"record": r}

    # ---- 反思环（复刻 _reflect_refine_standardization，逐 mapping）----
    def n_propose_requery(self, state):
        svc, r = self.svc, state["record"]
        r.pop("_requeries", None)
        r.pop("_new_cands", None)
        r["_rank_before"] = svc._std_rank(r)
        sc = r.get("std_concept")
        chosen_name = sc.get("concept_name") if sc else None
        seen = [c["concept_name"] for c in r["std_cache"]]
        requeries = svc.verifier.propose_requeries(r["expansion"], chosen_name, seen) or []
        tried = r.setdefault("_tried", {r["expansion"].strip().lower()})
        new_terms = [q for q in requeries if q.strip().lower() not in tried]
        if not new_terms:
            r["_reflect_stop"] = True
            r["_requeries"] = []
        else:
            tried.update(q.strip().lower() for q in new_terms)
            r["_requeries"] = new_terms
        return {"record": r, "reflect_iter": state.get("reflect_iter", 0) + 1}

    def n_re_retrieve(self, state):
        svc, r = self.svc, state["record"]
        requeries = r.get("_requeries") or []
        if requeries:
            pool = {c["concept_id"]: c for c in r["std_cache"]}
            for rq in requeries:
                docs = svc.retriever.retrieve(
                    query=rq,
                    top_k=10,
                    domain_filter=None,
                    domain_boost=r.get("domain"),
                    score_threshold=0.6,
                    source=svc._route_source(r.get("domain")),
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
            new_cands = sorted(
                pool.values(),
                key=lambda c: float(c.get("score") or 0),
                reverse=True,
            )[:15]
            r["_new_cands"] = new_cands if len(new_cands) > len(r["std_cache"]) else None
            if r["_new_cands"] is None:
                r["_reflect_stop"] = True
        return {"record": r}

    def n_re_verify(self, state):
        svc, text, expanded, r = (
            self.svc,
            state["text"],
            state["expanded_text"],
            state["record"],
        )
        new_cands = r.get("_new_cands")
        requeries = r.get("_requeries") or []
        rank_before = r.get("_rank_before", svc._std_rank(r))
        reflect_iter = state.get("reflect_iter", 0)
        r.pop("_requeries", None)
        r.pop("_new_cands", None)
        if new_cands:
            verification = svc.verifier.verify_mappings(
                original_text=text,
                expanded_text=expanded,
                mapping_standardizations=[{
                    "abbreviation": r["abbreviation"],
                    "expansion": r["expansion"],
                    "candidates": new_cands,
                }],
            )
            vs = verification.get("mapping_validations", [])
            v = vs[0] if vs else None
            ci = v.get("chosen_index") if v else None
            faithful = bool(v and v.get("standardization_faithful") is True)
            handled = False
            if (
                faithful
                and isinstance(ci, int)
                and not isinstance(ci, bool)
                and 0 <= ci < len(new_cands)
            ):
                refined = new_cands[ci]
                requery_names = {q.strip().lower() for q in requeries}
                if refined.get("concept_name", "").strip().lower() in requery_names:
                    refined_rank = 2 if refined.get("concept_name", "").strip().lower() == r["expansion"].strip().lower() else 1
                    if refined_rank <= rank_before:
                        # 横移：仅首轮(reflect_iter==1)采纳，之后停；次轮起不采纳横移。
                        if reflect_iter == 1:
                            r["std_cache"] = new_cands
                            r["std_concept"] = refined
                            if r["status"] == "WITHHELD":
                                r["status"], r["failure"] = "CODED", None
                        r["_reflect_stop"] = True
                        handled = True
                    else:
                        # 秩严格变高：采纳并允许继续。
                        r["std_cache"] = new_cands
                        r["std_concept"] = refined
                        if r["status"] == "WITHHELD":
                            r["status"], r["failure"] = "CODED", None
                        handled = True
            if not handled:
                r["_reflect_stop"] = True
        return {"record": r}

    def n_finalize(self, state):
        return {"result": state["record"]}

    def _enter_reflect(self, state):
        r = state["record"]
        if state.get("reflect_iter", 0) >= self.max_reflect_iter:
            return "finalize"
        if r.get("_reflect_stop"):
            return "finalize"
        return "propose_requery" if _reflectable(r) else "finalize"

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
        # L3 路由岔路：Drug → RxNorm，其它 → SNOMED
        g.add_conditional_edges(
            "route",
            lambda s: (
                "retrieve_rxnorm"
                if s["record"].get("domain") == "Drug"
                else "retrieve_snomed"
            ),
            {
                "retrieve_rxnorm": "retrieve_rxnorm",
                "retrieve_snomed": "retrieve_snomed",
            },
        )
        g.add_edge("retrieve_snomed", "verify")
        g.add_edge("retrieve_rxnorm", "verify")
        g.add_conditional_edges(
            "verify",
            self._enter_reflect,
            {"propose_requery": "propose_requery", "finalize": "finalize"},
        )
        g.add_edge("propose_requery", "re_retrieve")
        g.add_edge("re_retrieve", "re_verify")
        g.add_conditional_edges(
            "re_verify",
            self._enter_reflect,
            {"propose_requery": "propose_requery", "finalize": "finalize"},
        )
        g.add_edge("finalize", END)
        return g.compile()

    # ---- 外层编排：逐 mapping 跑图，拼回整句结果（形状对齐生产 expand_verify_with_retry）----
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
                "std_cache": None,
                "std_concept": None,
                "status": "PENDING" if best else "NOT_EXPANDED",
                "failure": None if best else info.get("failure"),
            })
        visible = [r for r in records if r["expansion"] and r["status"] != "ABSTAIN"]
        expanded = svc._build_expanded_text_deterministic(text, visible)

        attempts = []
        for r in records:
            if r["status"] == "PENDING":
                graph_result = self.app.invoke({
                    "text": text,
                    "expanded_text": expanded,
                    "record": r,
                    "reflect_iter": 0,
                })
                # 节点会就地更新 record，但显式回写返回状态，避免未来节点改为
                # 不可变状态时 Graph 外层悄悄丢失标准化结果。
                r.update(graph_result.get("record") or {})

        for r in records:
            if r["status"] == "PENDING":
                r["status"] = "ABSTAIN"
                r["failure"] = {
                    "type": "EXPANSION_ABSTAIN",
                    "stage": "coverage",
                    "reason": "expansion candidates exhausted without a lock",
                    "evidence": {},
                }
        visible = [r for r in records if r["expansion"] and r["status"] != "ABSTAIN"]
        expanded = svc._build_expanded_text_deterministic(text, visible)
        resolved = [r for r in records if r["status"] in ("CODED", "WITHHELD")]
        success_breakdown = svc._build_success_breakdown(records)
        expansion_success = success_breakdown["expansion_success"]
        standardization_success = success_breakdown["standardization_success"]
        success = expansion_success and standardization_success
        final_result = {
            "attempt": 1,
            "expanded_text": expanded,
            "abbreviation_candidates": [
                {
                    "abbreviation": r["abbreviation"],
                    "expansion": r.get("expansion"),
                    "source": r.get("source"),
                    "domain": r.get("domain"),
                }
                for r in records
            ],
            "mappings": [
                {
                    "abbreviation": r["abbreviation"],
                    "expansion": r["expansion"],
                    "label": r["label"],
                    "source": r["source"],
                    "status": r["status"],
                }
                for r in resolved
            ],
            "verification": None,
            "mapping_standardizations": [
                {
                    "abbreviation": r["abbreviation"],
                    "expansion": r["expansion"],
                    "candidates": r["std_cache"],
                    "chosen_concept": r["std_concept"],
                }
                for r in resolved
            ],
            "mapping_states": [
                {
                    "abbreviation": r["abbreviation"],
                    "expansion": r["expansion"],
                    "source": r["source"],
                    "status": r["status"],
                    "domain": r.get("domain"),
                    "chosen_concept": r.get("std_concept"),
                    "coverage": r["coverage"],
                    "failure": r["failure"],
                }
                for r in records
            ],
            "success_breakdown": success_breakdown,
        }
        return {
            "original_text": text,
            "final_expanded_text": expanded,
            "success": success,
            "expansion_success": expansion_success,
            "standardization_success": standardization_success,
            "success_breakdown": success_breakdown,
            "final_result": final_result,
        }

    def mermaid(self) -> str:
        return self.app.get_graph().draw_mermaid()
