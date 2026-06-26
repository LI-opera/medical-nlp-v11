"""
渲染 L3 流程图（mermaid）+ parity 测试。

证明 LangGraph 包装与生产状态机 expand_verify_with_retry 输出一致。
跑法：python backend/graph/render_graph.py（需 Milvus + DeepSeek key）
"""
import os
import sys
from pathlib import Path

os.environ["ERROR_LOG_RUNTIME"] = "0"

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
        (s["abbreviation"], s["expansion"], s["status"])
        for s in fr.get("mapping_states", [])
    )
    stds = sorted(
        (
            m["abbreviation"],
            (m.get("chosen_concept") or {}).get("concept_id"),
        )
        for m in fr.get("mapping_standardizations", [])
    )
    return (res.get("final_expanded_text"), res.get("success"), states, stds)


def main():
    svc = ABBRService()
    g = StandardizationGraph(svc)

    mmd = g.mermaid()
    out = BACKEND_DIR.parent / "项目梳理" / "L3_pipeline.mmd"
    out.write_text(mmd, encoding="utf-8")
    print("=== mermaid 已写入", out, "===\n")
    print(mmd)

    print("\n=== parity: graph vs expand_verify_with_retry ===")
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
