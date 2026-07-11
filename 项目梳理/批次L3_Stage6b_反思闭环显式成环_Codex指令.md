# 批次 L3 Stage-6b:把反思闭环显式画成 LangGraph 环(真环·先等价)

## 目的
Stage-6 的图是直线——反思的"改写→重检索→重 verify"封在 reflect 一个节点里,LangGraph 的环路能力没体现。
本轮把 reflect **拆成 3 个节点 + 一条条件回边**,让图上真正出现一个环;同时用
`max_reflect_iter=1` 保证**行为与现在完全一致**(parity 仍 ALL PASS、零风险)。以后把这个旋钮调到 2~3
就是真多轮自纠(那是行为改变,需另跑 benchmark)。

## 关键纪律(parity 必须不变)
- 三个新节点必须**逐字复刻** `abbr_service._reflect_refine_standardization`(line 101-163)的逻辑:
  - 早返回:选中概念名精确同名扩写 → 不反思;
  - `propose_requeries(expansion, chosen_name, seen=std_cache 概念名)`;无改写词 → 不反思;
  - 池 = `{concept_id: c}`,对每个改写词路由重检索并入池;
  - `new_cands = sorted(pool, key=score desc)[:15]`;`len(new_cands) <= len(std_cache)` → 不采纳;
  - 重 verify;**保守门**:重选概念名(lower)必须 ∈ 改写词集合,才写回 std_cache/std_concept;
  - WITHHELD 被救出 → 升 CODED。
- **只动 `backend/graph/standardization_graph.py`**;不碰 abbr_service/api/render_graph。

## 修改文件
- `backend/graph/standardization_graph.py`(整文件替换,见下)
- `项目梳理/L3_pipeline.mmd`(render 脚本重新生成)
- `项目梳理/后续改进/codex对项目的改动日志.md`(追加日志)

## 整文件替换:`backend/graph/standardization_graph.py`
```python
"""
L3 Stage-6/6b: LangGraph 可视化包装(显式反思环)。

把 ABBRService 既有标准化链路用 LangGraph 重新表达;节点只调 svc 现有方法,
leaf 逻辑零重写,仅复刻编排 glue。反思被拆成 propose_requery→re_retrieve→re_verify
三节点 + 条件回边,在图上形成可见的 agentic 自纠环。
max_reflect_iter=1 时与生产状态机逐字段一致(parity);调大则为真多轮迭代(行为改变,需 benchmark)。
不进生产热路径;正确性由 render_graph.py 的 parity 测试兜底。
"""
from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from services.abbr_service import ABBRService


class PipelineState(TypedDict, total=False):
    text: str
    records: list
    expanded_text: str
    has_expansion: bool
    reflect_iter: int
    result: dict


def _is_exact(rec):
    """选中概念名是否精确同名扩写(精确 → 无需反思)。"""
    sc = rec.get("std_concept")
    cn = sc.get("concept_name") if sc else None
    exp = rec.get("expansion")
    return bool(cn and exp and cn.strip().lower() == exp.strip().lower())


def _reflectable(rec):
    return (
        rec.get("expansion")
        and rec.get("status") in ("CODED", "WITHHELD")
        and not _is_exact(rec)
    )


class StandardizationGraph:
    def __init__(self, svc: Optional[ABBRService] = None, max_reflect_iter: int = 1):
        self.svc = svc or ABBRService()
        self.max_reflect_iter = max_reflect_iter
        self.app = self._build()

    # ---- 主链路节点(与 Stage-6 相同)----
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
            "reflect_iter": 0,
        }

    def n_route_retrieve(self, state):
        svc = self.svc
        for r in [r for r in state["records"] if r["status"] == "PENDING"]:
            docs = svc.retriever.retrieve(
                query=r["expansion"], top_k=10, domain_filter=None,
                domain_boost=r.get("domain"), score_threshold=0.6,
                source=svc._route_source(r.get("domain")),
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
        return {"records": state["records"]}

    def n_verify(self, state):
        svc, text, expanded = self.svc, state["text"], state["expanded_text"]
        pending = [r for r in state["records"] if r["status"] == "PENDING"]
        ms = [{"abbreviation": r["abbreviation"], "expansion": r["expansion"],
               "candidates": r["std_cache"]} for r in pending]
        verification = svc.verifier.verify_mappings(
            original_text=text, expanded_text=expanded, mapping_standardizations=ms)
        validations = verification.get("mapping_validations", [])

        def find(rec):
            for v in validations:
                if v.get("abbreviation") == rec["abbreviation"] and v.get("expansion") == rec["expansion"]:
                    return v
            return None

        for r in pending:
            v = find(r)
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
        return {"records": state["records"]}

    # ---- 反思环:propose_requery → re_retrieve → re_verify(复刻 _reflect_refine_standardization)----
    def n_propose_requery(self, state):
        svc = self.svc
        for r in state["records"]:
            r.pop("_requeries", None)
            r.pop("_new_cands", None)
            if not _reflectable(r):
                continue
            sc = r.get("std_concept")
            chosen_name = sc.get("concept_name") if sc else None
            seen = [c["concept_name"] for c in r["std_cache"]]
            r["_requeries"] = svc.verifier.propose_requeries(r["expansion"], chosen_name, seen) or []
        return {"records": state["records"], "reflect_iter": state.get("reflect_iter", 0) + 1}

    def n_re_retrieve(self, state):
        svc = self.svc
        for r in state["records"]:
            requeries = r.get("_requeries")
            if not requeries:
                continue
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
                            "concept_id": md["concept_id"],
                            "concept_name": md["concept_name"],
                            "domain_id": md["domain_id"],
                            "concept_code": md["concept_code"],
                            "score": md["score"],
                            "rerank_score": md.get("rerank_score"),
                        }
            new_cands = sorted(pool.values(), key=lambda c: float(c.get("score") or 0), reverse=True)[:15]
            r["_new_cands"] = new_cands if len(new_cands) > len(r["std_cache"]) else None
        return {"records": state["records"]}

    def n_re_verify(self, state):
        svc, text, expanded = self.svc, state["text"], state["expanded_text"]
        for r in state["records"]:
            new_cands = r.get("_new_cands")
            requeries = r.get("_requeries") or []
            r.pop("_requeries", None)
            r.pop("_new_cands", None)
            if not new_cands:
                continue
            verification = svc.verifier.verify_mappings(
                original_text=text, expanded_text=expanded,
                mapping_standardizations=[{
                    "abbreviation": r["abbreviation"], "expansion": r["expansion"],
                    "candidates": new_cands,
                }])
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
        visible = [r for r in state["records"] if r["expansion"] and r["status"] != "ABSTAIN"]
        return {"records": state["records"],
                "expanded_text": svc._build_expanded_text_deterministic(text, visible)}

    def n_finalize(self, state):
        svc, text, records = self.svc, state["text"], state["records"]
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
        return {"result": {"original_text": text, "final_expanded_text": expanded,
                           "success": success, "final_result": final_result}}

    # ---- 条件:是否进/继续反思环 ----
    def _enter_reflect(self, state):
        if state.get("reflect_iter", 0) >= self.max_reflect_iter:
            return "finalize"
        return "propose_requery" if any(_reflectable(r) for r in state["records"]) else "finalize"

    def _build(self):
        g = StateGraph(PipelineState)
        g.add_node("expand", self.n_expand)
        g.add_node("route_retrieve", self.n_route_retrieve)
        g.add_node("verify", self.n_verify)
        g.add_node("propose_requery", self.n_propose_requery)
        g.add_node("re_retrieve", self.n_re_retrieve)
        g.add_node("re_verify", self.n_re_verify)
        g.add_node("finalize", self.n_finalize)

        g.add_edge(START, "expand")
        g.add_conditional_edges("expand",
            lambda s: "route_retrieve" if s["has_expansion"] else "finalize",
            {"route_retrieve": "route_retrieve", "finalize": "finalize"})
        g.add_edge("route_retrieve", "verify")
        # verify 后:需要反思就进环,否则收尾
        g.add_conditional_edges("verify", self._enter_reflect,
            {"propose_requery": "propose_requery", "finalize": "finalize"})
        g.add_edge("propose_requery", "re_retrieve")
        g.add_edge("re_retrieve", "re_verify")
        # re_verify 后:回到改写(形成可见环)或收尾;max_reflect_iter=1 时恒收尾(=现行为)
        g.add_conditional_edges("re_verify", self._enter_reflect,
            {"propose_requery": "propose_requery", "finalize": "finalize"})
        g.add_edge("finalize", END)
        return g.compile()

    def run(self, text: str):
        return self.app.invoke({"text": text})["result"]

    def mermaid(self) -> str:
        return self.app.get_graph().draw_mermaid()
```

## 验收
1. `python -m compileall backend/graph` 通过。
2. `python backend/graph/render_graph.py`:
   - 重新写入 `项目梳理/L3_pipeline.mmd`,打印 mermaid;
   - **图里应出现环**:`verify -.-> propose_requery`、`re_verify -.-> propose_requery`(回边)、`re_verify -.-> finalize`;
   - **parity 必须仍 ALL PASS**(尤其 `'Patient reports SOB.'` 要复刻出 Dyspnea;若 FAIL 贴 prod/graph 差异,只调 graph glue,别动生产)。
3. 把 mermaid 文本 + parity 结果贴回来。

## 合入
- 验收通过提交:`backend/graph/standardization_graph.py`、`项目梳理/L3_pipeline.mmd`、本日志文件。

## 回滚
- 退回 Stage-6 的单节点 `n_reflect` 版本(或删 backend/graph/)。生产链路不依赖,零影响。

## 面试讲法
- "反思是一个自纠检索环:verify 觉得不够忠实/不够规范 → 改写检索词 → 重检索 → 重 verify → 回到判定。
  我用 LangGraph 把这个环显式画出来,并留了 `max_reflect_iter` 旋钮:=1 时与现行为逐字段一致(有 parity 测试证明),
  调大即真多轮自纠——但那是行为改变,要用 concept/main benchmark 卡关再决定。**先把环接对、再谈要不要真转。**"
