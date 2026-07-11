"""
Current-run benchmark error triage.

Input:
    backend/evaluation/error_analysis_report.json

Output:
    backend/logs/triage/error_triage_report.md
    backend/logs/triage/candidate_gold_cases.json

This script follows one current-run chain only:
benchmark_results.json -> error_analysis_report.json -> error_triage.py.
It calls DeepSeek to turn the structured report into readable Chinese analysis.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env", override=True)

from services.diagnosis_explainer import explain_benchmark_payload

INPUT_REPORT = BACKEND_DIR / "evaluation" / "error_analysis_report.json"
OUT_DIR = BACKEND_DIR / "logs" / "triage"
REPORT = OUT_DIR / "error_triage_report.md"
CANDIDATE_GOLD = OUT_DIR / "candidate_gold_cases.json"


def load_current_report(path: Path = INPUT_REPORT) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"Current error analysis report not found: {path}. "
            "Run backend/evaluation/error_analysis_report.py first."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _compact_mapping_state(state: dict[str, Any]) -> dict[str, Any]:
    failure = state.get("failure") or {}
    coverage = state.get("coverage") or {}
    evidence = failure.get("evidence") or {}
    return {
        "abbreviation": state.get("abbreviation"),
        "expansion": state.get("expansion"),
        "source": state.get("source"),
        "status": state.get("status"),
        "coverage_ok": coverage.get("coverage_ok"),
        "coverage_confidence": coverage.get("confidence"),
        "coverage_issues": coverage.get("issues") or [],
        "failure_type": failure.get("type"),
        "failure_subtype": failure.get("subtype"),
        "failure_stage": failure.get("stage"),
        "failure_reason": failure.get("reason"),
        "suggestion": failure.get("suggestion"),
        "evidence_candidate_source": evidence.get("candidate_source"),
        "evidence_candidate_count": evidence.get("candidate_count"),
        "evidence_candidates_seen": evidence.get("candidates_seen") or [],
        "evidence_plausible_candidates": evidence.get("plausible_candidates") or [],
        "evidence_coverage_issues": evidence.get("coverage_issues") or [],
        "evidence_retrieved_top": evidence.get("retrieved_top") or [],
        "primary_called": evidence.get("primary_called"),
        "primary_candidate_count": evidence.get("primary_candidate_count"),
        "fallback_called": evidence.get("fallback_called"),
        "fallback_candidate_count": evidence.get("fallback_candidate_count"),
        "fallback_reason": evidence.get("fallback_reason"),
        "fallback_error_kind": evidence.get("fallback_error_kind"),
        "fallback_raw_output": evidence.get("fallback_raw_output"),
        "fallback_error": evidence.get("fallback_error"),
    }


def _is_expansion_blocked_state(state: dict[str, Any]) -> bool:
    return state.get("status") in ("NOT_EXPANDED", "ABSTAIN", "PENDING")


def _build_failure_detail(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "abbreviation": state.get("abbreviation"),
        "status": state.get("status"),
        "source": state.get("source"),
        "failure_type": state.get("failure_type"),
        "failure_subtype": state.get("failure_subtype"),
        "failure_stage": state.get("failure_stage"),
        "failure_reason": state.get("failure_reason"),
        "suggestion": state.get("suggestion"),
        "coverage_ok": state.get("coverage_ok"),
        "coverage_confidence": state.get("coverage_confidence"),
        "coverage_issues": state.get("coverage_issues") or [],
        "evidence_candidate_source": state.get("evidence_candidate_source"),
        "evidence_candidate_count": state.get("evidence_candidate_count"),
        "evidence_candidates_seen": state.get("evidence_candidates_seen") or [],
        "evidence_plausible_candidates": state.get("evidence_plausible_candidates") or [],
        "evidence_coverage_issues": state.get("evidence_coverage_issues") or [],
        "evidence_retrieved_top": state.get("evidence_retrieved_top") or [],
        "primary_called": state.get("primary_called"),
        "primary_candidate_count": state.get("primary_candidate_count"),
        "fallback_called": state.get("fallback_called"),
        "fallback_candidate_count": state.get("fallback_candidate_count"),
        "fallback_reason": state.get("fallback_reason"),
        "fallback_error_kind": state.get("fallback_error_kind"),
        "fallback_raw_output": state.get("fallback_raw_output"),
        "fallback_error": state.get("fallback_error"),
    }


def _summarize_field(states: list[dict[str, Any]], field: str) -> dict[str, int]:
    summary: dict[str, int] = {}
    for state in states:
        value = state.get(field)
        if not value:
            continue
        summary[value] = summary.get(value, 0) + 1
    return summary


def _compact_case(case: dict[str, Any]) -> dict[str, Any]:
    mapping_states = [
        _compact_mapping_state(state) for state in case.get("mapping_states") or []
    ]
    expansion_blocked_details = [
        _build_failure_detail(state)
        for state in mapping_states
        if _is_expansion_blocked_state(state)
    ]
    standardization_failure_details = [
        _build_failure_detail(state)
        for state in mapping_states
        if state.get("status") == "WITHHELD"
    ]

    return {
        "id": case.get("id"),
        "category": case.get("category"),
        "text": case.get("text"),
        "labels": case.get("labels") or {},
        "failure_reasons": case.get("failure_reasons") or [],
        "failure_type_summary": _summarize_field(mapping_states, "failure_type"),
        "failure_subtype_summary": _summarize_field(mapping_states, "failure_subtype"),
        "expansion_blocked_details": expansion_blocked_details,
        "standardization_failure_details": standardization_failure_details,
        "expected_mappings": case.get("expected_mappings") or [],
        "predicted_mappings": case.get("predicted_mappings") or [],
        "mapping_delta": case.get("mapping_delta") or {},
        "benchmark_correct": case.get("benchmark_correct"),
        "mapping_correct": case.get("mapping_correct"),
        "system_success": case.get("system_success"),
        "expansion_success": case.get("expansion_success"),
        "standardization_success": case.get("standardization_success"),
        "error_type": case.get("error_type"),
        "taxonomy": case.get("taxonomy") or {},
        "final_expanded_text": case.get("final_expanded_text"),
        "mapping_states": mapping_states,
    }


def _cases_with_label(cases: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
    return [case for case in cases if (case.get("labels") or {}).get(label)]


def build_payload(report: dict[str, Any]) -> dict[str, Any]:
    overall = report.get("overall_failure_analysis") or {}
    failure_cases = overall.get("failure_cases") or []

    compact_failure_cases = [_compact_case(case) for case in failure_cases]
    benchmark_cases = _cases_with_label(compact_failure_cases, "benchmark_mismatch")
    expansion_cases = _cases_with_label(compact_failure_cases, "expansion_blocked")
    standardization_cases = _cases_with_label(
        compact_failure_cases, "standardization_failure"
    )

    return {
        "input_file": str(INPUT_REPORT),
        "scope": "current benchmark run only",
        "benchmark_summary": report.get("benchmark_summary") or {},
        "overall_failure_analysis": {
            "total_cases": overall.get("total_cases"),
            "overall_success_count": overall.get("overall_success_count"),
            "overall_failure_count": overall.get("overall_failure_count"),
            "overall_success_rate": overall.get("overall_success_rate"),
            "success_definition": overall.get("success_definition") or {},
            "failure_definition": overall.get("failure_definition"),
            "failure_label_summary": overall.get("failure_label_summary") or {},
            "failure_set_relationship": overall.get("failure_set_relationship") or {},
            "failure_category_summary": overall.get("failure_category_summary") or {},
        },
        "diagnostic_summary": report.get("diagnostic_summary") or {},
        "failed_summary": report.get("failed_summary") or {},
        "failure_cases": compact_failure_cases,
        "benchmark_mismatch_cases": benchmark_cases,
        "expansion_blocked_cases": expansion_cases,
        "standardization_failure_cases": standardization_cases,
    }


def llm_triage(payload: dict[str, Any]) -> dict[str, Any]:
    return explain_benchmark_payload(payload)


def _fmt_dict(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _pct(rate: Any) -> str:
    if not isinstance(rate, (int, float)):
        return "N/A"
    return f"{rate:.2%}"


def _render_case(case: dict[str, Any]) -> list[str]:
    labels = case.get("labels") or {}
    active_labels = [name for name, enabled in labels.items() if enabled]
    return [
        f"### {case.get('id')} ({case.get('category')})",
        "",
        f"- Text: {case.get('text')}",
        f"- Labels: `{', '.join(active_labels)}`",
        f"- Failure reasons: `{_fmt_dict(case.get('failure_reasons') or [])}`",
        f"- Benchmark correct: {case.get('benchmark_correct')}",
        f"- Expansion success: {case.get('expansion_success')}",
        f"- Standardization success: {case.get('standardization_success')}",
        f"- Failure type summary: `{_fmt_dict(case.get('failure_type_summary') or {})}`",
        f"- Failure subtype summary: `{_fmt_dict(case.get('failure_subtype_summary') or {})}`",
        f"- Expansion blocked details: `{_fmt_dict(case.get('expansion_blocked_details') or [])}`",
        f"- Standardization failure details: `{_fmt_dict(case.get('standardization_failure_details') or [])}`",
        f"- Mapping delta: `{_fmt_dict(case.get('mapping_delta') or {})}`",
        f"- Mapping states: `{_fmt_dict(case.get('mapping_states') or [])}`",
        "",
    ]


def _render_cases(title: str, cases: list[dict[str, Any]]) -> list[str]:
    lines = [title, ""]
    if not cases:
        lines.extend(["- 本路径没有失败样例。", ""])
        return lines

    for case in cases:
        lines.extend(_render_case(case))
    return lines


def _render_notes(title: str, notes: list[dict[str, Any]]) -> list[str]:
    lines = [title, ""]
    if not notes:
        lines.extend(["- LLM 未生成该路径的人话解释。", ""])
        return lines

    for note in notes:
        labels = note.get("labels")
        lines.extend(
            [
                f"### {note.get('id')}",
                "",
                f"- 失败标签: `{_fmt_dict(labels)}`" if labels else "- 失败标签: `未提供`",
                f"- 发生了什么: {note.get('what_happened')}",
                f"- 可能原因: {note.get('likely_cause')}",
                f"- 下一步建议: {note.get('next_step')}",
                "",
            ]
        )
    return lines


def render_markdown(payload: dict[str, Any], triage: dict[str, Any]) -> str:
    benchmark = payload.get("benchmark_summary") or {}
    overall = payload.get("overall_failure_analysis") or {}
    relationship = overall.get("failure_set_relationship") or {}
    label_summary = overall.get("failure_label_summary") or {}
    diagnostics = payload.get("diagnostic_summary") or {}
    failed_summary = payload.get("failed_summary") or {}

    failure_cases = payload.get("failure_cases") or []
    benchmark_cases = payload.get("benchmark_mismatch_cases") or []
    expansion_cases = payload.get("expansion_blocked_cases") or []
    standardization_cases = payload.get("standardization_failure_cases") or []

    total_cases = overall.get("total_cases")
    success_count = overall.get("overall_success_count")
    failure_count = overall.get("overall_failure_count")
    success_rate = overall.get("overall_success_rate")

    lines = [
        "# 错误 Triage 报告",
        "",
        f"> 输入文件: `{INPUT_REPORT}`",
        "> 范围: 只分析当前这一轮 benchmark 生成的 error_analysis_report.json",
        f"> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "> 生成方式: DeepSeek 根据结构化错误报告生成中文解释",
        "",
        "## 1. 总体结论",
        "",
        str(triage.get("executive_summary") or "").strip(),
        "",
        f"- 总样例数(total_cases): {total_cases}",
        f"- 总成功数(overall_success): {success_count}",
        f"- 总失败数(overall_failure): {failure_count}",
        f"- 总成功率(overall_success_rate): {_pct(success_rate)}",
        "",
        "## 2. 口径说明",
        "",
        "| 指标 | 含义 | 本轮数值 |",
        "| --- | --- | --- |",
        (
            "| overall_success | 同时满足 benchmark_correct、expansion_success、"
            f"standardization_success 的 case 数 | {success_count} |"
        ),
        (
            "| overall_failure | benchmark_mismatch、expansion_blocked、"
            f"standardization_failure 任一成立的 case 数 | {failure_count} |"
        ),
        (
            "| benchmark_accuracy | predicted_mappings 与 gold expected_mappings 的对齐准确率 | "
            f"{benchmark.get('correct')}/{benchmark.get('total_cases')} = "
            f"{_pct(benchmark.get('accuracy'))} |"
        ),
        (
            "| expansion_success | 目标缩写 record 是否完成扩写的 case 级统计 | "
            f"{benchmark.get('expansion_success_count')} |"
        ),
        (
            "| standardization_success | 目标 record 是否全部 CODED 的 case 级统计 | "
            f"{benchmark.get('standardization_success_count')} |"
        ),
        "| record_status_summary | record 级状态计数，不是 case 数 | 见第 8 节 |",
        "",
        "## 3. 总失败集合关系",
        "",
        "```text",
        "overall_failure_cases = benchmark_mismatch ∪ expansion_blocked ∪ standardization_failure",
        "```",
        "",
        f"- benchmark_mismatch: {label_summary.get('benchmark_mismatch')}",
        f"- expansion_blocked: {label_summary.get('expansion_blocked')}",
        f"- standardization_failure: {label_summary.get('standardization_failure')}",
        f"- overall_failure: {failure_count}",
        "",
        "> 注意: 上面三个失败标签可以重叠，所以不能直接相加。",
        "",
        f"- 只有 benchmark_mismatch 的 case 数: {relationship.get('benchmark_mismatch_only_count')}",
        (
            "- 同时 benchmark_mismatch + standardization_failure 的 case 数: "
            f"{relationship.get('benchmark_mismatch_and_standardization_failure_count')}"
        ),
        (
            "- 同时 benchmark_mismatch + expansion_blocked 的 case 数: "
            f"{relationship.get('benchmark_mismatch_and_expansion_blocked_count')}"
        ),
        (
            "- expansion_blocked 是否全部包含在 standardization_failure 中: "
            f"{relationship.get('expansion_blocked_is_subset_of_standardization_failure')}"
        ),
        "",
        "## 4. 关键发现",
        "",
    ]

    for item in triage.get("key_findings") or []:
        lines.append(f"- {item}")
    if not triage.get("key_findings"):
        lines.append("- LLM 未生成关键发现。")

    lines.extend([""])
    lines.extend(_render_cases("## 5. benchmark 错误分析", benchmark_cases))
    lines.extend(_render_cases("## 6. 扩写错误分析", expansion_cases))
    lines.extend(_render_cases("## 7. 标准化错误分析", standardization_cases))

    lines.extend(
        [
            "## 8. record 级诊断",
            "",
            "下面这些字段直接来自 `error_analysis_report.json`。`record_status_summary` 是 record 数，不是 case 数。",
            "",
            "### 全量 record 诊断",
            "",
            f"```json\n{_fmt_dict(diagnostics)}\n```",
            "",
            "### benchmark 失败样例的 record 诊断",
            "",
            f"```json\n{_fmt_dict(failed_summary)}\n```",
            "",
        ]
    )

    lines.extend(_render_notes("## 9. 总失败样例的人话解释", triage.get("failure_case_notes") or []))
    lines.extend(_render_notes("## 10. benchmark 错误的人话解释", triage.get("benchmark_mismatch_notes") or []))
    lines.extend(_render_notes("## 11. 扩写错误的人话解释", triage.get("expansion_blocked_notes") or []))
    lines.extend(_render_notes("## 12. 标准化错误的人话解释", triage.get("standardization_failure_notes") or []))

    lines.extend(["## 13. 后续改进建议", ""])
    for item in triage.get("manual_followups") or []:
        lines.append(f"- {item}")
    if not triage.get("manual_followups"):
        lines.append("- LLM 未生成额外的人工跟进事项。")

    lines.extend(
        [
            "",
            "## 14. 使用边界",
            "",
            "- 本报告只分析当前 `error_analysis_report.json`，不会汇总历史错误。",
            "- `overall_success` 是本报告主口径，`benchmark_accuracy` 只是 gold 对齐辅助指标。",
            "- 失败标签可以重叠，标签数量不能直接相加。",
            "- record 级状态用于定位原因，不能直接当作 case 数。",
            "",
            "## 15. 总失败样例 ID",
            "",
            f"```json\n{_fmt_dict([case.get('id') for case in failure_cases])}\n```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    report = load_current_report()
    payload = build_payload(report)
    triage = llm_triage(payload)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_markdown(payload, triage), encoding="utf-8")

    candidates = triage.get("candidate_gold_case_drafts") or []
    CANDIDATE_GOLD.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Triage report saved to: {REPORT}")
    print(f"Candidate gold cases saved to: {CANDIDATE_GOLD}")


if __name__ == "__main__":
    main()
