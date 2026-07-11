# 批次 L3 Stage-6:LangGraph 可视化包装(不改逻辑、不动分数、不进生产热路径)

## 目的
把 `ABBRService` 既有的"扩写 → 路由检索 → verify → 反思 → 收尾"用 LangGraph **重新表达成一张图**,
作为**可视化 + 备用入口**。节点只调用 ABBRService 现有方法(leaf 逻辑零重写,只复刻编排 glue);
用 **parity 测试**证明图的输出与生产状态机 `expand_verify_with_retry` 完全一致。

## 三个设计决定(为什么这么做)
1. **包装非重写**:节点调 `svc._get_abbreviation_candidates / retriever.retrieve / _route_source /
   verifier.verify_mappings / _reflect_refine_standardization / _build_expanded_text_deterministic`。
2. **并行非替换**:**不修改 `abbr_service.py`、不碰 `api/`**。LangGraph 不进 `/expand/simple` 热路径。
   → 主 benchmark 天然不受影响(仍 71/74=0.9595)。框架价值=可读流程图 + 标准 orchestration 语义,不是新能力。
3. **忠实建模**:现版 verify 一趟即出 CODED/WITHHELD,外层 max_retries 实际只跑一轮;真正的 agentic 回环在
   reflection 内部(propose_requeries→重检索→重 verify)。故图建成"单趟 + reflection 阶段",不画空转的大重试圈。

## 依赖
- `pip install langgraph`(batch7 删过 backend/graph/,本轮重新引入,但这次是可视化壳)。
- Codex 环境与 Li 本机都需装。

## 修改文件
- 新增 `backend/graph/__init__.py`(空)
- 新增 `backend/graph/standardization_graph.py`
- 新增 `backend/graph/render_graph.py`
- `项目梳理/后续改进/codex对项目的改动日志.md`(追加日志)
- 渲染产物 `项目梳理/L3_pipeline.mmd`(由 render 脚本生成)

## 文件 1:`backend/graph/standardization_graph.py`(基本照贴)
```python
"""
L3 Stage-6: LangGraph 可视化包装。
把 ABBRService 既有标准化链路用 LangGraph 重新表达;节点只调 svc 现有方法,
leaf 逻辑零重写,仅复刻 expand_verify_with_retry 的编排 glue(见该方法 line 165-408)。
不进生产热路径;正确性由 render_graph.py 的 parity 测试兜底。
"""
from typing import Optional, TypedDict
from langgraph.graph import StateGraph, START, END
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

    # ---- 节点:每个只调用 svc 现有方法 ----
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
        return {"records": records, "expanded_text": expanded,
                "has_expansion": any(r["expansion"] for r in records)}

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

    def n_reflect(self, state):
        svc, text, expanded = self.svc, state["text"], state["expanded_text"]
        # 复刻生产:对每个已解析(CODED/WITHHELD)record 跑反思;可把 WITHHELD 救成 CODED、或把 CODED 升 canonical
        for r in [r for r in state["records"] if r["status"] in ("CODED", "WITHHELD")]:
            svc._reflect_refine_standardization(r, text, expanded)
            if r.get("std_concept") and r["status"] == "WITHHELD":
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

    def _build(self):
        g = StateGraph(PipelineState)
        g.add_node("expand", self.n_expand)
        g.add_node("route_retrieve", self.n_route_retrieve)
        g.add_node("verify", self.n_verify)
        g.add_node("reflect", self.n_reflect)
        g.add_node("finalize", self.n_finalize)
        g.add_edge(START, "expand")
        # 真实的条件分支:coverage 一个都没扩出来 → 直接收尾(coverage_failed)
        g.add_conditional_edges("expand",
            lambda s: "route_retrieve" if s["has_expansion"] else "finalize",
            {"route_retrieve": "route_retrieve", "finalize": "finalize"})
        g.add_edge("route_retrieve", "verify")
        g.add_edge("verify", "reflect")       # 反思恒在路径上(是否真改动由函数内部早返回决定),保证 parity
        g.add_edge("reflect", "finalize")
        g.add_edge("finalize", END)
        return g.compile()

    def run(self, text: str):
        return self.app.invoke({"text": text})["result"]

    def mermaid(self) -> str:
        return self.app.get_graph().draw_mermaid()
```

## 文件 2:`backend/graph/render_graph.py`(渲染 mermaid + parity 测试)
```python
"""
渲染 L3 流程图(mermaid)+ parity 测试:
证明 LangGraph 包装与生产状态机 expand_verify_with_retry 输出一致。
跑法:python backend/graph/render_graph.py(需 Milvus + DeepSeek key)
"""
import os, sys
from pathlib import Path
os.environ["ERROR_LOG_RUNTIME"] = "0"
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))
from services.abbr_service import ABBRService
from graph.standardization_graph import StandardizationGraph

SAMPLES = [
    "The patient has CP and DM.",          # 常规 CODED
    "The patient took ASA for chest pain.", # L3 药品路由 RxNorm
    "Patient reports SOB.",                 # 触发反思(Dyspnea)
    "zzz qqq.",                             # coverage_failed / 不扩
]

def _sig(res):
    fr = res.get("final_result") or {}
    states = sorted((s["abbreviation"], s["expansion"], s["status"]) for s in fr.get("mapping_states", []))
    stds = sorted((m["abbreviation"], (m.get("chosen_concept") or {}).get("concept_id"))
                  for m in fr.get("mapping_standardizations", []))
    return (res.get("final_expanded_text"), res.get("success"), states, stds)

def main():
    svc = ABBRService()
    g = StandardizationGraph(svc)

    mmd = g.mermaid()
    out = BACKEND_DIR.parent / "项目梳理" / "L3_pipeline.mmd"
    out.write_text(mmd, encoding="utf-8")
    print("=== mermaid 已写入", out, "===\n")
    print(mmd)

    print("\n=== parity:graph vs expand_verify_with_retry ===")
    ok = True
    for text in SAMPLES:
        a = _sig(svc.expand_verify_with_retry(text))
        b = _sig(g.run(text))
        same = a == b
        ok = ok and same
        print(f"[{'PASS' if same else 'FAIL'}] {text!r}")
        if not same:
            print("  prod :", a)
            print("  graph:", b)
    print("\nPARITY:", "ALL PASS" if ok else "MISMATCH")

if __name__ == "__main__":
    main()
```

## 验收
1. `pip install langgraph` 成功。
2. `python -m compileall backend/graph` 通过。
3. `python backend/graph/render_graph.py`:
   - 打印 mermaid 并写入 `项目梳理/L3_pipeline.mmd`;
   - **parity 必须 ALL PASS**(4 条样例 graph 与生产输出完全一致)。
   - 若某条 FAIL,贴出 prod/graph 两行差异,先对齐节点逻辑再说,不要改生产代码去迁就图。
4. `python backend/evaluation/run_benchmark.py`:仍 71/74=0.9595(本轮没碰 abbr_service/api,应天然持平;跑一次确认无 import 副作用)。
5. 把 mermaid 文本 + parity 结果贴回来。

## 合入
- 验收通过提交:`backend/graph/__init__.py`、`backend/graph/standardization_graph.py`、
  `backend/graph/render_graph.py`、`项目梳理/L3_pipeline.mmd`、本日志文件。
- `requirements.txt` 若存在,加 `langgraph`。

## 回滚
- 删 `backend/graph/` 整个目录 + `项目梳理/L3_pipeline.mmd`。生产链路无任何依赖它,删了零影响。

## 面试讲法
- "我把既有的 agentic 标准化链路用 LangGraph 重新表达成一张可读的状态图(expand→route_retrieve→verify→reflect→finalize),
  节点复用同一批函数,并用 parity 测试证明与原状态机输出逐字段一致——**框架带来的是可视化与标准编排语义,不是新逻辑**。"
- "我没把它放进生产热路径:它对分数零贡献,我让框架待在可视化/备用入口,主链路仍是轻量确定性状态机——**框架要挣到钱才进热路径**。"
- "图里唯一的真条件分支是 coverage 没扩出任何词→直接收尾;agentic 回环(换同义词重检索)封装在 reflect 节点内部,忠实于代码实际行为(外层重试现版只跑一趟)。"
