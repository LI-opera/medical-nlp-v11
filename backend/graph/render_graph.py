"""生成 L3 Mermaid 图并执行 Graph/生产链路的 parity 对照。

本脚本只用于 Graph 参考实现的可视化和回归检查，不是生产 API 入口。
运行：``python backend/graph/render_graph.py``；需要 Milvus 和对应 LLM 配置。
"""
import json
import argparse
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))

from graph.standardization_graph import StandardizationGraph
from services.abbr_service import ABBRService


SAMPLES = [
    "The patient has CP and DM.",
    "The patient took ASA for chest pain.",
    "Patient reports SOB.",
    "zzz qqq.",
]


def _sig(res):
    fr = res.get("final_result") or {}
    states = sorted(
        (
            s.get("abbreviation"),
            s.get("expansion"),
            s.get("status"),
            (s.get("failure") or {}).get("type"),
        )
        for s in fr.get("mapping_states", [])
    )
    stds = sorted(
        (
            m["abbreviation"],
            (m.get("chosen_concept") or {}).get("concept_id"),
        )
        for m in fr.get("mapping_standardizations", [])
    )
    return {
        "final_expanded_text": res.get("final_expanded_text"),
        "success": res.get("success"),
        "expansion_success": res.get("expansion_success"),
        "standardization_success": res.get("standardization_success"),
        "success_breakdown": res.get("success_breakdown"),
        "states": states,
        "standardized_concepts": stds,
    }


def _diff(expected, actual):
    """只返回不一致字段，方便定位 Graph 与生产状态的差异。"""
    return {
        key: {"production": expected.get(key), "graph": actual.get(key)}
        for key in expected
        if expected.get(key) != actual.get(key)
    }


def _write_mermaid(graph):
    """将 Graph 结构写入 backend/graph，便于和 Graph 源码一起维护。"""
    mmd = graph.mermaid()
    out = BACKEND_DIR / "graph" / "L3_pipeline.mmd"
    out.write_text(mmd, encoding="utf-8")
    print("=== mermaid 已写入", out, "===\n")
    return out


def main(diagram_only=False):
    if diagram_only:
        # 生成结构图不需要加载 Embedding、Milvus 或 LLM；真实服务只在 parity 模式创建。
        graph = StandardizationGraph(svc=object())
        _write_mermaid(graph)
        return True

    svc = ABBRService()
    g = StandardizationGraph(svc)

    _write_mermaid(g)

    print("\n=== parity: graph vs expand_verify_with_retry ===")
    ok = True
    for text in SAMPLES:
        a = _sig(svc.expand_verify_with_retry(text))
        b = _sig(g.run(text))
        differences = _diff(a, b)
        same = not differences
        ok = ok and same
        print(f"[{'PASS' if same else 'FAIL'}] {text!r}")
        if differences:
            print(json.dumps(differences, ensure_ascii=False, indent=2, default=str))
    print("\nPARITY:", "ALL PASS" if ok else "MISMATCH")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="生成 V11 Graph 图并执行 parity 对照")
    parser.add_argument(
        "--diagram-only",
        action="store_true",
        help="只生成 Mermaid 图，不初始化 Embedding、Milvus 和 LLM",
    )
    args = parser.parse_args()
    main(diagram_only=args.diagram_only)
