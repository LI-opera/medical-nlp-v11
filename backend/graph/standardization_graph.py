"""
L3 Stage-6: LangGraph 可视化包装。

把 ABBRService 既有标准化链路用 LangGraph 重新表达；节点只调 svc 现有方法，
leaf 逻辑零重写，仅复刻 expand_verify_with_retry 的编排 glue。
不进生产热路径；正确性由 render_graph.py 的 parity 测试兜底。
"""
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from services.abbr_service import ABBRService


class PipelineState(TypedDict, total=False):
    text: str
    records: list
    expanded_text: str
    has_expansion: bool
    result: dict


class StandardizationGraph:
    def __init__(self, svc: Optional[ABBRService] = None):
        self.svc = svc or ABBRService()
        self.app = self._build()

    # ---- 节点：每个只调用 svc 现有方法 ----
    def n_expand(self, state):
        svc, text = self.svc, state["text"]
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
                "failure": None,
            })
        visible = [r for r in records if r["expansion"] and r["status"] != "ABSTAIN"]
        expanded = svc._build_expanded_text_deterministic(text, visible)
        return {
            "records": records,
            "expanded_text": expanded,
            "has_expansion": any(r["expansion"] for r in records),
        }

    def n_route_retrieve(self, state):
        svc = self.svc
        for r in [r for r in state["records"] if r["status"] == "PENDING"]:
            docs = svc.retriever.retrieve(
                query=r["expansion"],
                top_k=10,
                domain_filter=None,
                domain_boost=r.get("domain"),
                score_threshold=0.6,
                source=svc._route_source(r.get("domain")),
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
        return {"records": state["records"]}

    def n_verify(self, state):
        svc, text, expanded = self.svc, state["text"], state["expanded_text"]
        pending = [r for r in state["records"] if r["status"] == "PENDING"]
        ms = [
            {
                "abbreviation": r["abbreviation"],
                "expansion": r["expansion"],
                "candidates": r["std_cache"],
            }
            for r in pending
        ]
        verification = svc.verifier.verify_mappings(
            original_text=text,
            expanded_text=expanded,
            mapping_standardizations=ms,
        )
        validations = verification.get("mapping_validations", [])

        def find(rec):
            for v in validations:
                if (
                    v.get("abbreviation") == rec["abbreviation"]
                    and v.get("expansion") == rec["expansion"]
                ):
                    return v
            return None

        for r in pending:
            v = find(r)
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
                r["failure"] = {
                    "type": "CODE_WITHHELD",
                    "stage": "standardization",
                    "reason": (
                        v.get("reason") if v else None
                    ) or "no faithful SNOMED concept among retrieved candidates",
                    "evidence": {
                        "retrieved_top": [
                            c.get("concept_name") for c in (r["std_cache"] or [])[:5]
                        ]
                    },
                }
        return {"records": state["records"]}

    def n_reflect(self, state):
        svc, text, expanded = self.svc, state["text"], state["expanded_text"]
        # 复刻生产：对每个已解析 record 跑反思；函数内部决定是否真正改写/重检索。
        for r in [
            r for r in state["records"] if r["status"] in ("CODED", "WITHHELD")
        ]:
            svc._reflect_refine_standardization(r, text, expanded)
            if r.get("std_concept") and r["status"] == "WITHHELD":
                r["status"], r["failure"] = "CODED", None
        visible = [r for r in state["records"] if r["expansion"] and r["status"] != "ABSTAIN"]
        return {
            "records": state["records"],
            "expanded_text": svc._build_expanded_text_deterministic(text, visible),
        }

    def n_finalize(self, state):
        svc, text, records = self.svc, state["text"], state["records"]
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
        expanded_records = [r for r in records if r["expansion"]]
        success = len(expanded_records) > 0 and all(
            r["status"] in ("CODED", "WITHHELD") for r in expanded_records
        )
        final_result = {
            "expanded_text": expanded,
            "mappings": [
                {
                    "abbreviation": r["abbreviation"],
                    "expansion": r["expansion"],
                    "label": r["label"],
                    "source": r["source"],
                }
                for r in resolved
            ],
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
                    "status": r["status"],
                    "failure": r["failure"],
                }
                for r in records
            ],
        }
        return {
            "result": {
                "original_text": text,
                "final_expanded_text": expanded,
                "success": success,
                "final_result": final_result,
            }
        }

    def _build(self):
        g = StateGraph(PipelineState)
        g.add_node("expand", self.n_expand)
        g.add_node("route_retrieve", self.n_route_retrieve)
        g.add_node("verify", self.n_verify)
        g.add_node("reflect", self.n_reflect)
        g.add_node("finalize", self.n_finalize)
        g.add_edge(START, "expand")
        # 真实条件分支：coverage 一个都没扩出来 → 直接收尾。
        g.add_conditional_edges(
            "expand",
            lambda s: "route_retrieve" if s["has_expansion"] else "finalize",
            {"route_retrieve": "route_retrieve", "finalize": "finalize"},
        )
        g.add_edge("route_retrieve", "verify")
        g.add_edge("verify", "reflect")
        g.add_edge("reflect", "finalize")
        g.add_edge("finalize", END)
        return g.compile()

    def run(self, text: str):
        return self.app.invoke({"text": text})["result"]

    def mermaid(self) -> str:
        return self.app.get_graph().draw_mermaid()
